# NeonPhantom XR in Quest Browser — local network

Your PC prepares the cutout; Quest Browser plays a stereoscopic video screen in VR or a transparent cutout
in passthrough. No APK, cloud account, public hosting or internet connection is
needed for playback. Keep the PC and headset on the same local network.

## Start on the PC

Import videos in the normal NeonPhantom XR studio at `http://127.0.0.1:8321` first.
Use an alpha-preserving or background-removal mode for cutouts. Videos that keep
their background remain rectangular in VR.

- **Linux:** run `./start-quest.sh` from the bundle folder.
- **Windows:** run `setup-windows.cmd` once, then double-click `start-quest.cmd`.
  Existing installations should rerun setup to install the HTTPS dependency.

The launcher needs Python 3.10+ and FFmpeg/ffprobe with libx264 and libvpx-vp9 on
PATH. Linux uses `.venv-quest/bin/python` when available, then the existing `.venv-gpu/bin/python`, otherwise `python3`. Run `./setup-quest.sh` for a dedicated CPU environment with the Quest/depth dependencies.
For certificate generation, use OpenSSL or install `requirements-quest.txt` into
the Python environment selected by the launcher. Windows setup installs it.

Keep the launcher terminal open. It prints an address such as
`https://<PC-LAN-IP>:8443/` and a six-digit pairing code. The companion serves
prepared clips and creates requested stereo derivatives on the LAN; the normal upload/edit studio stays on loopback.

## Open on the headset

1. In **Quest Browser**, enter the exact HTTPS address printed by the PC.
   `localhost` on the headset refers to the headset, so use the PC's LAN address.
2. The default certificate is generated locally. If Quest Browser offers a
   certificate exception, accept it for this PC's address. Then enter the code.
3. Wait for a clip to finish preparing, select it, and choose **Enter passthrough**.
   Allow the browser's immersive session request if prompted.

