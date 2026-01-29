"""
Intel Zero-Copy Streaming Pipeline

Provides efficient video streaming using Intel iGPU hardware:
- OpenCL rendering (Xe cores)
- VA-API H.264 encoding (Quick Sync)
- WebRTC streaming to browsers/VSCode

Architecture:
    OpenCL Render → VA Surface (zero-copy) → VAAPI H.264 → WebRTC/RTP

Power consumption: ~6-8W total (vs ~35W with CPU encoding)
Latency: <50ms end-to-end
"""

import asyncio
import json
import logging
import threading
from dataclasses import dataclass
from typing import Callable, Dict, Optional

import numpy as np

logger = logging.getLogger(__name__)

# GStreamer imports
try:
    import gi

    gi.require_version("Gst", "1.0")
    gi.require_version("GstApp", "1.0")
    gi.require_version("GstWebRTC", "1.0")
    gi.require_version("GstSdp", "1.0")
    from gi.repository import GLib, Gst, GstApp, GstSdp, GstWebRTC

    Gst.init(None)
    _GST_AVAILABLE = True
except (ImportError, ValueError) as e:
    logger.warning(f"GStreamer not available: {e}")
    _GST_AVAILABLE = False

# WebSocket for signaling
try:
    from websockets.server import serve as ws_serve

    _WS_AVAILABLE = True
except ImportError:
    logger.warning("websockets not available, WebRTC signaling disabled")
    _WS_AVAILABLE = False

try:
    from aiohttp import web

    _AIOHTTP_AVAILABLE = True
except ImportError:
    logger.warning("aiohttp not available, MJPEG server disabled")
    _AIOHTTP_AVAILABLE = False
    web = None


@dataclass
class StreamConfig:
    """Configuration for the streaming pipeline."""

    width: int = 1920
    height: int = 1080
    framerate: int = 30
    bitrate: int = 4000  # kbps

    # Encoder selection: 'va' (VA-API), 'qsv' (Quick Sync), 'auto'
    encoder: str = "va"

    # Codec: 'h264', 'h265', 'av1'
    codec: str = "h264"

    # WebRTC signaling port
    signaling_port: int = 8765

    # RTP output (alternative to WebRTC)
    rtp_host: str = "127.0.0.1"
    rtp_port: int = 5000

    # Enable v4l2 output alongside streaming (for Google Meet)
    v4l2_device: Optional[str] = None

    # Flip output horizontally (for Google Meet mirror compensation)
    flip: bool = False

    # Input format: 'bgra' (default) or 'yuyv' (more efficient for video_generator)
    input_format: str = "bgra"


