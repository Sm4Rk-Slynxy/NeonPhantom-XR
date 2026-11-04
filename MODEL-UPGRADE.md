# Cutout engine upgrade

The existing Classic engine remains the default until comparisons on representative
clips establish a better default. MatAnyone 2 is the first candidate for people;
WeVisOne is experimental for described objects, animals, and characters.

## Use

Choose **Auto cutout** or **AI cutout**, then select the model. Click **Download &
install** for an optional engine. Installation runs in the same serial queue as
imports, shows progress and errors, and can be retried. No model is downloaded just
by opening the menu. A completed install marker means dependencies and weights
were downloaded; it is not a performance or GPU-memory guarantee.

For WeVisOne, describe the subject to retain. Multiple matches are combined by
pixel-wise maximum; no match produces a transparent frame. Image inference runs
per frame and has no temporal smoothing or tracking. A 3-second preview can still
take a long time on CPU. The 2B model is the suggested starting point.

MatAnyone 2 uses Classic's detailed human matte to seed its first frame, refines
that frame with ten warm-up iterations, and carries memory through the rest of the
clip. The optional normalized first-frame region restricts the human seed rather
than generating a rectangular matte. The subject text field applies to WeVisOne;
it is not used to guide MatAnyone. People should be visible in the first frame.

Choose a three-second preview before a full conversion. Preview clips are labeled
and do not replace existing cards. Full imports preserve their original duration;
Fast limits processing to 480px / 12fps and Detailed to 720px / 30fps. The complete
original RGB frame is retained and combined with the generated alpha matte.
Imports process frames sequentially, retaining temporal memory for MatAnyone;
intermediate PNG sequences need disk space proportional to clip length.

Model/subject options survive retries, are recorded on jobs, and the engine is
recorded on new cards. Old state files get safe defaults. Browser preferences
remember model, subject, background mode, and quality. Preview is never remembered.

## Environments and sources

- Classic uses the existing `DESKDANCE_PYTHON` / GPU wrapper / CPU fallback.
- MatAnyone uses `.venv-matanyone2` and `.models/matanyone2`.
- Both WeVisOne sizes share `.venv-wevisone` but have separate weight directories.
- `python model_manager.py list` reports availability; `python model_manager.py
  install matanyone2` (or `wevisone-2b` / `wevisone-4b`) installs on demand.

Pinned inference source:

- [MatAnyone 2](https://github.com/pq-yang/MatAnyone2/tree/0079197acd6d16a741f71558809c06c586c579e0)
  — `0079197acd6d16a741f71558809c06c586c579e0`.
- [WeVisOne-VL](https://github.com/Tencent/WeVisOne-VL/tree/9a6bcd85404505df0d05cfb5d97512ccacf35dee)
  — `9a6bcd85404505df0d05cfb5d97512ccacf35dee`.

MatAnyone's inference subset is installed separately from its full training/GUI
dependency set for portability. The installer removes a duplicate `force-include`
entry from the pinned upstream wheel metadata; inference code remains unchanged.
WeVisOne follows upstream dependency requirements.
Weights download from the official MatAnyone release and Tencent Hugging Face
repositories. Model packages and weights are not redistributed inside NeonPhantom XR.
Review the [MatAnyone license](https://github.com/pq-yang/MatAnyone2/blob/main/LICENSE.txt)
and [WeVisOne license](https://huggingface.co/tencent/WeVisOne-VL-2B) before commercial distribution.

MatAnyone-E and VideoMaMa++ are not offered until installable upstream inference
weights and code are available. LTX Alpha Gen is excluded from this first upgrade
because long clips require chunking and upper-bound workloads need substantial GPU memory.

## CUDA runtime isolation fix

Each optional engine's child process now starts with its own NVIDIA and PyTorch
library directories first. Python-distributed CUDA libraries inherited from
Classic or another application are removed from the child's loader path; system
driver and unrelated library directories are retained. This prevents mixing
cuDNN's versioned sublibraries across environments. The same isolation is applied
to model dependency installation and validation. No driver changes are required.


## Download integrity

MatAnyone 2's v1.0.0 checkpoint is verified against the publisher's SHA-256 before installation and each load: `5e9821e4087231427376b437c85bb6e072b41e582314f06fd524f75bc4af5914`. Source/depth/checkpoint helpers require HTTPS even after redirects, and keep an existing model if a replacement download fails validation.

New WeVisOne installations pin weight revisions as well as inference source:

- 2B: `fcf8c8ca7fa481b514005ef591c8b72bed39618a`.
- 4B: `6b44a45873b4bbc7dca383922504430dc60eca23`.

Existing installations retain their current weights. Optional third-party packages still execute locally and retain their upstream licenses.
