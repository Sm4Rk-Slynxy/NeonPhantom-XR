# NeonPhantom XR for Windows x64

Windows 10/11 x64 package. Extract the entire ZIP into a writable folder such as
`C:\Apps\NeonPhantom-XR`. Run it from your signed-in desktop session.
The package includes the Windows server executable and built interface;
Node.js, Rust, Git, WSL, and mpv are not needed to run it.

## First setup

1. Install Python **3.12 x64** from [python.org](https://www.python.org/downloads/windows/).
   Include the Python launcher. Python 3.11–3.13 also work with the setup script.
2. Install a Windows FFmpeg build with **ffmpeg.exe and ffprobe.exe**, including
   libvpx-vp9. See [FFmpeg's download page](https://ffmpeg.org/download.html#build-windows).
   Add its `bin` folder to your user PATH. Open a fresh terminal and verify
   `ffmpeg -version` and `ffprobe -version`.
3. Double-click **setup-windows.cmd**. It creates an app-local `.venv-ai` and
   downloads the base CPU cutout packages plus PySide6 for the native overlay.
4. Double-click **start-windows.cmd**, then open **http://127.0.0.1:8321/**.

Setup requires internet access and several GB of free disk space. First use of
Classic cutout downloads its weights. Optional engines require additional disk
space and download separately from the studio. Keep the launch window open.
Press Ctrl+C there to stop the server and its player.

## Model choices

- **Classic cutout** remains the default and works on CPU. Detailed targets people;
  Fast uses a small general foreground model.
- **MatAnyone 2** is intended for human videos. Click **Download & install** before
  selecting it for imports. It starts from an automatic person mask, optionally
  restricted by first-frame region percentages, and propagates video memory.
- **WeVisOne 2B / 4B** accept descriptions such as `the penguin`. Each frame is
  processed independently. Subject selection and edges may flicker; GPU recommended.
  When the target is absent the frame becomes transparent. 4B needs more memory.

Try **Preview only · first 3 seconds** first. It creates a clearly labeled library
clip; turn it off and upload again for the full video. Full imports have no
automatic time limit and preserve the source duration. Playback is muted.
Model, subject, and quality preferences are remembered in this browser.

Optional installers isolate MatAnyone and WeVisOne in separate environments.
PyTorch selects CUDA when available; an NVIDIA GPU and compatible driver are
required for CUDA. Check actual availability in the model environment with:

```powershell
.venv-matanyone2\Scripts\python.exe -c "import torch; print(torch.cuda.is_available())"
.venv-wevisone\Scripts\python.exe -c "import torch; print(torch.cuda.is_available())"
```

If this reports False, use the official [PyTorch installer](https://pytorch.org/get-started/locally/)
for that environment. CPU operation is supported but large models can be very slow.
Never install model dependencies into your system Python to repair this app.

## Desktop playback

The Windows edition uses a native, borderless, always-on-top translucent Qt window.
FFmpeg decodes the actual VP9 alpha channel into RGBA frames. Position and height
use the primary monitor's available desktop area, leaving room for the taskbar.
Stop, shuffle, size, and corner controls work through the studio.

Keep both the studio port (8321 by default) and the following port (8322) free.
Player control binds only to loopback and requires a per-session random token.
If changing `DESKDANCE_PORT`, choose a value below 65535.

Back up `deskdanced\state.json` and `samples\` together while the app is stopped.
The distribution starts with an empty library; it contains no personal clips.
Keep the folder in the same location after setup, or recreate the virtual environments.

## Validation status

The Windows backend is cross-compiled from the shared Rust source. The RGBA player
and control protocol are exercised with Qt's offscreen platform on Linux.
Native Windows installation and desktop composition still need a Windows smoke test;
this package is a preview release, not a Windows-tested installer.

## Source and licenses

The ZIP includes the app source and dependency lockfile. To rebuild on Windows:

```powershell
cargo build --release --locked --manifest-path deskdanced\Cargo.toml
```

Optional models download from their official upstream projects; see
[MODEL-UPGRADE.md](MODEL-UPGRADE.md) for pinned source revisions, license links,
and implementation details. FFmpeg and PySide6 retain their respective licenses.

## Quest Browser on the local network

After setup, double-click `start-quest.cmd` and keep its terminal open. It prints the HTTPS address and six-digit pairing code to use in Quest Browser. Allow Python through Windows Firewall on your private network if prompted. See [QUEST-README.md](QUEST-README.md) for certificate setup, playback and controls.
