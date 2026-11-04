# NeonPhantom XR alpha validation

Release preparation: 2026-11-04. All fresh release checks use disposable state, generated footage, and isolated local servers.

| Check | Result |
| --- | --- |
| Python conversion/security regressions | 49 discovered: 40 passed in the clean runtime; remaining 6 API, 2 real-AI and 1 Qt checks passed separately |
| API integration, isolated server | 6 passed, including Host/Origin rejection, uploads, retry, M4S, projection and automatic stereo options |
| Qt overlay on Linux offscreen | 1 passed: transparent RGBA frames, authenticated control commands and clean shutdown |
| Rust tests | 2 state migration/default tests passed |
| Build dependency security | 6 exploit/compatibility checks passed, including a clean npm install; studio assets match the previous build |
| MatAnyone compatibility | Existing official checkpoint matches its published digest; real CUDA inference passed with the new pre-load integrity guard |
| Hardened downloads | HTTPS redirects, checksum rejection and atomic-file preservation verified |
| Studio and Quest production builds | Passed with pinned npm lockfiles |
| Quest browser / emulated headset | Passed pairing, alpha pixels, actual CPU depth conversion/download, per-eye SBS framebuffer colors, VR180 hemisphere, AR/VR re-entry and controller Play/Pause/Hide/Exit, click-to-show and idle hide |
| Responsive UI | Desktop and 390 px studio/Quest layouts checked; no horizontal overflow or JavaScript errors |
| Screenshots | Desktop studio, paired Quest viewer and mobile studio captured from generated geometric footage; visually inspected |
| Linux executable | Extracted binary smoke-tested; glibc 2.39+ required |
| Windows executable | Cross-built x64; native Windows execution still pending |
| PowerShell / shell | Setup and launch scripts parse successfully |
| Dependency resolution | Complete CPU lockfile and Windows Python 3.12 x64 setup requirements resolve successfully; CPU/GPU runtime pip checks pass |
| Dependency and privacy scans | See SECURITY-REVIEW.md; registry audits are clear; the locally patched build dependency has separate exploit regressions |

The two real-AI duration tests are optional and were skipped in the clean release test environment because weights are excluded, then passed separately on synthetic footage using cached Classic weights and the updated rembg/Pillow runtime. Synthetic matting stubs verify alpha composition and independent VR180 eyes; they do not establish model quality. Prior GPU inference work is not a hardware certification for this alpha.

Run tests with Python 3.12, FFmpeg/ffprobe, NumPy, Pillow, ONNX Runtime and cryptography. The Qt check additionally needs PySide6. API tests must use `python scripts/test_api_runner.py` with the built backend, never the personal working library. Browser checks need Playwright, Chrome and `npm ci` in `quest/app`; set `QUEST_PYTHON` to the test runtime, and optionally `QUEST_TEST_MODEL` to a cached Depth Anything V2 Small q8 ONNX file.

Real Quest input/comfort, per-eye matting quality on camera footage, Windows display composition and driver combinations still need device testing. Do not describe emulator results as physical-headset verification.