Both **Enter VR** (a dark cinema) and **Enter passthrough** (your room) use WebXR. WebXR requires a secure context. If the browser does not treat the certificate
exception as secure, use a certificate trusted by that headset/browser and pass
`--cert /path/server.crt --key /path/server.key`. There is no HTTP fallback for
immersive AR. The viewer checks `isSecureContext` and immersive-AR support and
explains when entry is unavailable. See Meta's [local HTTPS example](https://github.com/facebook/immersive-web-sdk/blob/main/examples/depth-occlusion/README.md)
and the [WebXR requirements](https://immersive-web.github.io/webxr/).

If the page cannot be reached, check that both devices use the same network,
wireless client isolation is off, and the PC firewall allows incoming TCP 8443
on that private network. A VPN or multiple network adapters may cause the printed
IP to pick the wrong adapter; use the PC's Wi-Fi/Ethernet LAN address instead.
No router port forwarding is needed.

The pairing code changes every time the companion starts. Each browser pairs
separately. HTTPS cookies restrict library listings and video downloads to paired
browsers. Ctrl+C in the launcher terminal stops sharing.

## Playback and placement

- **Trigger / select on the video:** show the playback controls.
- **In-scene toolbar:** Play/Pause, ±10 seconds, Mute, size, Recenter, Move and Exit VR.
  Controls hide after five seconds of inactivity; click the video to restore them.
  Click outside to hide immediately. Use Move video, then aim and click to place a flat cutout.
- **Left thumbstick up/down:** change video height.
- **Right thumbstick up/down:** change distance and place in front of you.
- **A/X:** pause or resume. **B/Y:** recenter the video and restore its playback controls.
- The playback toolbar works inside the 3D scene without DOM overlay. Set up
  source format, distance, vertical
  position, rotation, opacity and edge cleanup before entry using the browser panel.
  Use the scene toolbar's **Exit VR** in VR or passthrough;
  the headset's browser/system controls can also end the immersive session.

Playback is muted and loops by default. Turn off **Mute audio** for clips with an audio track. The clip stays at its placed location
for the current session; placement is not saved between sessions. This is a flat
video in a 3D scene, with no volumetric reconstruction, persistent anchors or
real-world object occlusion.

**Open a video on this device** supports local files already on the headset.
Regular MP4 files display as rectangles. The packed RGB+alpha checkbox is only
for NeonPhantom XR Quest exports; it does not remove the background from ordinary MP4.

## Convert 2D video to 3D SBS

1. Add a 2D video in the PC studio, then select it in the Quest viewer.
2. Under **Convert 2D to 3D SBS**, set **Depth strength**. Start at 1.5%;
   lower values give gentler stereo and reduce edge distortion.
3. Choose **Convert selected video to 3D SBS**. The PC estimates depth and
   synthesizes separate left/right views. Choose Auto, GPU preferred or CPU only.
   Conversion runs locally,
   one job at a time, with progress and cancellation controls.
4. Choose **Play converted 3D video**, then **Enter VR** or **Enter passthrough**.
   Source format switches to Full SBS automatically. **Download SBS MP4** saves
   the ordinary full-SBS H.264 file for other VR players; select Full SBS there.

The first conversion downloads a pinned, SHA-256-verified ONNX export (27 MB
for CPU, 99 MB for GPU) of
[Depth Anything V2 Small](https://huggingface.co/onnx-community/depth-anything-v2-small).
Subsequent conversions work offline. No video is uploaded. The small model supports CPU fallback when NVIDIA CUDA is unavailable. Run
`./setup-quest.sh` on Linux if dependencies are absent; Windows setup already
installs the required CPU packages.

These are **estimated stereoscopic views**, with depth-aware pixel warping and
nearer-surface selection at overlaps. The eyes are not duplicate images. Temporal
smoothing reduces flicker, but depth errors, motion shimmer, stretched edges and
inpainting artifacts remain possible. This is a stereo video screen, rather than
volumetric reconstruction or a 180°/360° capture. Moving sideways does not reveal
new camera angles. Use lower depth strength or the original mono clip when a
scene looks uncomfortable or distorted.

The converter preserves duration and any audio present in its source. Studio
cutout exports are typically silent. It writes two derivatives under `.quest/stereo/`:
`sbs.mp4` (standard SBS, transparent areas composited onto black) and `quest.mp4`
(color stereo plus corresponding alpha stereo for this viewer). Originals stay
unchanged. Completed conversions persist between starts and appear beside their
source while that source remains in the studio library. Files opened only on the
headset can be played, but conversion requires a video in the PC library.

## GPU processing and VR preparation on import

In the PC studio, optionally enable **Prepare a 3D SBS VR version after import**
and choose Auto, GPU preferred or CPU only. Keep the Quest companion running.
It waits for studio imports/model installations to finish before automatically
queuing the requested stereo derivatives, one at a time. Each import request is
recorded to avoid preparing the same derivative again on every refresh/restart.
Failures and completed results appear in the Quest viewer; failed conversions can
be started manually again from the original library card.

GPU accelerates depth inference. Warping and H.264 encoding remain CPU-based.
GPU workers run in a separate process using their own CUDA/cuDNN library paths;
they never install into or modify an existing cutout environment. CUDA memory
allocation is limited to a 2 GiB arena, and unavailable/failed GPU inference
falls back to CPU. The completed result and progress show which device was used.
The GPU arena limit does not guarantee total process VRAM use stays below 2 GiB.

An existing app-local `.venv-cuda` runtime can also be used. For a separate optional
NVIDIA runtime on another computer, use `setup-quest-gpu.sh` (Linux) or
`setup-quest-gpu.cmd` (Windows; Python 3.12 launcher required). An appropriate
NVIDIA driver is required by the [CUDA provider](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html).
The companion prefers `.venv-quest-gpu`, then `.venv-cuda`, then its current Python
with CPU fallback. `DESKDANCE_STEREO_GPU_PYTHON` can select an existing compatible
Python executable. These are processing settings for the PC; the headset still
decodes the prepared video.

## Headset-ready VR180 SBS: people in passthrough

In the PC studio, choose **Video source → Headset-ready VR180 SBS**, then
**Background → AI cutout** and a person matting model. Import the video normally.
Each eye is split and processed separately with independent temporal model state,
then combined with its alpha mask. The captured stereo views and their timing
are retained; 2D-to-3D depth generation is disabled for this source format.

In the headset viewer, select the result and choose **Enter passthrough**.
Its projection and stereo layout are selected automatically. The transparent
background reveals the room; visible people retain the recorded stereo depth.
The 180° hemisphere leaves the rear view transparent. **B/Y** recenters the
capture direction and restores playback controls. Flat-screen size/move buttons
are inactive for hemispherical video.

This mode accepts **180° equirectangular SBS** exports, including normally
headset-ready footage. Raw dual-fisheye, lens-specific distortion and camera
calibration conversion are outside this input mode. If a headset-ready export is
still fisheye encoded, export it as equirectangular VR180 first. Existing local
VR180 files can also be viewed by selecting the matching projection and SBS layout.
Background removal requires importing through the PC studio.

The output remains captured stereo with three degrees of viewing rotation, not
volumetric people or real-world depth/occlusion. Head translation does not reveal
new viewpoints. Independent eye mattes may differ at edges and moving hair;
physical Quest viewing and matte quality with the user's footage require testing.
VR180 currently follows the studio's 480/720-pixel processing profiles per eye
and silent-video behavior.

## Play existing SBS videos

For a local video already containing stereo views, select **Full SBS** or
**Half SBS** as appropriate. Full SBS halves the encoded width for each eye;
half SBS restores the horizontally compressed halves. Use **Swap left and right
eyes** if near/far depth is reversed. The desktop preview can show either eye.
The packed RGB+alpha checkbox describes transparency encoding and is separate
from SBS stereo. Leave it off for ordinary SBS files. Converted Quest library
entries set both controls automatically.

## How clips reach the headset

The companion reads the same `deskdanced/state.json` and `samples` directory as
the studio and checks for changes every 15 seconds. It never edits originals.
Each library clip is converted once into a cached H.264 MP4 with color in the
left half and grayscale alpha in the right half. A shader combines the halves
using one synchronized decoder, avoiding reliance on headset WebM alpha support.
Exports preserve duration and fit within 1920×1080 per half (3840×1080 packed).
The first preparation can take time; subsequent starts reuse cached exports.
The cache and local certificate live under `.quest/` and are excluded from release
packages. Remove that directory only while the companion is stopped to regenerate
the cache and certificate.

Optional configuration:

```bash
./start-quest.sh --port 8443 --state /path/state.json --media /path/samples
./start-quest.sh --cert /path/server.crt --key /path/server.key
```

The companion honors `DESKDANCE_STATE` and `DESKDANCE_MEDIA_DIR`. Set
`DESKDANCE_QUEST_PYTHON` to choose a different Linux Python executable. Restrict
to PC-only preview with `--host 127.0.0.1`.

The full Linux and Windows ZIPs include the prebuilt viewer. Node.js is only
needed to modify/rebuild it:

```bash
cd quest/app
npm ci
npm run build
```

## Validation and limits

Automated checks cover alpha-mask encoding, soft edges, opaque video, duration,
cache refresh/removal, path boundaries, HTTPS pairing, authenticated range requests,
browser playback and emulated Quest AR session entry/exit/re-entry. Physical
Quest rendering, certificate acceptance and controller ergonomics still require
testing on a real headset. See `VALIDATION.md` for the recorded checks.
