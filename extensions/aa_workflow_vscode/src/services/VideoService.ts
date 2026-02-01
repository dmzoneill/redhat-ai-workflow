/**
 * VideoService - Video Preview Business Logic
 *
 * Handles video streaming and capture operations without direct UI dependencies.
 * Uses MessageBus for UI communication and NotificationService for user feedback.
 */

import * as fs from "fs";
import { promisify } from "util";
import { exec } from "child_process";
import { StateStore } from "../state";
import { MessageBus } from "./MessageBus";
import { NotificationService } from "./NotificationService";
import { createLogger } from "../logger";

const execAsync = promisify(exec);
const logger = createLogger("VideoService");

// ============================================================================
// Types
// ============================================================================

export interface VideoServiceDependencies {
  state: StateStore;
  messages: MessageBus;
  notifications: NotificationService;
  queryDBus: (service: string, path: string, iface: string, method: string, args?: any[]) => Promise<any>;
}

export type VideoMode = "webrtc" | "mjpeg" | "snapshot";

export interface VideoPreviewState {
  active: boolean;
  device: string;
  mode: VideoMode;
}

export interface VideoFrame {
  dataUrl: string;
  resolution: string;
}

// ============================================================================
// VideoService Class
// ============================================================================

export class VideoService {
  private state: StateStore;
  private messages: MessageBus;
  private notifications: NotificationService;
  private queryDBus: VideoServiceDependencies['queryDBus'];

  // Video preview state
  private _active = false;
  private _device = "/dev/video10";
  private _mode: VideoMode = "webrtc";
  private _process: any = null;

  private readonly VIDEO_DBUS = {
    service: "com.aiworkflow.BotVideo",
    path: "/com/aiworkflow/BotVideo",
    interface: "com.aiworkflow.BotVideo",
  };

  constructor(deps: VideoServiceDependencies) {
    this.state = deps.state;
    this.messages = deps.messages;
    this.notifications = deps.notifications;
    this.queryDBus = deps.queryDBus;
  }

  // ============================================================================
  // State
  // ============================================================================

  /**
   * Get current video preview state
   */
  getPreviewState(): VideoPreviewState {
    return {
      active: this._active,
      device: this._device,
      mode: this._mode,
    };
  }

  /**
   * Check if preview is active
   */
  isActive(): boolean {
    return this._active;
  }

  // ============================================================================
  // Start/Stop
  // ============================================================================

  /**
   * Start video preview in the specified mode.
   *
   * Modes:
   * - webrtc: Hardware-accelerated H.264 via Intel VAAPI, streamed via WebRTC (~6W, <50ms latency)
   * - mjpeg: Hardware JPEG encoding via VAAPI, HTTP stream (~8W, ~100ms latency)
   * - snapshot: Legacy ffmpeg frame capture (~35W, ~500ms latency)
   */
  async startPreview(device: string, mode: VideoMode = "webrtc"): Promise<boolean> {
    this._device = device || "/dev/video10";
    this._mode = mode;
    this._active = true;

    logger.log(`Starting preview: device=${device}, mode=${mode}`);

    if (mode === "webrtc" || mode === "mjpeg") {
      // For WebRTC/MJPEG modes, start the streaming pipeline via D-Bus
      try {
        await this.queryDBus(
          this.VIDEO_DBUS.service,
          this.VIDEO_DBUS.path,
          this.VIDEO_DBUS.interface,
          "StartStreaming",
          [
            { type: "string", value: device },
            { type: "string", value: mode },
            { type: "string", value: String(mode === "webrtc" ? 8765 : 8766) },
          ]
        );

        this.messages.publish("videoPreviewStarted", {
          mode,
          device,
        });

        logger.log(`Streaming started via D-Bus: ${mode}`);
        return true;
      } catch (e: any) {
        logger.log(`D-Bus streaming start failed: ${e.message}, falling back to direct check`);

        // Check if device exists for snapshot fallback
        if (!fs.existsSync(this._device)) {
          this.messages.publish("videoPreviewError", {
            error: `Device ${this._device} not found. Start the video daemon first.`,
          });
          this._active = false;
          return false;
        }

        // For WebRTC/MJPEG, the webview will connect directly to the streaming server
        this.messages.publish("videoPreviewStarted", {
          mode,
          device,
          note: "Connecting directly to streaming server",
        });
        return true;
      }
    } else {
      // Snapshot mode - check if device exists
      if (!fs.existsSync(this._device)) {
        this.messages.publish("videoPreviewError", {
          error: `Device ${this._device} not found. Is the video daemon running?`,
        });
        this._active = false;
        return false;
      }

      this.messages.publish("videoPreviewStarted", {
        mode: "snapshot",
        device,
      });
      return true;
    }
  }

  /**
   * Stop video preview
   */
  async stopPreview(): Promise<void> {
    this._active = false;

    // Stop streaming via D-Bus if using WebRTC/MJPEG
    if (this._mode === "webrtc" || this._mode === "mjpeg") {
      try {
        await this.queryDBus(
          this.VIDEO_DBUS.service,
          this.VIDEO_DBUS.path,
          this.VIDEO_DBUS.interface,
          "StopStreaming",
          []
        );
        logger.log("Streaming stopped via D-Bus");
      } catch (e: any) {
        logger.log(`D-Bus streaming stop failed: ${e.message}`);
      }
    }

    // Kill any running ffmpeg process (snapshot mode)
    if (this._process) {
      try {
        this._process.kill();
      } catch (e) {
        // Ignore
      }
      this._process = null;
    }

    logger.log("Stopped video preview");
  }

  // ============================================================================
  // Frame Capture (Snapshot Mode)
  // ============================================================================

  /**
   * Get a single frame for snapshot mode (legacy, high CPU usage).
   *
   * This uses ffmpeg to capture from v4l2, which is inefficient but works
   * without the streaming pipeline. Use WebRTC or MJPEG modes for better
   * performance.
   */
  async captureFrame(): Promise<VideoFrame | null> {
    if (!this._active || this._mode !== "snapshot") {
      return null;
    }

    try {
      // Capture a single frame from the v4l2 device using ffmpeg
      const tmpFile = `/tmp/video_preview_${Date.now()}.jpg`;

      await execAsync(
        `ffmpeg -f v4l2 -video_size 640x360 -i ${this._device} -vframes 1 -f image2 -y ${tmpFile} 2>/dev/null`,
        { timeout: 2000 }
      );

      // Read the file and convert to base64
      if (fs.existsSync(tmpFile)) {
        const imageBuffer = fs.readFileSync(tmpFile);
        const base64 = imageBuffer.toString("base64");
        const dataUrl = `data:image/jpeg;base64,${base64}`;

        // Get resolution from device
        let resolution = "640x360";
        try {
          const { stdout } = await execAsync(
            `v4l2-ctl -d ${this._device} --get-fmt-video 2>/dev/null | grep "Width/Height" | head -1`,
            { timeout: 1000 }
          );
          const match = stdout.match(/(\d+)\/(\d+)/);
          if (match) {
            resolution = `${match[1]}x${match[2]}`;
          }
        } catch (e) {
          // Use default
        }

        // Clean up temp file
        try {
          fs.unlinkSync(tmpFile);
        } catch (e) {
          // Ignore
        }

        return { dataUrl, resolution };
      }
    } catch (e: any) {
      logger.log(`Frame capture error: ${e.message}`);
    }

    return null;
  }

  /**
   * Capture frame and publish to UI
   */
  async captureAndPublishFrame(): Promise<void> {
    const frame = await this.captureFrame();
    if (frame) {
      this.messages.publish("videoPreviewFrame", frame);
    }
  }
}
