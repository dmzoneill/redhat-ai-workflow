# Meet Bot GPU/NPU Optimization Guide

This document captures deep technical knowledge about GPU, NPU, OpenCL, OpenGL, v4l2loopback, and audio processing optimizations for the AI Meet Bot video generator.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Video Generation Pipeline                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌───────────┐ │
│  │   OpenGL     │    │   OpenCL     │    │  v4l2loopback │    │  Virtual  │ │
│  │  Text/Shapes │───▶│  Waveform +  │───▶│    Device     │───▶│   Camera  │ │
│  │  Rendering   │    │  YUYV Conv   │    │  /dev/video10 │    │  Output   │ │
│  └──────────────┘    └──────────────┘    └──────────────┘    └───────────┘ │
│        │                    │                                               │
│        │                    │                                               │
│        ▼                    ▼                                               │
│  ┌──────────────┐    ┌──────────────┐                                      │
│  │  GPU (iGPU)  │    │  GPU (iGPU)  │                                      │
│  │  Intel Arc   │    │  Intel Arc   │                                      │
│  └──────────────┘    └──────────────┘                                      │
│                                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                           Audio/STT Pipeline                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌───────────┐ │
│  │  PipeWire    │    │   Python     │    │  OpenVINO    │    │   Intel   │ │
│  │  pw-record   │───▶│  numpy FFT   │───▶│  Whisper     │───▶│    NPU    │ │
│  │  Audio Cap   │    │  Waveform    │    │  Pipeline    │    │  Meteor   │ │
│  └──────────────┘    └──────────────┘    └──────────────┘    └───────────┘ │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Performance Targets and Results

| Configuration | Target | Achieved | Notes |
|--------------|--------|----------|-------|
| Video only (no audio) | <5% CPU | ~13% CPU | OpenGL text + OpenCL conversion |
| Video + Audio waveform | <10% CPU | ~15% CPU | + FFT for waveform |
| Video + Audio + STT | <20% CPU | ~25% CPU | + Whisper on NPU |

## Key Components

### 1. OpenGL Text Rendering (`gpu_text.py`)

**Purpose:** Render anti-aliased TrueType fonts on GPU

**Implementation:**
- Uses GLFW for headless OpenGL context creation
- FreeType for glyph rasterization into texture atlas
- Custom shaders for text rendering to FBO (Framebuffer Object)
- Supports multiple font sizes with separate atlases

**Critical Settings:**
```python
# Force GLX platform for Linux headless rendering
os.environ.setdefault('PYOPENGL_PLATFORM', 'glx')

# Initialize GLFW with X11 platform
glfw.init_hint(glfw.PLATFORM, glfw.PLATFORM_X11)
```

**Font Sizes (1080p):**
- Large: 26px (titles)
- Normal: 18px (body text)
- Small: 14px (labels)
- Tiny: 12px (fine print)

### 2. OpenCL Video Processing (`UltraLowCPURenderer`)

**Purpose:** GPU-accelerated waveform rendering and color conversion

**Kernel Features:**
- Single "mega-kernel" processes entire frame
- Waveform bars generated with `native_sin()` or from audio data
- Progress bar overlay
- BGR→YUYV color conversion (BT.601)

**Key Optimization:** Hardcoded constants via template substitution:
```c
#define WIDTH {width}
#define HEIGHT {height}
#define WAVE_X {wave_x}
// ... etc
```

This allows the OpenCL compiler to optimize memory access patterns.

**Buffer Management:**
```python
# Pre-allocate all buffers at init
self.base_gpu = cl.Buffer(ctx, mf.READ_ONLY, width * height * 3)  # BGR
self.yuyv_gpu = cl.Buffer(ctx, mf.WRITE_ONLY, width * height * 2)  # YUYV
self.audio_gpu = cl.Buffer(ctx, mf.READ_ONLY, num_bars * 4)  # float32
```

### 3. v4l2loopback Virtual Camera

**Purpose:** Create virtual camera device for video output

