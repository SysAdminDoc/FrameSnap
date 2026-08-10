# Changelog

All notable changes to FrameSnap will be documented in this file.

## [v2.3.0] - 2026-08-08

- Changed: removed first-run package installation and added explicit dependency diagnostics.
- Added: pyproject metadata, a single version source, and a hash-locked Windows CPython 3.12
  runtime manifest for reproducible local setup.
- Added: headless cross-platform CI, Windows package smoke coverage, lock validation, dependency
  auditing, and version-metadata synchronization tests.
- Changed: session, template, and preference writes are atomic, keep one rolling backup, and
  reject unsupported future schemas with actionable errors.
- Added: generation-aware cooperative cancellation for analysis workers and bounded, acknowledged
  shutdown without force termination.
- Added: transactional still, animation, contact-sheet, and batch outputs with explicit collision
  policies plus hash-verified resumable export manifests.
- Added: bounded marker parsing, Unicode/reserved-name filename sanitization, and output-root/
  reparse-point checks for safer local media exports.
- Added: frame/time identities for marks and manifests, including decoder PTS/time-base metadata
  when available and explicit Exact, Approximate, and Nearest timestamp seek modes.
- Added: A/B comparison by frame index or presentation time, signed offsets, per-source frame/time
  overlays, and deterministic mismatched-boundary handling.
- Added: keyboard and screen-reader parity for core controls, keyboard thumbnail navigation, a
  high-contrast theme, and a scrollable export panel for scaled layouts.
- Added: user-invoked redacted support bundles with runtime capabilities, decoder attempts, timing,
  classified failures, and visible hardware-fallback reasons; no telemetry or media data is collected.
- Added: indexed, quota-bounded proxy caching with source/settings identity, safe stale/partial
  cleanup, low-disk refusal, and cancellable progress reporting.
- Added: searchable mark metadata plus stable, atomic JSON/CSV export and import preserving
  source, frame, presentation-time, PTS, labels, tags, comments, chapters, and colors.
- Added: Qt Linguist runtime catalogs with Spanish UI support, locale-aware visible numbers and
  timecodes, restart-safe language preferences, and CI checks for missing or stale translations.
- Added: versioned local plugin registry for opt-in detectors, probes, and exporters; manifest
  discovery is non-executable, capabilities are declared and inspectable, and session loading
  never executes plugin code. Added headless manifest inspection/loading and explicit config-based
  enablement without plugin-specific MainWindow changes.
- Added: deterministic SHA-256 release manifests with offline verification, reproducible source
  inputs, synchronized version metadata, and an explicitly invoked, cancellable update check that
  sends no media paths or telemetry and introduces no signing requirement.

## [v2.2.0] - 2026-08-03

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
- Added: multi-video drag-and-drop/open queues with mark reuse and previous/next navigation.
- Added: noninteractive CSV/JSON marker-list export with frame/time selection and transforms.
- Added: Windows per-monitor-v2 DPI setup and Latte, GitHub Dark, and AMOLED themes.
- Added: native Linux AppImage and Flatpak bundles with desktop metadata and pinned runtime wheels.
- Added: background perceptual-hash similarity search with configurable threshold and sampling.
- Added: current-frame QR and barcode detection through OpenCV.
- Added: per-video mouse-wheel step settings persisted in the local configuration.
- Added: side-by-side A/B viewer with synchronized frame-index navigation for two videos.
- Added: `multiprocessing.freeze_support()` for frozen OpenCV/PyAV entry points.
- Fixed: Windows PyInstaller builds include NumPy’s frozen exception module and tolerate missing
  standard streams in windowed CLI paths.
- Fixed: frozen PyInstaller builds no longer recursively invoke the dependency bootstrapper.

## [v2.1.0] - %Y->- (HEAD -> main, origin/main)

- Added: Add screenshot to README
- Added: Add app icon and update CI to embed it in executables
- Added: Add GitHub Actions workflow: build executables for Windows, macOS, Linux
- v2.1.0: update README, remove duplicate SAPPHIRE constant
- Fixed: Fix NameError: add missing SAPPHIRE palette constant
- v2.1.0: bug fixes, all-format support, power features
- Initial release: FrameSnap v2.0.0

