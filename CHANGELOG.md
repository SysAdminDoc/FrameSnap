# Changelog

All notable changes to FrameSnap will be documented in this file.

## [Unreleased] - 2026-08-03

- Added: optional PyAV decoding with OpenCV fallback, hardware-decode requests, and audio-track metadata.
- Added: background audio waveform analysis and a timeline waveform track under the scrubber.
- Added: persisted Exact frame and Fast keyframe seek modes for PyAV playback.
- Added: opt-in cached 1280px proxy playback for large videos while exports read the source.
- Added: background thumbnail strip sampling with click-to-jump timeline navigation.
- Added: background histogram-based scene-cut detection with automatic marks.
- Added: embedded MP4/MKV chapter starts as labeled marks.
- Added: comma-separated marker tags with persisted group-filtered exports.
- Added: timestamped mark comments with visible shot-note metadata and session persistence.
- Added: Ripple Delete action with compact export numbering after mark removal.
- Added: opt-in burn-in overlays, reusable crop rectangles, and 16-bit TIFF/EXR export.
- Added: animated WebP export, AVIF still export, and configurable contact-sheet title,
  watermark, columns, and PDF output.
- Added: per-mark FFmpeg extraction command echo for scripted replay.
- Added: same-video session merge and frame-level session diff actions.
- Added: relative-timestamp session templates that can be applied to another video.
- Fixed: frozen PyInstaller builds no longer recursively invoke the dependency bootstrapper.

## [v2.1.0] - %Y->- (HEAD -> main, origin/main)

- Added: Add screenshot to README
- Added: Add app icon and update CI to embed it in executables
- Added: Add GitHub Actions workflow: build executables for Windows, macOS, Linux
- v2.1.0: update README, remove duplicate SAPPHIRE constant
- Fixed: Fix NameError: add missing SAPPHIRE palette constant
- v2.1.0: bug fixes, all-format support, power features
- Initial release: FrameSnap v2.0.0
