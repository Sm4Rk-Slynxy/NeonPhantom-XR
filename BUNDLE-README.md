# NeonPhantom XR — Linux setup

Extract the complete Linux x64 release into a writable folder. The supplied binary requires glibc 2.39 or newer (for example Ubuntu 24.04+); build from source on older distributions. Keep its contents together. Install Python **3.11–3.13** (3.12 recommended), **FFmpeg and ffprobe with libvpx-vp9/libx264**, and **mpv** for desktop playback. Use your distribution's package manager for native tools.

## CPU setup

```sh
python3.12 -m venv .venv-gpu
.venv-gpu/bin/python -m pip install -r requirements-ai.txt
./start.sh
```

The historical `.venv-gpu` directory name also supports a CPU-only runtime. Open **http://127.0.0.1:8321/** from your desktop session. First use of Classic downloads its model. Optional models install from the studio.

The release includes a backend binary and built web interfaces. A source checkout needs Rust and Node.js to build them; see [README.md](README.md). A launcher with Cargo installed rebuilds the backend automatically.

## Import

Choose the source projection and background mode, then add or drop local video files. Auto preserves an existing alpha channel or runs AI cutout. AI removes the selected subject's background; green/blue use chromakey; Preserve transparency rejects opaque input; Keep background retains the full image.

For fragmented M4S, select the matching initialization file and every consecutive video segment from a single track. Separate audio tracks and encrypted inputs are not supported. HLS/DASH/concat playlists and network URLs are rejected; export a self-contained video first.

Detailed output is capped at 720 px high / 30 fps, Fast AI at 480 px / 12 fps. VR180 processes each eye separately. Full imports preserve duration and produce muted VP9 WebM. The explicit three-second preview creates a separate shortened clip. Conversion can need substantial temporary disk space.

Uploads are removed after success. Failed uploaded inputs are retained for retry; Remove in Import activity deletes that retained copy. Local-path imports never delete the source file.

## Desktop output

Use Play on desktop, then adjust size and corner. A compatible compositor is required for alpha. Linux supports Hyprland and composited X11; GNOME/KDE Wayland use XWayland when available. Other Wayland compositors may need window rules. Hyprland rules target `mpv-dancer`. Positioning depends on the window manager.

Player socket and log are kept in a private `neonphantom-xr` directory under `$XDG_RUNTIME_DIR`, or `.runtime/` in the app folder. Stop playback closes the owned player. Start from a terminal carrying the desktop's DISPLAY/WAYLAND_DISPLAY and compositor environment.

## GPU

Use a separate Python 3.11–3.13 environment with `requirements-gpu.txt` and compatible NVIDIA drivers. The server selects `.venv-cuda` through `gpu-python.sh` only when `.venv-cuda/.ready` exists; create the marker after validating actual inference. `DESKDANCE_PYTHON` can select an explicit runtime. Each optional model environment isolates its own CUDA/cuDNN libraries. See [model setup](MODEL-UPGRADE.md) and the [ONNX Runtime CUDA documentation](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html).

For GPU stereo depth, use `setup-quest-gpu.sh`; see [QUEST-README.md](QUEST-README.md).

## Configuration and private data

| Variable | Default |
| --- | --- |
| `DESKDANCE_ROOT` | App directory, set by launcher |
| `DESKDANCE_STATE` | `deskdanced/state.json` |
| `DESKDANCE_MEDIA_DIR` | `samples/` |
| `DESKDANCE_PYTHON` | Automatically selected cutout runtime |
| `DESKDANCE_PORT` | `8321`, loopback only |
| `DESKDANCE_QUEST_PYTHON` | Automatically selected Quest runtime |

The internal names are retained for upgrade compatibility. Back up state and media together while the app is stopped. `.quest/` contains private exports, conversions, and TLS keys; `.models/` contains downloaded weights. These are local runtime data and must never be published. Release packages start with an empty library.