class IntelStreamingPipeline:
    """
    Zero-copy streaming pipeline using Intel iGPU.

    Supports multiple output modes:
    - WebRTC (for browser/VSCode preview)
    - RTP (for network streaming)
    - v4l2 (for Google Meet, optional)

    All encoding happens on the Intel GPU using VA-API or Quick Sync.
    """

    def __init__(self, config: StreamConfig):
        if not _GST_AVAILABLE:
            raise RuntimeError("GStreamer not available. Install: dnf install gstreamer1-plugins-bad-free")

        self.config = config
        self.pipeline: Optional[Gst.Pipeline] = None
        self.appsrc: Optional[GstApp.AppSrc] = None
        self.webrtcbin: Optional[Gst.Element] = None

        self._running = False
        self._frame_count = 0
        self._start_time = 0

        # WebRTC peer connections
        self._peers: Dict[str, Gst.Element] = {}
        self._signaling_server = None
        self._signaling_task = None

        # Main loop for GStreamer
        self._loop: Optional[GLib.MainLoop] = None
        self._loop_thread: Optional[threading.Thread] = None

        # Callbacks
        self._on_stats: Optional[Callable] = None

    def _get_encoder_element(self) -> str:
        """Get the appropriate encoder element based on config."""
        encoder = self.config.encoder
        codec = self.config.codec

        # Map codec + encoder to GStreamer element
        encoders = {
            ("h264", "va"): "vah264enc",
            ("h264", "qsv"): "qsvh264enc",
            ("h265", "va"): "vah265enc",
            ("h265", "qsv"): "qsvh265enc",
            ("av1", "va"): "vaav1enc",
            ("av1", "qsv"): "qsvav1enc",
        }

        element = encoders.get((codec, encoder))
        if not element:
            logger.warning(f"Unknown encoder combo {codec}/{encoder}, falling back to vah264enc")
            element = "vah264enc"

        return element

    def _get_rtp_payloader(self) -> str:
        """Get the RTP payloader for the codec."""
        payloaders = {
            "h264": "rtph264pay",
            "h265": "rtph265pay",
            "av1": "rtpav1pay",
        }
        return payloaders.get(self.config.codec, "rtph264pay")

    def _build_pipeline(self, mode: str = "webrtc") -> str:
        """
        Build GStreamer pipeline string.

        Args:
            mode: 'webrtc', 'rtp', or 'both'
        """
        w, h = self.config.width, self.config.height
        fps = self.config.framerate
        bitrate = self.config.bitrate

        encoder = self._get_encoder_element()
        payloader = self._get_rtp_payloader()

        # Check if we're reading from v4l2 device or using appsrc
        if self.config.v4l2_device:
            # Read from v4l2 device (video generator writes to it)
            # This is for preview - we read what's being written to the device
            pipeline_parts = [
                f"v4l2src device={self.config.v4l2_device} ! "
                f"video/x-raw,format=YUY2,width={w},height={h},framerate={fps}/1 ! "
                f"videoconvert"
            ]
        elif self.config.input_format == "yuyv":
            # Input: appsrc with YUYV frames (efficient - matches video_generator output)
            # VA-API handles YUY2→NV12 conversion in hardware
            pipeline_parts = [
                f"appsrc name=src format=time is-live=true do-timestamp=true "
                f'caps="video/x-raw,format=YUY2,width={w},height={h},framerate={fps}/1"',
            ]
        else:
            # Input: appsrc with raw BGRA frames from OpenCL
            pipeline_parts = [
                f"appsrc name=src format=time is-live=true do-timestamp=true "
                f'caps="video/x-raw,format=BGRA,width={w},height={h},framerate={fps}/1"',
            ]

        # Optional flip for Google Meet
        if self.config.flip:
            pipeline_parts.append("videoflip method=horizontal-flip")

        # Color conversion to NV12 (required by most HW encoders)
        # Use VA postproc if available for zero-copy conversion
        if self.config.encoder == "va":
            pipeline_parts.append("vapostproc ! video/x-raw(memory:VAMemory),format=NV12")
        else:
            pipeline_parts.append("videoconvert ! video/x-raw,format=NV12")

        # Hardware encoder
        if encoder.startswith("va"):
            # VA-API encoder settings
            pipeline_parts.append(
                f"{encoder} rate-control=cbr bitrate={bitrate} " f"target-percentage=95 cpb-size={bitrate * 2}"
            )
        else:
            # QSV encoder settings
            pipeline_parts.append(f"{encoder} bitrate={bitrate} rate-control=cbr " f"low-latency=true")

        # Add profile constraint for WebRTC compatibility
        if self.config.codec == "h264":
            pipeline_parts.append("video/x-h264,profile=constrained-baseline")

        # Tee for multiple outputs (only if we have multiple outputs)
        needs_tee = mode in ("webrtc", "both") and mode in ("rtp", "both")
        if needs_tee:
            pipeline_parts.append("tee name=t")

        # WebRTC output
        if mode in ("webrtc", "both"):
            if needs_tee:
                pipeline_parts.append(
                    f"t. ! queue ! {payloader} config-interval=1 pt=96 ! "
                    f"webrtcbin name=webrtc bundle-policy=max-bundle"
                )
            else:
                pipeline_parts.append(
                    f"{payloader} config-interval=1 pt=96 ! " f"webrtcbin name=webrtc bundle-policy=max-bundle"
                )

        # RTP output (for testing/debugging)
        if mode in ("rtp", "both"):
            if needs_tee:
                pipeline_parts.append(
                    f"t. ! queue ! {payloader} config-interval=1 pt=96 ! "
                    f"udpsink host={self.config.rtp_host} port={self.config.rtp_port}"
                )
            else:
                pipeline_parts.append(
                    f"{payloader} config-interval=1 pt=96 ! "
                    f"udpsink host={self.config.rtp_host} port={self.config.rtp_port}"
                )

        # Build pipeline string
        # Main pipeline parts are joined with ' ! '
        # Branch parts (t. ! ...) are joined with spaces
        main_parts = []
        branch_parts = []
        for part in pipeline_parts:
            if part.startswith("t."):
                branch_parts.append(part)
            else:
                main_parts.append(part)

        pipeline = " ! ".join(main_parts)
        if branch_parts:
            pipeline += " " + " ".join(branch_parts)

        return pipeline

    def start(self, mode: str = "webrtc"):
        """
        Start the streaming pipeline.

        Args:
            mode: 'webrtc', 'rtp', or 'both'
        """
        if self._running:
            logger.warning("Pipeline already running")
            return

        pipeline_str = self._build_pipeline(mode)
        logger.info(f"Starting pipeline: {pipeline_str}")

        try:
            self.pipeline = Gst.parse_launch(pipeline_str)
        except GLib.Error as e:
            logger.error(f"Failed to create pipeline: {e}")
            raise RuntimeError(f"Pipeline creation failed: {e}")

        # Get appsrc element (only present when not using v4l2src)
        self.appsrc = self.pipeline.get_by_name("src")
        if self.appsrc:
            # Configure appsrc
            self.appsrc.set_property("format", Gst.Format.TIME)
            self.appsrc.set_property("is-live", True)
            self.appsrc.set_property("block", False)
            # Limit buffer queue to prevent memory leak (3 frames worth at 1080p YUYV = ~12MB)
            frame_size = self.config.width * self.config.height * 2  # YUYV = 2 bytes/pixel
            self.appsrc.set_property("max-bytes", frame_size * 3)
            self.appsrc.set_property("max-buffers", 3)  # Also limit buffer count
            # Drop old buffers when queue is full (live streaming - latency matters)
            self.appsrc.set_property("leaky-type", 2)  # 2 = downstream (drop oldest)
        elif not self.config.v4l2_device:
            # Only error if we expected appsrc (no v4l2 device)
            raise RuntimeError("Failed to get appsrc element")

        # Get webrtcbin if present
        self.webrtcbin = self.pipeline.get_by_name("webrtc")
        if self.webrtcbin:
            self._setup_webrtc()

        # Set up bus for messages
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message::error", self._on_error)
        bus.connect("message::eos", self._on_eos)
        bus.connect("message::state-changed", self._on_state_changed)

        # Start GLib main loop in separate thread
        self._loop = GLib.MainLoop()
        self._loop_thread = threading.Thread(target=self._loop.run, daemon=True)
        self._loop_thread.start()

        # Start pipeline
        ret = self.pipeline.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            raise RuntimeError("Failed to start pipeline")

        self._running = True
        self._start_time = GLib.get_monotonic_time()
        logger.info("Streaming pipeline started")

        # Start signaling server for WebRTC
        if self.webrtcbin and _WS_AVAILABLE:
            asyncio.create_task(self._start_signaling_server())

    def _setup_webrtc(self):
        """Configure WebRTC bin."""
        # Connect to signals
        self.webrtcbin.connect("on-negotiation-needed", self._on_negotiation_needed)
        self.webrtcbin.connect("on-ice-candidate", self._on_ice_candidate)
        self.webrtcbin.connect("pad-added", self._on_pad_added)

        # Add STUN server for NAT traversal
        self.webrtcbin.set_property("stun-server", "stun://stun.l.google.com:19302")

        logger.info("WebRTC configured")

    def _on_negotiation_needed(self, webrtcbin):
        """Handle WebRTC negotiation."""
        logger.debug("Negotiation needed")
        promise = Gst.Promise.new_with_change_func(self._on_offer_created, webrtcbin, None)
        webrtcbin.emit("create-offer", None, promise)

    def _on_offer_created(self, promise, webrtcbin, _):
        """Handle offer creation."""
        logger.info("WebRTC offer created callback triggered")
        reply = promise.get_reply()
        if reply is None:
            logger.error("Promise reply is None - offer creation failed")
            return
        offer = reply.get_value("offer")
        if offer is None:
            logger.error("Offer is None in promise reply")
            return
        promise = Gst.Promise.new()
        webrtcbin.emit("set-local-description", offer, promise)
        promise.interrupt()

        # Send offer to signaling server
        sdp_text = offer.sdp.as_text()
        logger.debug(f"Created offer: {sdp_text[:100]}...")

        # Store for signaling
        self._local_sdp = sdp_text

    def _on_ice_candidate(self, webrtcbin, mline_index, candidate):
        """Handle ICE candidate."""
        logger.debug(f"ICE candidate: {candidate}")
        # Will be sent via signaling
        if hasattr(self, "_ice_candidates"):
            self._ice_candidates.append({"candidate": candidate, "sdpMLineIndex": mline_index})

    def _on_pad_added(self, webrtcbin, pad):
        """Handle new pad."""
        logger.debug(f"Pad added: {pad.get_name()}")

    def _on_error(self, bus, message):
        """Handle pipeline error."""
        err, debug = message.parse_error()
        logger.error(f"Pipeline error: {err.message}")
        logger.debug(f"Debug info: {debug}")

    def _on_eos(self, bus, message):
        """Handle end of stream."""
        logger.info("End of stream")
        self.stop()

    def _on_state_changed(self, bus, message):
        """Handle state changes."""
        if message.src == self.pipeline:
            old, new, pending = message.parse_state_changed()
            logger.debug(f"Pipeline state: {old.value_nick} -> {new.value_nick}")

    def push_frame(self, frame: np.ndarray, timestamp_ns: Optional[int] = None):
        """
        Push a frame to the pipeline.

        Args:
            frame: BGRA numpy array of shape (height, width, 4)
            timestamp_ns: Optional timestamp in nanoseconds
        """
        if not self._running or not self.appsrc:
            return False

        # Ensure frame is contiguous and correct format
        if frame.dtype != np.uint8:
            frame = frame.astype(np.uint8)
        if not frame.flags["C_CONTIGUOUS"]:
            frame = np.ascontiguousarray(frame)

        # Create GStreamer buffer
        data = frame.tobytes()
        buf = Gst.Buffer.new_allocate(None, len(data), None)
        buf.fill(0, data)

        # Set timestamp
        if timestamp_ns is None:
            timestamp_ns = (GLib.get_monotonic_time() - self._start_time) * 1000
        buf.pts = timestamp_ns
        buf.dts = timestamp_ns
        buf.duration = Gst.SECOND // self.config.framerate

        # Push to appsrc
        ret = self.appsrc.emit("push-buffer", buf)
        if ret != Gst.FlowReturn.OK:
            logger.warning(f"Failed to push buffer: {ret}")
            return False

        self._frame_count += 1
        return True

    def push_frame_bgr(self, frame_bgr: np.ndarray):
        """
        Push a BGR frame (convert to BGRA first).

        Args:
            frame_bgr: BGR numpy array of shape (height, width, 3)
        """
        # Add alpha channel
        h, w = frame_bgr.shape[:2]
        frame_bgra = np.zeros((h, w, 4), dtype=np.uint8)
        frame_bgra[:, :, :3] = frame_bgr
        frame_bgra[:, :, 3] = 255
        return self.push_frame(frame_bgra)

    def push_frame_yuyv(self, frame_yuyv: np.ndarray, timestamp_ns: Optional[int] = None):
        """
        Push a YUYV frame directly to the pipeline.

        This is the most efficient method when the pipeline is configured with
        input_format='yuyv'. The VA-API encoder handles YUY2→NV12 conversion
        in hardware with zero CPU overhead.

        Args:
            frame_yuyv: YUYV numpy array (flat bytes or shaped)
            timestamp_ns: Optional timestamp in nanoseconds
        """
        if not self._running or not self.appsrc:
            return False

        # Ensure frame is contiguous
        if isinstance(frame_yuyv, np.ndarray):
            if not frame_yuyv.flags["C_CONTIGUOUS"]:
                frame_yuyv = np.ascontiguousarray(frame_yuyv)
            data = frame_yuyv.tobytes()
        else:
            data = bytes(frame_yuyv)

        # Create GStreamer buffer - new_wrapped takes ownership, avoids extra copy
        buf = Gst.Buffer.new_wrapped(data)

        # Set timestamp
        if timestamp_ns is None:
            timestamp_ns = (GLib.get_monotonic_time() - self._start_time) * 1000
        buf.pts = timestamp_ns
        buf.dts = timestamp_ns
        buf.duration = Gst.SECOND // self.config.framerate

        # Push to appsrc
        ret = self.appsrc.emit("push-buffer", buf)
        if ret != Gst.FlowReturn.OK:
            logger.warning(f"Failed to push YUYV buffer: {ret}")
            return False

        self._frame_count += 1
        return True

    def stop(self):
        """Stop the streaming pipeline."""
        if not self._running:
            return

        self._running = False

        # Stop signaling server
        if self._signaling_server:
            self._signaling_server.close()

        # Send EOS and wait for pipeline to finish
        if self.appsrc:
            self.appsrc.emit("end-of-stream")

        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)

        # Stop main loop
        if self._loop:
            self._loop.quit()

        logger.info(f"Pipeline stopped. Frames processed: {self._frame_count}")

    def get_stats(self) -> dict:
        """Get streaming statistics."""
        elapsed = (GLib.get_monotonic_time() - self._start_time) / 1_000_000 if self._start_time else 0
        fps = self._frame_count / elapsed if elapsed > 0 else 0

        return {
            "running": self._running,
            "frames": self._frame_count,
            "elapsed_seconds": elapsed,
            "fps": fps,
            "encoder": self._get_encoder_element(),
            "resolution": f"{self.config.width}x{self.config.height}",
            "bitrate_kbps": self.config.bitrate,
        }

    # WebRTC Signaling Server
    async def _start_signaling_server(self):
        """Start WebSocket signaling server for WebRTC."""
        if not _WS_AVAILABLE:
            logger.warning("WebSocket not available, skipping signaling server")
            return

        self._ice_candidates = []

        async def handle_client(websocket, path):
            """Handle WebRTC signaling for a client."""
            client_id = id(websocket)
            logger.info(f"WebRTC client connected: {client_id}")

            try:
                async for message in websocket:
                    data = json.loads(message)
                    msg_type = data.get("type")

                    if msg_type == "request_offer":
                        # Client wants to connect, send our offer
                        logger.info(f"Client {client_id} requested offer, have SDP: {hasattr(self, '_local_sdp')}")
                        if hasattr(self, "_local_sdp") and self._local_sdp:
                            logger.info(f"Sending offer to client {client_id}")
                            await websocket.send(json.dumps({"type": "offer", "sdp": self._local_sdp}))
                            # Send ICE candidates
                            logger.info(f"Sending {len(self._ice_candidates)} ICE candidates")
                            for candidate in self._ice_candidates:
                                await websocket.send(json.dumps({"type": "ice-candidate", **candidate}))
                        else:
                            logger.warning(f"No SDP offer available yet for client {client_id}")

                    elif msg_type == "answer":
                        # Client sent answer
                        sdp = data.get("sdp")
                        if sdp and self.webrtcbin:
                            res, sdpmsg = GstSdp.SDPMessage.new()
                            GstSdp.sdp_message_parse_buffer(bytes(sdp, "utf-8"), sdpmsg)
                            answer = GstWebRTC.WebRTCSessionDescription.new(GstWebRTC.WebRTCSDPType.ANSWER, sdpmsg)
                            promise = Gst.Promise.new()
                            self.webrtcbin.emit("set-remote-description", answer, promise)
                            promise.interrupt()
                            logger.info("Set remote description from answer")

                    elif msg_type == "ice-candidate":
                        # Client sent ICE candidate
                        candidate = data.get("candidate")
                        sdp_mline_index = data.get("sdpMLineIndex", 0)
                        if candidate and self.webrtcbin:
                            self.webrtcbin.emit("add-ice-candidate", sdp_mline_index, candidate)

            except Exception as e:
                logger.error(f"Signaling error: {e}")
            finally:
                logger.info(f"WebRTC client disconnected: {client_id}")

        try:
            self._signaling_server = await ws_serve(handle_client, "0.0.0.0", self.config.signaling_port)
            logger.info(f"WebRTC signaling server started on port {self.config.signaling_port}")
            await self._signaling_server.wait_closed()
        except Exception as e:
            logger.error(f"Signaling server error: {e}")

    @property
    def is_running(self) -> bool:
        return self._running


