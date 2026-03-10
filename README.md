# FrameSnap

> Browse MP4 videos, mark frames visually, and export precise screenshots — all in a dark, polished desktop app.

![Version](https://img.shields.io/badge/version-2.0.0-cba6f7?style=flat-square)
![Python](https://img.shields.io/badge/python-3.10%2B-89b4fa?style=flat-square)
![License](https://img.shields.io/badge/license-MIT-a6e3a1?style=flat-square)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-b4befe?style=flat-square)

---

## Features

### Video Playback
- Open MP4, AVI, MOV, MKV, WMV, FLV, and WebP video files
- Play/Pause with native FPS timing
- Step frame-by-frame (-10, -1, +1, +10)
- Drag scrubber to any position
- **Mouse wheel** on the video to step frames
- **Drag-and-drop** a video file directly onto the window
- Recent files menu for quick access

### Scrubber
- **Live hover preview** — floating thumbnail with timestamp follows your cursor along the scrubber
- **Mark tick indicators** — purple ticks drawn directly on the scrubber at every marked position

### Frame Marking
- **Mark current frame** with one click — thumbnail + timestamp added to the Marks panel
- **Per-mark labels** — right-click any mark to add a custom label (shown in italic)
- **Jump to frame** from any mark via "Go" button or right-click menu
- **Prev / Next mark** navigation buttons for quick cycling
- **Multi-select** marks with Ctrl/Shift+Click, then bulk delete selected
- Marks are kept sorted by time and persist in sessions

### Export
- **Format:** PNG (lossless), JPEG, or WebP
- **Quality control** for JPEG and WebP (1–100%)
- **Scale:** 100%, 75%, 50%, 25%, or custom pixel width
- **Filename template** with variables:
  - `{stem}` — video filename without extension
  - `{frame}` — zero-padded frame number (e.g. `001234`)
  - `{ts}` — timestamp as `HH-MM-SS-mmm`
  - `{label}` — custom mark label (or `mark` if unset)
  - `{n}` — sequential mark number
- **Open Folder** button to reveal the export directory in Explorer / Finder
- **Copy to Clipboard** — copy the current frame or any mark's frame directly

### Sessions
- **Save Session** — stores video path + all marks + labels to a `.fsnap` JSON file
- **Load Session** — restores video, marks, and labels from a session file

### UX
- **Frame overlay** on video display — shows frame number, total frames, and timestamp (toggleable via View menu)
- **Video info bar** — resolution, FPS, duration, frame count, file size shown on load
- Preferences auto-saved (output folder, format, quality, scale, template, overlay state)
- Catppuccin Mocha dark theme throughout

---

## Requirements

- Python 3.10+
- Dependencies are **auto-installed on first run**: `PyQt6`, `opencv-python`, `numpy`

---

## Installation & Usage

```bash
git clone https://github.com/SysAdminDoc/FrameSnap.git
cd FrameSnap
python framesnap.py
```

On first launch, missing packages are installed automatically via pip. No manual setup required.

---

## Workflow

1. **Open** a video via `File > Open Video...`, the button, or drag-and-drop
2. **Scrub** the timeline — hover to preview any frame
3. **Navigate** with play, step buttons, or mouse wheel on the video
4. **Mark** frames with the purple **Mark Frame** button
5. **Label** marks via right-click → Edit Label
6. Switch to the **Export** tab
7. Choose format, quality, scale, and a filename template
8. Click **Export All Frames**

---

## Keyboard-Free Design

FrameSnap is designed for pure mouse/GUI operation. All actions are accessible through visible controls, right-click context menus, and the menu bar.

---

## License

MIT — see [LICENSE](LICENSE)