## Roadmap archive — 2026-08-10 — ROADMAP.md

<details>
<summary>Original roadmap snapshot</summary>

```markdown
# ROADMAP

Backlog for FrameSnap. Stays a single-window, mouse-first, Catppuccin-themed desktop app for
browsing video and exporting precise frames.

## Planned Features

### Playback engine

### Frame precision

### Marking

### Export

### Sessions

### UI / UX

### Distribution

## Competitive Research

- **VideoProc Converter AI** — "extract frames" wizard + AI upscale. FrameSnap should not chase
  the AI angle; differentiate on precision + session portability.
- **ScreenToGif** — open-source, Windows-only; its frame editor is a model for granular per-frame
  edit workflows.
- **Shotcut / DaVinci Resolve** — full NLEs with frame export. FrameSnap stays in the "I only want
  stills and a few GIFs" niche rather than competing.
- **Kreatli / VideoToJPG.com / Teamz Converter** — rising browser-based, WASM-powered
  competitors. Desktop edge: >2GB files, local processing, no upload cap.
- **VLC "Save video snapshot"** — the 1-click baseline everyone compares to; match its speed for
  single-shot extractions.

## Open-Source Research (Round 2)

### Related OSS Projects
- **KimSource/video-frame-extractor** — https://github.com/KimSource/video-frame-extractor — Python GUI wrapping ffmpeg; PyInstaller-built exe.
- **noarche/FrameExtractor** — https://github.com/noarche/FrameExtractor — Portable exe; per-video count-based sampling.
- **EnragedAntelope/youtube-screenshot-extractor** — https://github.com/EnragedAntelope/youtube-screenshot-extractor — yt-dlp-fed 1000-site extractor; scene detection + keyframe + aesthetic filter.
- **Gifcurry** — https://github.com/lettier/gifcurry — Haskell GUI+CLI; powerful trim/crop/text-overlay pipeline worth mirroring.
- **ScreenToGif** — https://github.com/NickeManarin/ScreenToGif — C#/WPF; live frame-editor with per-frame annotate/delete.
- **Video Frame Extractor Pro** (Qt+OpenCV topic entry) — https://github.com/topics/frame-extraction — Qt frame extractor worth studying for scrubber UX.

### Features to Borrow
- yt-dlp-fed input (`EnragedAntelope`) — accept a YouTube/Vimeo/TikTok URL, resolve best stream, scrub in place. Removes manual download step.
- PySceneDetect content/adaptive detection (`EnragedAntelope`) — "snap to scene boundary" button that finds nearest cut.
- Blur/aesthetic filter at export (`EnragedAntelope` — CLIP/LAION scorer) — discard out-of-focus candidates in batch runs.
- Per-frame annotate (ScreenToGif) — reuse its frame-list + undo stack model for exported contact sheets.
- Batch-sampling presets from `noarche/FrameExtractor` — "every N seconds" / "N uniform frames" / "all I-frames".
- GIF + MP4 export in addition to stills (`Gifcurry`) — reuse ffmpeg already in the project.
- Text overlay with timing (`Gifcurry`) — watermark/label stills at export.

### Patterns & Architectures Worth Studying
- **OpenCV `VideoCapture.set(CAP_PROP_POS_FRAMES)` vs ffmpeg `-ss` seek** — OpenCV is accurate-per-frame but slow; ffmpeg `-ss` before `-i` is fast but keyframe-only. Most extractors pick one; the good ones implement "fast seek + fine adjust" (ffmpeg for rough, OpenCV for exact).
- **Decoupled producer/consumer queue**: decoder thread fills a bounded frame queue; GUI thread consumes. Keeps UI at 60fps during scrub. Used in the Qt+OpenCV topic entry.
- **PyAV over subprocess ffmpeg**: libavformat bindings give per-frame PTS without parsing stderr; cleaner than spawning ffmpeg per export.
- **MediaInfo sidecar** (`EnragedAntelope`): probe codec/framerate/HDR flags once, cache in sqlite keyed by file hash — skip re-probe on re-open.

## Research-Driven Additions
```

</details>