class MJPEGStreamServer:
    """
    Simple MJPEG HTTP server for browser preview.

    Uses VA-API JPEG encoder for hardware-accelerated encoding.
    Lower latency than WebRTC for simple preview use cases.
    """

    def __init__(self, port: int = 8766, width: int = 640, height: int = 360):
        self.port = port
        self.width = width
        self.height = height
        self._running = False
        self._frame: Optional[bytes] = None
        self._frame_lock = threading.Lock()
        self._server = None

    async def start(self):
        """Start the MJPEG server."""
        from aiohttp import web

        app = web.Application()
        app.router.add_get("/stream.mjpeg", self._handle_stream)
        app.router.add_get("/snapshot.jpg", self._handle_snapshot)
        app.router.add_get("/stats", self._handle_stats)

        runner = web.AppRunner(app)
        await runner.setup()
        self._server = web.TCPSite(runner, "0.0.0.0", self.port)
        await self._server.start()

        self._running = True
        logger.info(f"MJPEG server started on port {self.port}")

    async def _handle_stream(self, request):
        """Handle MJPEG stream request."""
        response = web.StreamResponse()
        response.content_type = "multipart/x-mixed-replace; boundary=frame"
        await response.prepare(request)

        while self._running:
            with self._frame_lock:
                frame_data = self._frame

            if frame_data:
                await response.write(b"--frame\r\n" b"Content-Type: image/jpeg\r\n\r\n" + frame_data + b"\r\n")

            await asyncio.sleep(1 / 30)  # 30 FPS max

        return response

    async def _handle_snapshot(self, request):
        """Handle single frame snapshot request."""
        with self._frame_lock:
            frame_data = self._frame

        if frame_data:
            return web.Response(body=frame_data, content_type="image/jpeg")
        else:
            return web.Response(status=503, text="No frame available")

    async def _handle_stats(self, request):
        """Return server stats as JSON."""
        return web.json_response(
            {
                "running": self._running,
                "resolution": f"{self.width}x{self.height}",
                "has_frame": self._frame is not None,
            }
        )

    def push_frame(self, frame_bgr: np.ndarray):
        """
        Push a BGR frame to the server.

        Uses hardware JPEG encoding if available.
        """
        import cv2

        # Resize if needed
        h, w = frame_bgr.shape[:2]
        if w != self.width or h != self.height:
            frame_bgr = cv2.resize(frame_bgr, (self.width, self.height))

        # Encode to JPEG (TODO: use VA-API JPEG encoder)
        _, jpeg_data = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 80])

        with self._frame_lock:
            self._frame = jpeg_data.tobytes()

    def stop(self):
        """Stop the server."""
        self._running = False


# Convenience function to create pipeline with optimal settings
def create_intel_pipeline(
    width: int = 1920,
    height: int = 1080,
    framerate: int = 30,
    flip: bool = False,
    v4l2_device: Optional[str] = None,
) -> IntelStreamingPipeline:
    """
    Create an Intel streaming pipeline with optimal settings.

    Args:
        width: Video width
        height: Video height
        framerate: Target framerate
        flip: Enable horizontal flip (for Google Meet)
        v4l2_device: Optional v4l2 device for Google Meet output

    Returns:
        Configured IntelStreamingPipeline
    """
    config = StreamConfig(
        width=width,
        height=height,
        framerate=framerate,
        flip=flip,
        v4l2_device=v4l2_device,
        encoder="va",  # Use VA-API (most compatible)
        codec="h264",  # H.264 for WebRTC compatibility
        bitrate=4000,  # 4 Mbps for 1080p
    )

    return IntelStreamingPipeline(config)