**Setup:**
```bash
# Load module with specific device number and resolution
sudo modprobe v4l2loopback video_nr=10 max_width=1920 max_height=1080 \
    card_label="AI_Meet_Bot" exclusive_caps=1
```

**Python Configuration:**
```python
# Set pixel format via ioctl
VIDIOC_S_FMT = 0xc0d05605
fmt = struct.pack('I4sIIIIII44x',
    1,  # V4L2_BUF_TYPE_VIDEO_OUTPUT
    b'YUYV',  # pixel format
    width, height,
    width * 2,  # bytesperline
    width * height * 2,  # sizeimage
    1, 1)  # colorspace
fcntl.ioctl(fd, VIDIOC_S_FMT, fmt)
```

**Output:** Direct write with zero-copy memoryview:
```python
os.write(v4l2_fd, memoryview(yuyv_frame))
```

### 4. Audio Capture and FFT

**Source:** PipeWire via `pw-record` subprocess

**Capture Command:**
```bash
pw-record --target=<source> --rate=16000 --channels=1 --format=f32 -
```

**FFT Processing (Optimized):**
```python
# Run FFT at video frame rate (12fps), not audio chunk rate (~15fps)
fft_interval = 1.0 / 12.0  # Match video frame rate

if now - last_fft_time >= fft_interval:
    fft_bars = self._compute_fft_bars(audio_buffer)
    self._audio_buffer = fft_bars
    last_fft_time = now
```

**Logarithmic Frequency Mapping:**
```python
# More resolution at low frequencies (more musical)
for i in range(num_bars):
    low_freq = int(n_fft_bins * (np.exp(i / num_bars * np.log(n_fft_bins)) - 1) / (n_fft_bins - 1))
    high_freq = int(n_fft_bins * (np.exp((i + 1) / num_bars * np.log(n_fft_bins)) - 1) / (n_fft_bins - 1))
```

### 5. NPU Speech-to-Text (Whisper)

**Model:** OpenVINO Whisper (base or tiny)
**Device:** Intel NPU (Meteor Lake)
**Location:** `~/.cache/openvino/whisper-base-ov/`

**Initialization:**
```python
import openvino_genai as ov_genai
pipeline = ov_genai.WhisperPipeline(str(model_dir), "NPU")
```

**Transcription Triggers:**
- After 1s of audio + silence detected
- After 5s of audio (max buffer)
- Check interval: 200ms

**CPU Overhead Sources:**
- NumPy array creation for audio data
- OpenVINO internal data marshalling
- Asyncio event loop management

## Why Zero-Copy NPU is Not Possible (Current APIs)

### The Problem

```
Audio Source → Python → NumPy Array → OpenVINO → NPU
                  ↑
            CPU copies here
```

### API Limitations

1. **OpenVINO GenAI WhisperPipeline** only accepts `std::vector<float>` (C++) or Python sequences
2. **RemoteTensor API** exists but is NOT exposed in WhisperPipeline
3. **PipeWire** doesn't provide DMA-BUF for audio (only for video)

### What Would Be Needed

```cpp
// Theoretical zero-copy path (not currently possible)
auto npu_context = core.get_default_context("NPU");
auto remote_tensor = npu_context.create_tensor(ov::element::f32, shape,
    {{"SHARED_BUF", dma_buf_fd}});  // DMA-BUF from audio
whisper_pipeline.generate(remote_tensor);  // NOT SUPPORTED
```

### Effort to Implement

| Approach | Effort | CPU Savings |
|----------|--------|-------------|
| Current Python API | Done | Baseline |
| C++ with manual Whisper | 2-4 weeks | ~5-10% |
| Level Zero direct | 4-8 weeks | ~10-15% |

## GL-CL Interop Investigation

### What We Tried

OpenGL-OpenCL interop to share textures without CPU readback:

```python
# Create shared context
props = [
    (cl.context_properties.GL_CONTEXT_KHR, glx_context_ptr),
    (cl.context_properties.GLX_DISPLAY_KHR, x11_display_ptr),
    (cl.context_properties.PLATFORM, platform),
]
ctx = cl.Context(devices, properties=props)

# Share OpenGL texture with OpenCL
gl_image = cl.GLTexture(ctx, mf.READ_ONLY, GL.GL_TEXTURE_2D, 0, texture_id, 2)
```

### Why It Didn't Help

1. **We're not sharing existing content** - We create the texture specifically for video output
2. **GL-CL sync overhead** - `acquire_gl_objects`/`release_gl_objects` adds latency
3. **Indirect texture access** - Reading GL texture in OpenCL is slower than direct buffer

### Results

| Renderer | Without Audio | With Audio+STT |
|----------|--------------|----------------|
| UltraLowCPU (current) | ~13% CPU | ~25% CPU |
| ZeroCopy GL-CL | ~16% CPU | ~27% CPU |

**Conclusion:** GL-CL interop is slower for our use case. Kept UltraLowCPU renderer.

## Building PyOpenCL with GL Support

If you need GL-CL interop for other purposes:

```bash
# Install headers
sudo dnf install -y opencl-headers

# Ensure libOpenCL.so symlink
sudo ln -sf libOpenCL.so.1 /usr/lib64/libOpenCL.so

# Build pyopencl with GL support
git clone https://github.com/inducer/pyopencl.git
cd pyopencl
export PYOPENCL_ENABLE_GL=1
export CL_INC_DIR=/usr/include
export CL_LIB_DIR=/usr/lib64
export CL_LIBNAME=OpenCL
pip install . -v
```

Verify:
```python
import pyopencl as cl
print(cl.have_gl())  # Should print True
```

## Resolution Presets

All UI coordinates are defined as absolute pixels (no runtime scaling):

```python
@dataclass
class VideoConfig:
    # 1080p preset
    width: int = 1920
    height: int = 1080
    title_y: int = 27
    name_y: int = 72
    tools_start_y: int = 117
    wave_x: int = 40
    wave_y: int = 592
    wave_w: int = 1000
    wave_h: int = 80
    # ... etc
```

## Troubleshooting

### v4l2loopback Shows Wrong Resolution

```bash
# Check current format
v4l2-ctl -d /dev/video10 --get-fmt-video

# Force reload module
sudo modprobe -r v4l2loopback
sudo modprobe v4l2loopback video_nr=10 max_width=1920 max_height=1080
```

### OpenGL Context Fails

```bash
# Check DISPLAY is set
echo $DISPLAY

# For headless, ensure X11 is running or use virtual framebuffer
Xvfb :99 -screen 0 1920x1080x24 &
export DISPLAY=:99
```

### Audio Waveform Not Showing

1. Check audio source exists: `pw-record --list-targets`
2. Verify buffer is being set: Look for `buffer=True` in logs
3. Check FFT produces valid data: Look for `Audio bars: min=X, max=Y`

### High CPU Usage

1. **Without audio:** Should be ~13% - check OpenCL is using GPU not CPU
2. **With audio:** FFT should run at 12fps not higher
3. **With STT:** Whisper adds ~12% - this is expected

## File Locations

| Component | Path |
|-----------|------|
| Video Generator | `tool_modules/aa_meet_bot/src/video_generator.py` |
| GPU Text Renderer | `tool_modules/aa_meet_bot/src/gpu_text.py` |
| STT Engine | `tool_modules/aa_meet_bot/src/stt_engine.py` |
| Audio Capture | `tool_modules/aa_meet_bot/src/audio_capture.py` |
| Whisper Model | `~/.cache/openvino/whisper-base-ov/` |

## Future Optimization Opportunities

1. **Use whisper-tiny model** - Smaller, faster, ~30% less CPU
2. **Batch longer audio** - Reduce transcription frequency
3. **C++ rewrite** - Eliminate Python overhead (~5% savings)
4. **Direct Level Zero** - Maximum control but high effort
5. **Disable STT when not needed** - Saves ~12% CPU instantly
