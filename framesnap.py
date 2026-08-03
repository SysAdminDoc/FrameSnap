#!/usr/bin/env python3
"""
FrameSnap v2.1.0
Browse any video, mark frames, and export screenshots — all formats, all features.
"""

import sys
import os
import json
import subprocess
import math
import hashlib
from pathlib import Path


# codex-branding:start
def _branding_icon_path() -> Path:
    candidates = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / "icon.png")
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "icon.png")
    current = Path(__file__).resolve()
    candidates.extend([current.parent / "icon.png", current.parent.parent / "icon.png", current.parent.parent.parent / "icon.png"])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return Path("icon.png")
# codex-branding:end


# ── Bootstrap ─────────────────────────────────────────────────────────────────

def _bootstrap():
    # PyInstaller bundles the dependencies; running the installer from a
    # frozen executable would recurse through sys.executable indefinitely.
    if getattr(sys, "frozen", False):
        return
    import importlib
    to_install = []
    for mod, pkg in [
        ("cv2",   "opencv-python"),
        ("numpy", "numpy"),
        ("PIL",   "Pillow"),
    ]:
        try:
            importlib.import_module(mod)
        except ImportError:
            to_install.append(pkg)
    try:
        importlib.import_module("PyQt6")
    except ImportError:
        to_install.append("PyQt6")
    if to_install:
        print(f"Installing: {', '.join(to_install)}")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install",
             "--break-system-packages"] + to_install,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


_bootstrap()

# OpenCV wheels ship the EXR codec behind an opt-in switch.
os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image as PilImage  # noqa: E402
from PIL import features as PilFeatures  # noqa: E402
try:
    import av  # noqa: E402
except ImportError:  # pragma: no cover - optional dependency
    av = None
from PyQt6.QtWidgets import (  # noqa: E402
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QSlider, QListWidget, QListWidgetItem,
    QFileDialog, QLineEdit, QGroupBox, QSizePolicy, QFrame, QSplitter,
    QMenu, QComboBox, QSpinBox, QInputDialog, QMessageBox,
    QStyle, QStyleOptionSlider, QTabWidget, QAbstractItemView, QCheckBox,
)
from PyQt6.QtCore import (  # noqa: E402
    Qt, QTimer, QThread, QMutex, QWaitCondition, pyqtSignal,
    QPoint, QSize, QRect,
)
from PyQt6.QtGui import (  # noqa: E402
    QPixmap, QImage, QIcon, QPainter, QColor, QFont, QAction,
    QDragEnterEvent, QDropEvent,
)


# ── Palette ───────────────────────────────────────────────────────────────────

BASE     = "#1e1e2e"
MANTLE   = "#181825"
CRUST    = "#11111b"
SURFACE0 = "#313244"
SURFACE1 = "#45475a"
SURFACE2 = "#585b70"
TEXT     = "#cdd6f4"
SUBTEXT0 = "#a6adc8"
OVERLAY0 = "#6c7086"
MAUVE    = "#cba6f7"
LAVENDER = "#b4befe"
BLUE     = "#89b4fa"
GREEN    = "#a6e3a1"
RED      = "#f38ba8"
PEACH    = "#fab387"
YELLOW   = "#f9e2af"
TEAL     = "#94e2d5"
SAPPHIRE = "#74c7ec"

MARK_COLORS: dict[str, str] = {
    "Default": MAUVE,
    "Red":     RED,
    "Green":   GREEN,
    "Blue":    BLUE,
    "Orange":  PEACH,
    "Yellow":  YELLOW,
    "Teal":    TEAL,
}

# All extensions cv2 / FFmpeg can typically handle
SUPPORTED_EXTS = (
    ".mp4", ".m4v", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".webm",
    ".ts",  ".mts", ".m2ts", ".m2t", ".m2v", ".mpg", ".mpeg", ".mpe",
    ".mxf", ".ogv", ".ogg", ".3gp", ".3g2", ".asf", ".vob", ".divx",
    ".rm",  ".rmvb", ".f4v", ".dv",  ".y4m", ".yuv", ".hevc", ".h264",
    ".h265",".bik",  ".smk", ".nut", ".roq", ".rv",  ".swf",  ".gif",
    ".amv", ".mpv",  ".mj2", ".mjpeg",
)
_ext_glob = " ".join(f"*{e}" for e in SUPPORTED_EXTS)
VIDEO_FILTER = f"Video Files ({_ext_glob});;All Files (*)"

STYLESHEET = f"""
QMainWindow, QDialog, QWidget {{
    background-color: {BASE};
    color: {TEXT};
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 13px;
}}
QLabel {{ color: {TEXT}; background: transparent; }}
QMenuBar {{
    background-color: {MANTLE};
    color: {TEXT};
    border-bottom: 1px solid {SURFACE0};
    padding: 2px 4px;
}}
QMenuBar::item:selected {{ background-color: {SURFACE0}; border-radius: 4px; }}
QMenu {{
    background-color: {MANTLE};
    border: 1px solid {SURFACE1};
    border-radius: 6px;
    padding: 4px;
}}
QMenu::item {{ padding: 5px 22px; border-radius: 4px; }}
QMenu::item:selected {{ background-color: {SURFACE1}; color: {MAUVE}; }}
QMenu::separator {{ height: 1px; background: {SURFACE1}; margin: 4px 10px; }}
QPushButton {{
    background-color: {SURFACE0};
    color: {TEXT};
    border: 1px solid {SURFACE1};
    border-radius: 6px;
    padding: 6px 14px;
}}
QPushButton:hover {{ background-color: {SURFACE1}; border-color: {MAUVE}; color: {MAUVE}; }}
QPushButton:pressed {{ background-color: {SURFACE2}; }}
QPushButton:disabled {{ color: {OVERLAY0}; border-color: {SURFACE0}; background-color: {MANTLE}; }}
QPushButton#markBtn {{
    background-color: {MAUVE}; color: {CRUST};
    font-weight: bold; border: none; font-size: 14px;
    padding: 8px 22px; border-radius: 8px;
}}
QPushButton#markBtn:hover {{ background-color: {LAVENDER}; }}
QPushButton#markBtn:disabled {{ background-color: {SURFACE1}; color: {OVERLAY0}; }}
QPushButton#exportBtn {{
    background-color: {GREEN}; color: {CRUST};
    font-weight: bold; border: none;
    padding: 8px 16px; border-radius: 8px;
}}
QPushButton#exportBtn:hover {{ background-color: #b9f1b5; }}
QPushButton#exportBtn:disabled {{ background-color: {SURFACE1}; color: {OVERLAY0}; }}
QPushButton#sheetBtn {{
    background-color: {TEAL}; color: {CRUST};
    font-weight: bold; border: none;
    padding: 8px 16px; border-radius: 8px;
}}
QPushButton#sheetBtn:hover {{ background-color: #a7f0e8; }}
QPushButton#sheetBtn:disabled {{ background-color: {SURFACE1}; color: {OVERLAY0}; }}
QPushButton#copyBtn {{
    background-color: {BLUE}; color: {CRUST};
    font-weight: bold; border: none;
    padding: 8px 16px; border-radius: 8px;
}}
QPushButton#copyBtn:hover {{ background-color: {LAVENDER}; }}
QPushButton#copyBtn:disabled {{ background-color: {SURFACE1}; color: {OVERLAY0}; }}
QPushButton#loopBtn {{
    background-color: {SURFACE0}; color: {TEXT};
    border: 1px solid {SURFACE1}; border-radius: 6px; padding: 6px 12px;
}}
QPushButton#loopBtn[active="true"] {{
    background-color: {SAPPHIRE}; color: {CRUST};
    border: none; font-weight: bold;
}}
QPushButton#dangerBtn {{
    background-color: {SURFACE0}; color: {RED};
    border: 1px solid {SURFACE1}; border-radius: 6px; padding: 6px 12px;
}}
QPushButton#dangerBtn:hover {{ background-color: {RED}; color: {CRUST}; border-color: {RED}; }}
QSlider::groove:horizontal {{
    height: 6px; background-color: {SURFACE0}; border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background-color: {MAUVE}; width: 16px; height: 16px;
    margin: -5px 0; border-radius: 8px; border: 2px solid {CRUST};
}}
QSlider::sub-page:horizontal {{ background-color: {MAUVE}; border-radius: 3px; }}
QSlider::handle:horizontal:disabled {{ background-color: {SURFACE2}; }}
QSlider::sub-page:horizontal:disabled {{ background-color: {SURFACE1}; }}
QListWidget {{
    background-color: {MANTLE}; border: 1px solid {SURFACE0};
    border-radius: 8px; padding: 4px; outline: none;
}}
QListWidget::item {{ border-radius: 6px; padding: 2px; border: 1px solid transparent; }}
QListWidget::item:selected {{ background-color: {SURFACE1}; border: 1px solid {SURFACE2}; }}
QListWidget::item:hover {{ background-color: {SURFACE0}; }}
QScrollBar:vertical {{
    background-color: {MANTLE}; width: 8px; border-radius: 4px; margin: 0;
}}
QScrollBar::handle:vertical {{ background-color: {SURFACE2}; border-radius: 4px; min-height: 20px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QLineEdit {{
    background-color: {MANTLE}; border: 1px solid {SURFACE1};
    border-radius: 6px; padding: 5px 10px; color: {TEXT};
}}
QLineEdit:focus {{ border-color: {MAUVE}; }}
QComboBox {{
    background-color: {SURFACE0}; color: {TEXT};
    border: 1px solid {SURFACE1}; border-radius: 6px;
    padding: 5px 10px; min-width: 72px;
}}
QComboBox:hover {{ border-color: {MAUVE}; }}
QComboBox::drop-down {{ border: none; width: 20px; }}
QComboBox QAbstractItemView {{
    background-color: {MANTLE}; color: {TEXT};
    border: 1px solid {SURFACE1}; border-radius: 6px;
    selection-background-color: {SURFACE1};
    selection-color: {MAUVE};
    outline: none;
}}
QSpinBox {{
    background-color: {SURFACE0}; color: {TEXT};
    border: 1px solid {SURFACE1}; border-radius: 6px; padding: 5px 8px;
}}
QSpinBox:focus {{ border-color: {MAUVE}; }}
QGroupBox {{
    border: 1px solid {SURFACE1}; border-radius: 10px;
    margin-top: 14px; padding: 10px 8px 8px 8px;
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 12px;
    padding: 0 6px; color: {MAUVE}; font-weight: bold; font-size: 12px;
}}
QTabWidget::pane {{
    border: 1px solid {SURFACE1}; border-radius: 8px;
    background: {MANTLE}; top: -1px;
}}
QTabBar::tab {{
    background: {SURFACE0}; color: {SUBTEXT0};
    border-radius: 6px 6px 0 0; padding: 7px 18px; margin-right: 2px;
}}
QTabBar::tab:selected {{ background: {MAUVE}; color: {CRUST}; font-weight: bold; }}
QTabBar::tab:hover:!selected {{ background: {SURFACE1}; color: {TEXT}; }}
QSplitter::handle {{ background-color: {SURFACE0}; width: 2px; }}
QFrame[frameShape="4"] {{ color: {SURFACE1}; }}
"""

CONFIG_PATH     = Path.home() / ".framesnap_config.json"
MAX_RECENT      = 10
DEFAULT_TEMPLATE = "{stem}_{frame}_{ts}"
PROXY_CACHE_DIR  = Path.home() / ".framesnap_proxy_cache"
PROXY_MAX_WIDTH  = 1280
PROXY_MIN_BYTES  = 1_000_000_000


# ── Utilities ─────────────────────────────────────────────────────────────────

def ms_to_ts(ms: float) -> str:
    total_s = int(ms) // 1000
    millis  = int(ms) % 1000
    h = total_s // 3600
    m = (total_s % 3600) // 60
    s = total_s % 60
    return f"{h:02d}:{m:02d}:{s:02d}.{millis:03d}"


def frame_to_ms(idx: int, fps: float) -> float:
    return (idx / fps) * 1000.0 if fps > 0 else 0.0


def bgr_to_pixmap(bgr: np.ndarray) -> QPixmap:
    """Convert a BGR numpy frame to QPixmap safely (copies buffer)."""
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    h, w, ch = rgb.shape
    # Use bytes() to own the data — avoids QImage holding a dangling pointer
    return QPixmap.fromImage(
        QImage(bytes(rgb), w, h, ch * w, QImage.Format.Format_RGB888)
    )


def make_thumb(bgr: np.ndarray, tw: int = 96, th: int = 54) -> QPixmap:
    return bgr_to_pixmap(bgr).scaled(
        tw, th,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def sizeof_fmt(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(num) < 1024.0:
            return f"{num:.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} TB"


def safe_filename(name: str) -> str:
    for ch in r'\/:*?"<>|':
        name = name.replace(ch, "_")
    return name.strip(". ") or "frame"


def apply_template(template: str, stem: str, frame_idx: int,
                   fps: float, label: str, n: int) -> str:
    ts  = ms_to_ts(frame_to_ms(frame_idx, fps)).replace(":", "-").replace(".", "-")
    lbl = label.strip() or "mark"
    try:
        result = template.format(
            stem=stem, frame=f"{frame_idx:06d}",
            ts=ts, label=lbl, n=f"{n:03d}",
        )
    except (KeyError, ValueError):
        result = f"{stem}_{frame_idx:06d}_{ts}"
    return safe_filename(result)


def parse_tags(value: str) -> list[str]:
    """Normalize comma-separated mark tags while preserving user order."""
    tags = []
    seen = set()
    for raw in value.split(","):
        tag = " ".join(raw.strip().split())
        key = tag.casefold()
        if tag and key not in seen:
            tags.append(tag)
            seen.add(key)
    return tags


def ordered_mark_indices(marked: dict, group: str = "All") -> list[int]:
    return sorted(
        idx for idx, mark in marked.items()
        if group == "All" or group in parse_tags(mark.get("tags", ""))
    )


def export_sequence(marked: dict, group: str = "All") -> dict[int, int]:
    """Assign compact 1-based export numbers after any mark is removed."""
    return {
        idx: number for number, idx in enumerate(
            ordered_mark_indices(marked, group), start=1
        )
    }


def crop_frame(frame: np.ndarray, x: int, y: int,
               width: int, height: int) -> np.ndarray:
    """Return a clamped copy of a crop rectangle, or the original frame."""
    if width <= 0 or height <= 0:
        return frame
    frame_height, frame_width = frame.shape[:2]
    left = max(0, min(int(x), frame_width - 1))
    top = max(0, min(int(y), frame_height - 1))
    right = min(frame_width, left + int(width))
    bottom = min(frame_height, top + int(height))
    if right <= left or bottom <= top:
        return frame
    return frame[top:bottom, left:right].copy()


def burn_in_overlay(frame: np.ndarray, frame_idx: int, fps: float,
                    label: str = "") -> np.ndarray:
    """Burn frame/timestamp/label metadata into a copy of an 8-bit BGR frame."""
    result = frame.copy()
    timestamp = ms_to_ts(frame_to_ms(frame_idx, fps))
    lines = [f"Frame {frame_idx:,}  |  {timestamp}"]
    if label.strip():
        lines.append(label.strip())
    scale = max(0.45, min(1.2, result.shape[1] / 1280.0))
    thickness = max(1, round(scale * 2))
    font = cv2.FONT_HERSHEY_SIMPLEX
    pad = max(8, round(10 * scale))
    line_height = max(18, round(24 * scale))
    text_width = max(cv2.getTextSize(line, font, scale, thickness)[0][0]
                     for line in lines)
    box_height = pad * 2 + line_height * len(lines)
    overlay = result.copy()
    cv2.rectangle(overlay, (0, 0), (text_width + pad * 2, box_height),
                  (17, 17, 27), cv2.FILLED)
    result = cv2.addWeighted(overlay, 0.78, result, 0.22, 0)
    for index, line in enumerate(lines):
        cv2.putText(result, line, (pad, pad + line_height * (index + 1) - 5),
                    font, scale, (203, 166, 247), thickness, cv2.LINE_AA)
    return result


def to_uint16_frame(frame: np.ndarray) -> np.ndarray:
    return np.asarray(frame, dtype=np.uint16) * 257


def ffmpeg_extract_command(video_path: str, frame_idx: int, fps: float,
                            output_path: str) -> str:
    """Return a reproducible FFmpeg single-frame extraction command."""
    seconds = frame_to_ms(frame_idx, fps) / 1000.0
    video = str(video_path).replace('"', '\\"')
    output = str(output_path).replace('"', '\\"')
    return f'ffmpeg -ss {seconds:.3f} -i "{video}" -frames:v 1 -y "{output}"'


BACKEND_OPTIONS = ["Auto", "OpenCV"] + (["PyAV"] if av is not None else [])
SEEK_OPTIONS = ["Exact frame", "Fast keyframe"]


def _hardware_backend_name() -> str:
    if sys.platform == "win32":
        return "d3d11va"
    if sys.platform == "darwin":
        return "videotoolbox"
    return "vaapi"


class VideoReader:
    """Small common reader API for OpenCV and optional PyAV decoding."""

    def __init__(self, path: str, backend: str = "Auto",
                 hardware_accel: bool = False,
                 exact_seek: bool = True):
        self.path = path
        self.backend_name = ""
        self.audio_tracks: int | None = None
        self.hardware_accel = False
        self.hardware_fallback = False
        self.exact_seek = exact_seek
        self._cv_cap: cv2.VideoCapture | None = None
        self._container = None
        self._stream = None
        self._decoder = None
        self._seek_target: int | None = None
        self._current_frame = -1
        self._decode_index = 0

        requested = backend if backend in BACKEND_OPTIONS else "Auto"
        candidates = [requested]
        if requested == "Auto":
            candidates = ["PyAV", "OpenCV"] if av is not None else ["OpenCV"]

        last_error: Exception | None = None
        for candidate in candidates:
            try:
                if candidate == "PyAV":
                    self._open_pyav(path, hardware_accel)
                else:
                    self._open_opencv(path)
                return
            except Exception as exc:
                last_error = exc
                self.release()

        detail = f" ({last_error})" if last_error else ""
        raise RuntimeError(f"No decoder could open {path}{detail}")

    def _open_opencv(self, path: str) -> None:
        for backend in (cv2.CAP_FFMPEG, cv2.CAP_ANY):
            cap = cv2.VideoCapture(path, backend)
            if cap.isOpened():
                self._cv_cap = cap
                self.backend_name = "OpenCV / FFmpeg"
                self.audio_tracks = _probe_audio_tracks(path)
                return
            cap.release()
        raise RuntimeError("OpenCV could not open the video")

    def _open_pyav(self, path: str, hardware_accel: bool) -> None:
        if av is None:
            raise RuntimeError("PyAV is not installed")
        options = {}
        requested_accel = _hardware_backend_name() if hardware_accel else ""
        if requested_accel:
            options["hwaccel"] = requested_accel
        try:
            self._container = av.open(path, options=options)
        except Exception:
            if not options:
                raise
            self._container = av.open(path, options={})
            self.hardware_fallback = True

        self._stream = next(iter(self._container.streams.video), None)
        if self._stream is None:
            raise RuntimeError("PyAV found no video stream")
        try:
            self._stream.thread_type = "AUTO"
        except (AttributeError, ValueError):
            pass
        self._decoder = self._container.decode(self._stream)
        self.audio_tracks = len(self._container.streams.audio)
        self.hardware_accel = bool(requested_accel and not self.hardware_fallback)
        suffix = f" + {requested_accel}" if self.hardware_accel else ""
        self.backend_name = f"PyAV{suffix}"

    def isOpened(self) -> bool:
        if self._cv_cap is not None:
            return self._cv_cap.isOpened()
        return self._container is not None and self._stream is not None

    def release(self) -> None:
        if self._cv_cap is not None:
            self._cv_cap.release()
            self._cv_cap = None
        if self._container is not None:
            self._container.close()
            self._container = None
        self._stream = None
        self._decoder = None

    def _pyav_frame_index(self, frame) -> int:
        if frame.pts is not None and self._stream is not None:
            try:
                timestamp = float(frame.pts * self._stream.time_base)
                if timestamp >= 0:
                    return max(0, int(round(timestamp * self.fps)))
            except (TypeError, ValueError, ZeroDivisionError):
                pass
        return self._decode_index

    def read(self) -> tuple[bool, np.ndarray | None]:
        if self._cv_cap is not None:
            return self._cv_cap.read()
        if self._decoder is None:
            return False, None
        while True:
            try:
                frame = next(self._decoder)
            except StopIteration:
                return False, None
            idx = self._pyav_frame_index(frame)
            self._decode_index = idx + 1
            if self._seek_target is not None and idx < self._seek_target:
                continue
            self._seek_target = None
            self._current_frame = idx
            return True, frame.to_ndarray(format="bgr24")

    def set(self, prop: int, value: float) -> bool:
        if self._cv_cap is not None:
            return bool(self._cv_cap.set(prop, value))
        if prop == cv2.CAP_PROP_POS_FRAMES:
            self._seek_frame(max(0, int(value)))
            return True
        if prop == cv2.CAP_PROP_POS_MSEC:
            self._seek_frame(max(0, int(round(value * self.fps / 1000.0))))
            return True
        return False

    def _seek_frame(self, idx: int) -> None:
        if self._container is None or self._stream is None:
            return
        time_base = float(self._stream.time_base or 1 / 90_000)
        timestamp = int((idx / self.fps) / time_base) if self.fps > 0 else 0
        self._container.seek(max(0, timestamp), stream=self._stream,
                             any_frame=not self.exact_seek,
                             backward=self.exact_seek)
        self._decoder = self._container.decode(self._stream)
        self._seek_target = idx if self.exact_seek else None
        self._current_frame = idx - 1
        self._decode_index = max(0, idx - 1)

    @property
    def fps(self) -> float:
        if self._cv_cap is not None:
            return self._cv_cap.get(cv2.CAP_PROP_FPS) or 30.0
        if self._stream is not None:
            rate = self._stream.average_rate or self._stream.base_rate
            if rate:
                return float(rate)
        return 30.0

    @property
    def frame_count(self) -> int:
        if self._cv_cap is not None:
            return int(self._cv_cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if self._stream is None:
            return 0
        frames = int(self._stream.frames or 0)
        if frames > 0:
            return frames
        duration = self._stream.duration
        if duration is not None and self._stream.time_base is not None:
            return max(0, int(round(float(duration * self._stream.time_base)
                                     * self.fps)))
        return 0

    def get(self, prop: int) -> float:
        if self._cv_cap is not None:
            return self._cv_cap.get(prop)
        if prop == cv2.CAP_PROP_FPS:
            return self.fps
        if prop == cv2.CAP_PROP_FRAME_COUNT:
            return float(self.frame_count)
        if prop == cv2.CAP_PROP_FRAME_WIDTH:
            return float(self._stream.width if self._stream else 0)
        if prop == cv2.CAP_PROP_FRAME_HEIGHT:
            return float(self._stream.height if self._stream else 0)
        if prop == cv2.CAP_PROP_POS_FRAMES:
            return float(max(0, self._current_frame))
        return 0.0


def _probe_audio_tracks(path: str) -> int | None:
    """Read stream metadata for an OpenCV session when PyAV is available."""
    if av is None:
        return None
    try:
        with av.open(path) as container:
            return len(container.streams.audio)
    except Exception:
        return None


def open_cap(path: str, backend: str = "Auto",
             hardware_accel: bool = False,
             exact_seek: bool = True) -> VideoReader | None:
    try:
        return VideoReader(path, backend, hardware_accel, exact_seek)
    except (OSError, RuntimeError, ValueError):
        return None


def extract_audio_waveform(path: str, bucket_count: int = 1200) -> tuple[list[float], float]:
    """Return normalized RMS buckets and duration for the first audio track."""
    if av is None or bucket_count <= 0:
        return [], 0.0
    try:
        with av.open(path) as container:
            stream = next(iter(container.streams.audio), None)
            if stream is None:
                return [], 0.0
            duration = 0.0
            if stream.duration is not None and stream.time_base is not None:
                duration = float(stream.duration * stream.time_base)
            if duration <= 0 and container.duration:
                duration = float(container.duration) / 1_000_000.0

            levels = np.zeros(bucket_count, dtype=np.float32)
            cursor = 0.0
            last_bucket = -1
            for frame in container.decode(stream):
                raw = np.asarray(frame.to_ndarray())
                if raw.size == 0:
                    continue
                source_dtype = raw.dtype
                values = raw.astype(np.float32, copy=False)
                if np.issubdtype(source_dtype, np.integer):
                    info = np.iinfo(source_dtype)
                    denominator = float(max(abs(info.min), info.max))
                else:
                    peak = float(np.max(np.abs(values)))
                    denominator = 1.0 if peak <= 1.5 else max(peak, 1.0)
                rms = float(np.sqrt(np.mean(np.square(values / denominator))))
                rms = max(0.0, min(1.0, rms))

                frame_time = frame.time
                start_time = float(frame_time) if frame_time is not None else cursor
                sample_rate = frame.sample_rate or stream.rate or 1
                frame_duration = frame.samples / sample_rate
                end_time = start_time + frame_duration
                cursor = max(cursor, end_time)
                if duration > 0:
                    start = max(0, min(bucket_count - 1,
                                       int(start_time / duration * bucket_count)))
                    end = max(start + 1, int(math.ceil(
                        end_time / duration * bucket_count)))
                    end = min(bucket_count, end)
                else:
                    start = min(bucket_count - 1, last_bucket + 1)
                    end = min(bucket_count, start + 1)
                levels[start:end] = np.maximum(levels[start:end], rms)
                last_bucket = max(last_bucket, end - 1)

            if duration <= 0:
                duration = cursor
            peak = float(levels.max()) if levels.size else 0.0
            if peak > 0:
                levels /= peak
            return levels.tolist(), duration
    except Exception:
        return [], 0.0


def proxy_cache_path(path: str, max_width: int = PROXY_MAX_WIDTH) -> Path:
    """Return a content-aware cache location for a generated playback proxy."""
    source = Path(path).resolve()
    try:
        stat = source.stat()
        stamp = f"{source}|{stat.st_size}|{stat.st_mtime_ns}|{max_width}"
    except OSError:
        stamp = f"{source}|{max_width}"
    digest = hashlib.sha256(stamp.encode("utf-8")).hexdigest()[:24]
    return PROXY_CACHE_DIR / f"{digest}.mp4"


def build_video_proxy(source_path: str, output_path: str | Path,
                      max_width: int = PROXY_MAX_WIDTH) -> tuple[int, int]:
    """Create a silent, low-resolution MP4 proxy and return its dimensions."""
    if max_width <= 0:
        raise ValueError("max_width must be positive")
    source = cv2.VideoCapture(source_path, cv2.CAP_FFMPEG)
    if not source.isOpened():
        source.release()
        source = cv2.VideoCapture(source_path)
    if not source.isOpened():
        raise RuntimeError("could not open source video for proxy generation")

    width = int(source.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(source.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = source.get(cv2.CAP_PROP_FPS) or 30.0
    if width <= 0 or height <= 0:
        source.release()
        raise RuntimeError("source video has no usable dimensions")
    scale = min(1.0, max_width / width)
    proxy_width = max(2, int(round(width * scale / 2) * 2))
    proxy_height = max(2, int(round(height * scale / 2) * 2))

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.stem}.partial.mp4")
    writer = cv2.VideoWriter(
        str(temporary), cv2.VideoWriter_fourcc(*"mp4v"), fps,
        (proxy_width, proxy_height),
    )
    if not writer.isOpened():
        source.release()
        writer.release()
        temporary.unlink(missing_ok=True)
        raise RuntimeError("could not create proxy video")

    frames = 0
    try:
        while True:
            ok, frame = source.read()
            if not ok:
                break
            if frame.shape[1] != proxy_width or frame.shape[0] != proxy_height:
                frame = cv2.resize(frame, (proxy_width, proxy_height),
                                   interpolation=cv2.INTER_AREA)
            writer.write(frame)
            frames += 1
    finally:
        source.release()
        writer.release()

    if frames == 0:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("source video contained no decodable frames")
    os.replace(temporary, output)
    return proxy_width, proxy_height


def thumbnail_frame_indices(total_frames: int, count: int = 18) -> list[int]:
    if total_frames <= 0 or count <= 0:
        return []
    if count == 1:
        return [0]
    return sorted({
        round(index * (total_frames - 1) / (count - 1))
        for index in range(count)
    })


def detect_scene_cuts(path: str, backend: str = "Auto",
                      hardware_accel: bool = False,
                      exact_seek: bool = True,
                      threshold: float = 0.45,
                      min_gap_frames: int = 1) -> list[int]:
    """Find content cuts using histogram distance between consecutive frames."""
    reader = open_cap(path, backend, hardware_accel, exact_seek)
    if reader is None or not reader.isOpened():
        return []
    threshold = max(0.0, min(1.0, threshold))
    min_gap_frames = max(1, min_gap_frames)
    cuts: list[int] = []
    previous_hist = None
    last_cut = -min_gap_frames
    frame_idx = 0
    try:
        while True:
            ok, frame = reader.read()
            if not ok or frame is None:
                break
            small = cv2.resize(frame, (160, 90), interpolation=cv2.INTER_AREA)
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            hist = cv2.calcHist([gray], [0], None, [32], [0, 256])
            cv2.normalize(hist, hist)
            if previous_hist is not None:
                distance = float(cv2.compareHist(
                    previous_hist, hist, cv2.HISTCMP_BHATTACHARYYA
                ))
                if distance >= threshold and frame_idx - last_cut >= min_gap_frames:
                    cuts.append(frame_idx)
                    last_cut = frame_idx
            previous_hist = hist
            frame_idx += 1
    finally:
        reader.release()
    return cuts


def extract_chapters(path: str) -> list[tuple[int, str]]:
    """Return chapter start frame indices and titles from the container."""
    if av is None:
        return []
    try:
        with av.open(path) as container:
            stream = next(iter(container.streams.video), None)
            fps = 30.0
            if stream is not None:
                rate = stream.average_rate or stream.base_rate
                if rate:
                    fps = float(rate)
            chapters = []
            seen = set()
            for index, chapter in enumerate(container.chapters, start=1):
                seconds = float(chapter.start * chapter.time_base)
                frame_idx = max(0, int(round(seconds * fps)))
                if frame_idx in seen:
                    continue
                seen.add(frame_idx)
                metadata = chapter.metadata or {}
                title = str(metadata.get("title") or f"Chapter {index}").strip()
                chapters.append((frame_idx, title))
            return chapters
    except Exception:
        return []


# ── Config ────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    defaults = {
        "recent": [],
        "last_output_dir": str(Path.home() / "Desktop"),
        "export_format": "PNG",
        "export_quality": 90,
        "export_scale": "100%",
        "export_group": "All",
        "burn_overlay": False,
        "crop_enabled": False,
        "crop_x": 0,
        "crop_y": 0,
        "crop_width": 1280,
        "crop_height": 720,
        "sheet_title": "",
        "sheet_watermark": "",
        "sheet_columns": 0,
        "sheet_pdf": False,
        "naming_template": DEFAULT_TEMPLATE,
        "show_overlay": True,
        "speed": "1x",
        "backend": "Auto",
        "hardware_accel": False,
        "seek_mode": "Exact frame",
        "proxy_enabled": False,
    }
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            defaults.update(data)
        except Exception:
            pass
    return defaults


def save_config(cfg: dict) -> None:
    try:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except Exception:
        pass


# ── Frame Cache ───────────────────────────────────────────────────────────────

class FrameCache:
    def __init__(self, maxsize: int = 40):
        self._cache: dict[int, np.ndarray] = {}
        self._order: list[int] = []
        self._maxsize = maxsize

    def get(self, idx: int) -> np.ndarray | None:
        return self._cache.get(idx)

    def put(self, idx: int, frame: np.ndarray) -> None:
        if idx in self._cache:
            self._order.remove(idx)
        elif len(self._order) >= self._maxsize:
            del self._cache[self._order.pop(0)]
        self._cache[idx] = frame
        self._order.append(idx)

    def clear(self) -> None:
        self._cache.clear()
        self._order.clear()


# ── Preview Thread ────────────────────────────────────────────────────────────

class PreviewThread(QThread):
    """Decodes single frames in background for hover-scrubber preview."""
    preview_ready = pyqtSignal(int, object)   # frame_idx, ndarray

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cap   = None
        self._mutex = QMutex()
        self._cond  = QWaitCondition()
        self._pending_frame: int = -1
        self._pending_path: str | None = None
        self._pending_backend = "Auto"
        self._pending_hardware = False
        self._pending_exact_seek = True
        self._running = True

    def open_video(self, path: str, backend: str = "Auto",
                   hardware_accel: bool = False,
                   exact_seek: bool = True) -> None:
        self._mutex.lock()
        self._pending_path = path
        self._pending_backend = backend
        self._pending_hardware = hardware_accel
        self._pending_exact_seek = exact_seek
        self._mutex.unlock()
        self._cond.wakeOne()

    def request(self, frame_idx: int) -> None:
        self._mutex.lock()
        self._pending_frame = frame_idx   # overwrites previous; only latest matters
        self._mutex.unlock()
        self._cond.wakeOne()

    def stop(self) -> None:
        self._mutex.lock()
        self._running = False
        self._mutex.unlock()
        self._cond.wakeOne()
        self.wait(3000)

    def run(self) -> None:
        while True:
            self._mutex.lock()
            while (self._running
                   and self._pending_frame < 0
                   and self._pending_path is None):
                self._cond.wait(self._mutex)
            if not self._running:
                self._mutex.unlock()
                break
            path  = self._pending_path
            idx   = self._pending_frame
            backend = self._pending_backend
            hardware_accel = self._pending_hardware
            exact_seek = self._pending_exact_seek
            self._pending_path  = None
            self._pending_frame = -1
            self._mutex.unlock()

            if path is not None:
                if self._cap:
                    self._cap.release()
                self._cap = open_cap(path, backend, hardware_accel, exact_seek)

            if idx >= 0 and self._cap and self._cap.isOpened():
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
                ret, frame = self._cap.read()
                if ret:
                    self.preview_ready.emit(idx, frame.copy())

        if self._cap:
            self._cap.release()


class WaveformThread(QThread):
    """Build an audio waveform without blocking playback or scrubbing."""
    waveform_ready = pyqtSignal(str, object, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mutex = QMutex()
        self._cond = QWaitCondition()
        self._pending_path: str | None = None
        self._running = True

    def request(self, path: str) -> None:
        self._mutex.lock()
        self._pending_path = path
        self._mutex.unlock()
        self._cond.wakeOne()

    def stop(self) -> None:
        self._mutex.lock()
        self._running = False
        self._mutex.unlock()
        self._cond.wakeOne()
        self.wait(3000)

    def run(self) -> None:
        while True:
            self._mutex.lock()
            while self._running and self._pending_path is None:
                self._cond.wait(self._mutex)
            if not self._running:
                self._mutex.unlock()
                break
            path = self._pending_path
            self._pending_path = None
            self._mutex.unlock()

            if path is not None:
                samples, duration = extract_audio_waveform(path)
                self.waveform_ready.emit(path, samples, duration)


class ProxyThread(QThread):
    """Generate one playback proxy at a time outside the GUI thread."""
    proxy_ready = pyqtSignal(str, str, int, int)
    proxy_failed = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mutex = QMutex()
        self._cond = QWaitCondition()
        self._pending: tuple[str, str, int] | None = None
        self._running = True

    def request(self, source_path: str, output_path: str,
                max_width: int = PROXY_MAX_WIDTH) -> None:
        self._mutex.lock()
        self._pending = (source_path, output_path, max_width)
        self._mutex.unlock()
        self._cond.wakeOne()

    def stop(self) -> None:
        self._mutex.lock()
        self._running = False
        self._mutex.unlock()
        self._cond.wakeOne()
        self.wait(3000)

    def run(self) -> None:
        while True:
            self._mutex.lock()
            while self._running and self._pending is None:
                self._cond.wait(self._mutex)
            if not self._running:
                self._mutex.unlock()
                break
            pending = self._pending
            self._pending = None
            self._mutex.unlock()

            if pending is None:
                continue
            source_path, output_path, max_width = pending
            try:
                width, height = build_video_proxy(
                    source_path, output_path, max_width
                )
                self.proxy_ready.emit(source_path, output_path, width, height)
            except Exception as exc:
                Path(output_path).with_name(
                    f".{Path(output_path).stem}.partial.mp4"
                ).unlink(missing_ok=True)
                self.proxy_failed.emit(source_path, str(exc))


class ThumbnailStripThread(QThread):
    """Decode evenly-spaced scrubber thumbnails away from the UI thread."""
    thumbnails_ready = pyqtSignal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mutex = QMutex()
        self._cond = QWaitCondition()
        self._pending: tuple[str, str, bool, bool] | None = None
        self._running = True

    def request(self, path: str, backend: str, hardware_accel: bool,
                exact_seek: bool) -> None:
        self._mutex.lock()
        self._pending = (path, backend, hardware_accel, exact_seek)
        self._mutex.unlock()
        self._cond.wakeOne()

    def stop(self) -> None:
        self._mutex.lock()
        self._running = False
        self._mutex.unlock()
        self._cond.wakeOne()
        self.wait(3000)

    def run(self) -> None:
        while True:
            self._mutex.lock()
            while self._running and self._pending is None:
                self._cond.wait(self._mutex)
            if not self._running:
                self._mutex.unlock()
                break
            pending = self._pending
            self._pending = None
            self._mutex.unlock()

            if pending is None:
                continue
            path, backend, hardware_accel, exact_seek = pending
            reader = open_cap(path, backend, hardware_accel, exact_seek)
            frames = []
            if reader is not None and reader.isOpened():
                try:
                    for idx in thumbnail_frame_indices(reader.frame_count):
                        reader.set(cv2.CAP_PROP_POS_FRAMES, idx)
                        ok, frame = reader.read()
                        if ok and frame is not None:
                            h, w = frame.shape[:2]
                            scale = min(1.0, 150 / max(1, w))
                            if scale < 1.0:
                                frame = cv2.resize(
                                    frame, (max(2, int(w * scale)),
                                            max(2, int(h * scale))),
                                    interpolation=cv2.INTER_AREA,
                                )
                            frames.append((idx, frame.copy()))
                finally:
                    reader.release()
            self.thumbnails_ready.emit(path, frames)


class SceneDetectThread(QThread):
    """Run histogram-based scene detection off the GUI thread."""
    scenes_ready = pyqtSignal(str, object)
    scenes_failed = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mutex = QMutex()
        self._cond = QWaitCondition()
        self._pending: tuple[str, str, bool, bool, float, int] | None = None
        self._running = True

    def request(self, path: str, backend: str, hardware_accel: bool,
                exact_seek: bool, threshold: float,
                min_gap_frames: int) -> None:
        self._mutex.lock()
        self._pending = (path, backend, hardware_accel, exact_seek,
                         threshold, min_gap_frames)
        self._mutex.unlock()
        self._cond.wakeOne()

    def stop(self) -> None:
        self._mutex.lock()
        self._running = False
        self._mutex.unlock()
        self._cond.wakeOne()
        self.wait(3000)

    def run(self) -> None:
        while True:
            self._mutex.lock()
            while self._running and self._pending is None:
                self._cond.wait(self._mutex)
            if not self._running:
                self._mutex.unlock()
                break
            pending = self._pending
            self._pending = None
            self._mutex.unlock()

            if pending is None:
                continue
            path, backend, hardware_accel, exact_seek, threshold, min_gap = pending
            try:
                cuts = detect_scene_cuts(
                    path, backend, hardware_accel, exact_seek,
                    threshold, min_gap,
                )
                self.scenes_ready.emit(path, cuts)
            except Exception as exc:
                self.scenes_failed.emit(path, str(exc))


# ── Mark Slider ───────────────────────────────────────────────────────────────

class MarkSlider(QSlider):
    """QSlider that paints mark ticks and emits hover frame index."""
    hovered_frame = pyqtSignal(int, QPoint)
    hover_left    = pyqtSignal()

    def __init__(self, orientation=Qt.Orientation.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self._marks: dict[int, str] = {}   # frame_idx -> color hex
        self.setMouseTracking(True)

    def set_marks(self, marks: dict[int, str]) -> None:
        self._marks = marks
        self.update()

    def _groove_rect(self) -> QRect:
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        return self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider, opt,
            QStyle.SubControl.SC_SliderGroove, self,
        )

    def _frame_to_x(self, idx: int) -> int:
        gr = self._groove_rect()
        pos = QStyle.sliderPositionFromValue(
            self.minimum(), self.maximum(), idx, gr.width()
        )
        return gr.x() + pos

    def _x_to_frame(self, x: int) -> int:
        gr = self._groove_rect()
        rel = max(0, min(x - gr.x(), gr.width()))
        return QStyle.sliderValueFromPosition(
            self.minimum(), self.maximum(), rel, gr.width()
        )

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        if self.maximum() > 0:
            self.hovered_frame.emit(
                self._x_to_frame(event.pos().x()),
                self.mapToGlobal(event.pos()),
            )

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.hover_left.emit()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._marks or self.maximum() <= 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        cy = self.height() // 2
        painter.setPen(Qt.PenStyle.NoPen)
        for idx, color_hex in self._marks.items():
            col = QColor(color_hex)
            col.setAlpha(215)
            painter.setBrush(col)
            x = self._frame_to_x(idx)
            painter.drawRoundedRect(x - 1, cy - 7, 3, 14, 1, 1)


class WaveformWidget(QWidget):
    """Compact RMS waveform aligned with the video timeline."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(46)
        self.setMaximumHeight(58)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._samples: list[float] = []
        self._duration = 0.0
        self._position = 0.0
        self._message = "Audio waveform loads after opening a video"

    def clear(self) -> None:
        self._samples = []
        self._duration = 0.0
        self._position = 0.0
        self._message = "Audio waveform loads after opening a video"
        self.update()

    def set_loading(self) -> None:
        self._samples = []
        self._duration = 0.0
        self._message = "Analyzing audio waveform..."
        self.update()

    def set_waveform(self, samples: list[float], duration: float) -> None:
        self._samples = samples
        self._duration = max(0.0, duration)
        self._message = "No audio track" if not samples else ""
        self.update()

    def set_position(self, seconds: float) -> None:
        if self._duration > 0:
            self._position = max(0.0, min(1.0, seconds / self._duration))
        else:
            self._position = 0.0
        self.update()

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(MANTLE))
        painter.setPen(QColor(SURFACE0))
        painter.drawLine(0, self.height() // 2, self.width(), self.height() // 2)

        if not self._samples:
            painter.setPen(QColor(OVERLAY0))
            painter.setFont(QFont("Segoe UI", 10))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._message)
            return

        center = self.height() // 2
        amplitude = max(4, (self.height() - 10) // 2)
        left = 5
        width = max(1, self.width() - left * 2)
        painter.setPen(QColor(TEAL))
        for x in range(width):
            sample_index = min(len(self._samples) - 1,
                               int(x / width * len(self._samples)))
            level = max(0.0, min(1.0, float(self._samples[sample_index])))
            half = max(1, int(level * amplitude))
            px = left + x
            painter.drawLine(px, center - half, px, center + half)

        position_x = left + int(self._position * width)
        painter.setPen(QColor(MAUVE))
        painter.drawLine(position_x, 2, position_x, self.height() - 3)


class ThumbnailStripWidget(QWidget):
    """A clickable strip of evenly-spaced frame thumbnails."""
    frame_clicked = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(60)
        self.setMaximumHeight(78)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._frames: list[tuple[int, QPixmap]] = []
        self._message = "Thumbnail strip loads after opening a video"

    def set_loading(self) -> None:
        self._frames = []
        self._message = "Building thumbnail strip..."
        self.update()

    def set_frames(self, frames) -> None:
        self._frames = [
            (idx, bgr_to_pixmap(frame)) for idx, frame in frames
        ]
        self._message = "No video frames available" if not self._frames else ""
        self.update()

    def paintEvent(self, event):
        del event
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(CRUST))
        if not self._frames:
            painter.setPen(QColor(OVERLAY0))
            painter.setFont(QFont("Segoe UI", 10))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._message)
            return

        tile_width = max(1, self.width() // len(self._frames))
        for pos, (_, pixmap) in enumerate(self._frames):
            tile = QRect(pos * tile_width, 3, tile_width, self.height() - 6)
            painter.drawPixmap(
                tile,
                pixmap.scaled(tile.size(), Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation),
            )
            if pos:
                painter.setPen(QColor(SURFACE0))
                painter.drawLine(tile.left(), tile.top(), tile.left(), tile.bottom())

    def mousePressEvent(self, event):
        if self._frames and event.button() == Qt.MouseButton.LeftButton:
            tile_width = max(1, self.width() // len(self._frames))
            pos = max(0, min(len(self._frames) - 1, event.position().x() // tile_width))
            self.frame_clicked.emit(self._frames[int(pos)][0])
        super().mousePressEvent(event)


# ── Video Display ─────────────────────────────────────────────────────────────

class VideoDisplay(QLabel):
    wheel_delta  = pyqtSignal(int)
    file_dropped = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(640, 360)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAcceptDrops(True)
        self._bgr: np.ndarray | None = None
        self._overlay_text = ""
        self._show_overlay = True
        self._placeholder()

    def _placeholder(self):
        self.setStyleSheet(
            f"background-color: {CRUST}; border-radius: 10px; "
            f"color: {SUBTEXT0}; font-size: 16px;"
        )
        self.setText("Open a video file or drop one here")

    def show_frame(self, bgr: np.ndarray):
        self._bgr = bgr
        self.setStyleSheet(f"background-color: {CRUST}; border-radius: 10px;")
        self._refresh()

    def set_overlay(self, text: str):
        self._overlay_text = text
        self.update()

    def set_show_overlay(self, val: bool):
        self._show_overlay = val
        self.update()

    def _refresh(self):
        if self._bgr is None:
            return
        self.setPixmap(
            bgr_to_pixmap(self._bgr).scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refresh()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._show_overlay or not self._overlay_text or self._bgr is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(QFont("Consolas", 10))
        fm  = painter.fontMetrics()
        tw  = fm.horizontalAdvance(self._overlay_text)
        th  = fm.height()
        pad, mg = 6, 8
        rx = self.width()  - tw - mg - pad * 2
        ry = self.height() - th - mg - pad * 2
        bg = QColor(CRUST)
        bg.setAlpha(185)
        painter.setBrush(bg)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rx, ry, tw + pad * 2, th + pad * 2, 4, 4)
        painter.setPen(QColor(MAUVE))
        painter.drawText(rx + pad, ry + pad + fm.ascent(), self._overlay_text)

    def wheelEvent(self, event):
        d = event.angleDelta().y()
        if d > 0:
            self.wheel_delta.emit(-1)
        elif d < 0:
            self.wheel_delta.emit(1)

    def dragEnterEvent(self, event: QDragEnterEvent):
        # Accept any file — let cv2 decide if it's valid
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if urls:
            self.file_dropped.emit(urls[0].toLocalFile())


# ── Frame Item Widget ─────────────────────────────────────────────────────────

class FrameItemWidget(QWidget):
    remove_requested = pyqtSignal(int)
    jump_requested   = pyqtSignal(int)

    def __init__(self, frame_idx: int, fps: float,
                 thumb: QPixmap | None, label: str = "",
                 color: str = MAUVE, tags: str = "", comment: str = "",
                 parent=None):
        super().__init__(parent)
        self.frame_idx = frame_idx
        self.fps       = fps
        self.setFixedHeight(90)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 6, 0)
        root.setSpacing(0)

        # Color bar
        self._color_bar = QFrame()
        self._color_bar.setFixedWidth(4)
        root.addWidget(self._color_bar)

        inner = QHBoxLayout()
        inner.setContentsMargins(8, 4, 0, 4)
        inner.setSpacing(10)
        root.addLayout(inner)

        # Thumbnail
        thumb_lbl = QLabel()
        thumb_lbl.setFixedSize(96, 54)
        thumb_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb_lbl.setStyleSheet(
            f"border: 1px solid {SURFACE1}; border-radius: 4px; background: {CRUST};"
        )
        if thumb:
            thumb_lbl.setPixmap(thumb)
        inner.addWidget(thumb_lbl)

        # Info
        info = QVBoxLayout()
        info.setSpacing(1)
        ms = frame_to_ms(frame_idx, fps)
        self._ts_lbl    = QLabel(ms_to_ts(ms))
        self._ts_lbl.setStyleSheet(f"color: {TEXT}; font-weight: bold; font-size: 13px;")
        self._frame_lbl = QLabel(f"Frame {frame_idx:,}")
        self._frame_lbl.setStyleSheet(f"color: {SUBTEXT0}; font-size: 11px;")
        self._label_lbl = QLabel(label)
        self._label_lbl.setStyleSheet(f"color: {PEACH}; font-size: 11px; font-style: italic;")
        self._label_lbl.setVisible(bool(label))
        self._tags_lbl = QLabel()
        self._tags_lbl.setStyleSheet(f"color: {TEAL}; font-size: 10px;")
        self._comment_lbl = QLabel()
        self._comment_lbl.setStyleSheet(f"color: {SUBTEXT0}; font-size: 10px;")
        self._comment_lbl.setToolTip(comment)
        info.addWidget(self._ts_lbl)
        info.addWidget(self._frame_lbl)
        info.addWidget(self._label_lbl)
        info.addWidget(self._tags_lbl)
        info.addWidget(self._comment_lbl)
        inner.addLayout(info)
        inner.addStretch()

        jump_btn = QPushButton("Go")
        jump_btn.setFixedSize(36, 28)
        jump_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {BLUE}; color: {CRUST};
                border: none; border-radius: 5px; font-size: 11px; font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {LAVENDER}; }}
        """)
        jump_btn.clicked.connect(lambda: self.jump_requested.emit(self.frame_idx))

        del_btn = QPushButton("x")
        del_btn.setFixedSize(28, 28)
        del_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {SURFACE0}; color: {RED};
                border: 1px solid {SURFACE1}; border-radius: 14px;
                font-size: 12px; font-weight: bold;
            }}
            QPushButton:hover {{ background-color: {RED}; color: {CRUST}; border-color: {RED}; }}
        """)
        del_btn.clicked.connect(lambda: self.remove_requested.emit(self.frame_idx))

        inner.addWidget(jump_btn)
        inner.addWidget(del_btn)

        self.set_color(color)
        self.update_tags(tags)
        self.update_comment(comment)

    def set_color(self, color_hex: str):
        self._color_bar.setStyleSheet(
            f"background: {color_hex}; border-radius: 2px;"
        )

    def update_label(self, label: str):
        self._label_lbl.setText(label)
        self._label_lbl.setVisible(bool(label))

    def update_tags(self, tags: str):
        self._tags_lbl.setText("  ".join(f"#{tag}" for tag in parse_tags(tags)))
        self._tags_lbl.setVisible(bool(tags.strip()))

    def update_comment(self, comment: str):
        self._comment_lbl.setText(comment.strip())
        self._comment_lbl.setToolTip(comment.strip())
        self._comment_lbl.setVisible(bool(comment.strip()))


# ── Main Window ───────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FrameSnap v2.1.0")
        self.setMinimumSize(1100, 680)
        self.resize(1380, 860)
        self.setAcceptDrops(True)

        self._cfg = load_config()
        self._backend = self._cfg.get("backend", "Auto")
        if self._backend not in BACKEND_OPTIONS:
            self._backend = "Auto"
        self._hardware_accel = bool(self._cfg.get("hardware_accel", False))
        self._seek_mode = self._cfg.get("seek_mode", "Exact frame")
        if self._seek_mode not in SEEK_OPTIONS:
            self._seek_mode = "Exact frame"
        self._proxy_enabled = bool(self._cfg.get("proxy_enabled", False))

        # Video state
        self.cap: VideoReader | None = None
        self._video_path = ""
        self._playback_path = ""
        self.total_frames = 0       # 0 means unknown
        self.fps          = 30.0
        self.current_frame = 0
        self.is_playing   = False
        self._loop_mode   = False
        self._speed       = 1.0
        self._slider_held = False
        self._last_bgr: np.ndarray | None = None
        self._cache = FrameCache(40)

        # Marks: frame_idx -> {item, widget, label, color}
        self.marked: dict[int, dict] = {}

        self._preview_thread = PreviewThread(self)
        self._preview_thread.preview_ready.connect(self._on_preview_ready)
        self._preview_thread.start()
        self._waveform_thread = WaveformThread(self)
        self._waveform_thread.waveform_ready.connect(self._on_waveform_ready)
        self._waveform_thread.start()
        self._proxy_thread = ProxyThread(self)
        self._proxy_thread.proxy_ready.connect(self._on_proxy_ready)
        self._proxy_thread.proxy_failed.connect(self._on_proxy_failed)
        self._proxy_thread.start()
        self._thumbnail_thread = ThumbnailStripThread(self)
        self._thumbnail_thread.thumbnails_ready.connect(self._on_thumbnails_ready)
        self._thumbnail_thread.start()
        self._scene_thread = SceneDetectThread(self)
        self._scene_thread.scenes_ready.connect(self._on_scenes_ready)
        self._scene_thread.scenes_failed.connect(self._on_scenes_failed)
        self._scene_thread.start()
        self._pending_hover_pos = QPoint()

        self._build_menu()
        self._build_ui()
        self._build_timer()
        self._build_hover_popup()
        self._apply_config()

    # ── Menu ──────────────────────────────────────────────────────────────────

    def _build_menu(self):
        mb = self.menuBar()

        file_menu = mb.addMenu("File")
        self._recent_menu = QMenu("Recent Files", self)
        file_menu.addAction(self._make_act("Open Video...", self.open_video))
        file_menu.addSeparator()
        file_menu.addMenu(self._recent_menu)
        file_menu.addSeparator()
        file_menu.addAction(self._make_act("Save Session...", self.save_session))
        file_menu.addAction(self._make_act("Load Session...", self.load_session))
        file_menu.addSeparator()
        file_menu.addAction(self._make_act("Exit", self.close))

        edit_menu = mb.addMenu("Edit")
        edit_menu.addAction(self._make_act("Mark Current Frame", self.mark_frame))
        edit_menu.addAction(self._make_act("Auto-mark Scene Cuts", self.auto_mark_scenes))
        edit_menu.addAction(self._make_act("Auto-mark Chapters", self.auto_mark_chapters))
        edit_menu.addAction(self._make_act("Clear All Marks",    self.clear_marks))
        edit_menu.addSeparator()
        edit_menu.addAction(self._make_act("Copy Current Frame to Clipboard",
                                            self.copy_frame_clipboard))

        view_menu = mb.addMenu("View")
        self._act_overlay = self._make_act("Frame Overlay", self._toggle_overlay,
                                            checkable=True,
                                            checked=self._cfg.get("show_overlay", True))
        view_menu.addAction(self._act_overlay)

        self._refresh_recent_menu()

    def _make_act(self, label: str, slot, checkable=False, checked=False) -> QAction:
        act = QAction(label, self)
        if checkable:
            act.setCheckable(True)
            act.setChecked(checked)
            act.triggered.connect(slot)
        else:
            act.triggered.connect(slot)
        return act

    def _refresh_recent_menu(self):
        self._recent_menu.clear()
        recents = self._cfg.get("recent", [])
        if not recents:
            no_act = QAction("(none)", self)
            no_act.setEnabled(False)
            self._recent_menu.addAction(no_act)
            return
        for path in recents:
            act = QAction(Path(path).name, self)
            act.setToolTip(path)
            act.triggered.connect(lambda _, p=path: self._open_path(p))
            self._recent_menu.addAction(act)

    def _push_recent(self, path: str):
        recents = self._cfg.get("recent", [])
        if path in recents:
            recents.remove(path)
        recents.insert(0, path)
        self._cfg["recent"] = recents[:MAX_RECENT]
        save_config(self._cfg)
        self._refresh_recent_menu()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        # ── Left ──────────────────────────────────────────────────────────────
        left_w = QWidget()
        left   = QVBoxLayout(left_w)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(8)

        top_bar = QHBoxLayout()
        open_btn = QPushButton("Open Video...")
        open_btn.setFixedHeight(34)
        open_btn.clicked.connect(self.open_video)
        self._file_lbl = QLabel("No file loaded")
        self._file_lbl.setStyleSheet(f"color: {SUBTEXT0}; font-size: 12px;")
        top_bar.addWidget(open_btn)
        top_bar.addWidget(self._file_lbl, 1)
        top_bar.addWidget(QLabel("Decoder:"))
        self._backend_combo = QComboBox()
        self._backend_combo.addItems(BACKEND_OPTIONS)
        self._backend_combo.setFixedHeight(30)
        self._backend_combo.setToolTip(
            "Auto prefers PyAV when installed; OpenCV uses its FFmpeg wrapper."
        )
        self._backend_combo.currentTextChanged.connect(self._backend_changed)
        top_bar.addWidget(self._backend_combo)
        self._hardware_check = QCheckBox("HW")
        self._hardware_check.setFixedHeight(30)
        self._hardware_check.setToolTip(
            "Request platform hardware decode through PyAV when available."
        )
        self._hardware_check.setEnabled(av is not None)
        self._hardware_check.toggled.connect(self._hardware_toggled)
        top_bar.addWidget(self._hardware_check)
        top_bar.addWidget(QLabel("Seek:"))
        self._seek_combo = QComboBox()
        self._seek_combo.addItems(SEEK_OPTIONS)
        self._seek_combo.setFixedHeight(30)
        self._seek_combo.setToolTip(
            "Exact frame decodes forward from a keyframe; Fast keyframe returns sooner."
        )
        self._seek_combo.currentTextChanged.connect(self._seek_changed)
        top_bar.addWidget(self._seek_combo)
        self._proxy_check = QCheckBox("Proxy")
        self._proxy_check.setFixedHeight(30)
        self._proxy_check.setToolTip(
            "Generate a cached 1280px playback proxy for videos over 1 GB."
        )
        self._proxy_check.toggled.connect(self._proxy_toggled)
        top_bar.addWidget(self._proxy_check)
        left.addLayout(top_bar)

        self._info_bar = QLabel("")
        self._info_bar.setStyleSheet(f"color: {OVERLAY0}; font-size: 11px; padding: 2px 0;")
        self._info_bar.hide()
        left.addWidget(self._info_bar)

        self.display = VideoDisplay()
        self.display.wheel_delta.connect(self.step)
        self.display.file_dropped.connect(self._open_path)
        left.addWidget(self.display, 1)

        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        left.addWidget(div)

        # Scrubber
        scrub = QHBoxLayout()
        self._pos_lbl = QLabel("00:00:00.000")
        self._pos_lbl.setStyleSheet(
            f"color: {MAUVE}; font-family: Consolas, monospace; "
            f"font-size: 13px; min-width: 105px;"
        )
        self.slider = MarkSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.sliderPressed.connect(self._slider_press)
        self.slider.sliderReleased.connect(self._slider_release)
        self.slider.valueChanged.connect(self._slider_changed)
        self.slider.hovered_frame.connect(self._slider_hovered)
        self.slider.hover_left.connect(self._slider_hover_left)
        self._dur_lbl = QLabel("00:00:00.000")
        self._dur_lbl.setStyleSheet(
            f"color: {SUBTEXT0}; font-family: Consolas, monospace; "
            f"font-size: 13px; min-width: 105px;"
        )
        self._dur_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        scrub.addWidget(self._pos_lbl)
        scrub.addWidget(self.slider, 1)
        scrub.addWidget(self._dur_lbl)
        left.addLayout(scrub)
        self._waveform = WaveformWidget()
        left.addWidget(self._waveform)
        self._thumbnail_strip = ThumbnailStripWidget()
        self._thumbnail_strip.frame_clicked.connect(self._jump_to_thumbnail)
        left.addWidget(self._thumbnail_strip)

        # Controls
        ctrl = QHBoxLayout()
        ctrl.setSpacing(6)

        self._btn_p10  = QPushButton("-10")
        self._btn_p1   = QPushButton("-1")
        self._btn_play = QPushButton("Play")
        self._btn_n1   = QPushButton("+1")
        self._btn_n10  = QPushButton("+10")
        for b in (self._btn_p10, self._btn_p1, self._btn_play, self._btn_n1, self._btn_n10):
            b.setEnabled(False)
            b.setFixedHeight(32)
            ctrl.addWidget(b)
        self._btn_p10.clicked.connect(lambda: self.step(-10))
        self._btn_p1.clicked.connect(lambda: self.step(-1))
        self._btn_play.clicked.connect(self.toggle_play)
        self._btn_n1.clicked.connect(lambda: self.step(1))
        self._btn_n10.clicked.connect(lambda: self.step(10))

        # Speed combo
        self._speed_combo = QComboBox()
        self._speed_combo.addItems(["0.25x", "0.5x", "1x", "2x", "4x"])
        self._speed_combo.setCurrentText("1x")
        self._speed_combo.setFixedHeight(32)
        self._speed_combo.currentTextChanged.connect(self._speed_changed)
        ctrl.addWidget(self._speed_combo)

        # Loop button
        self._loop_btn = QPushButton("Loop")
        self._loop_btn.setObjectName("loopBtn")
        self._loop_btn.setFixedHeight(32)
        self._loop_btn.setCheckable(True)
        self._loop_btn.toggled.connect(self._loop_toggled)
        ctrl.addWidget(self._loop_btn)

        ctrl.addStretch()

        self._btn_prev_mark = QPushButton("< Prev")
        self._btn_prev_mark.setEnabled(False)
        self._btn_prev_mark.setFixedHeight(32)
        self._btn_prev_mark.clicked.connect(self.jump_prev_mark)

        self._btn_next_mark = QPushButton("Next >")
        self._btn_next_mark.setEnabled(False)
        self._btn_next_mark.setFixedHeight(32)
        self._btn_next_mark.clicked.connect(self.jump_next_mark)

        self._copy_btn = QPushButton("Copy Frame")
        self._copy_btn.setObjectName("copyBtn")
        self._copy_btn.setEnabled(False)
        self._copy_btn.setFixedHeight(38)
        self._copy_btn.clicked.connect(self.copy_frame_clipboard)

        self._mark_btn = QPushButton("Mark Frame")
        self._mark_btn.setObjectName("markBtn")
        self._mark_btn.setEnabled(False)
        self._mark_btn.setFixedHeight(38)
        self._mark_btn.clicked.connect(self.mark_frame)

        ctrl.addWidget(self._btn_prev_mark)
        ctrl.addWidget(self._btn_next_mark)
        ctrl.addSpacing(8)
        ctrl.addWidget(self._copy_btn)
        ctrl.addWidget(self._mark_btn)
        left.addLayout(ctrl)

        # ── Right ─────────────────────────────────────────────────────────────
        right_w = QWidget()
        right_w.setMinimumWidth(320)
        right_w.setMaximumWidth(430)
        right = QVBoxLayout(right_w)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)

        self._tabs = QTabWidget()
        right.addWidget(self._tabs)

        # Tab 1: Marks
        marks_tab = QWidget()
        ml = QVBoxLayout(marks_tab)
        ml.setContentsMargins(8, 8, 8, 8)
        ml.setSpacing(6)

        self._marks_list = QListWidget()
        self._marks_list.setSpacing(2)
        self._marks_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._marks_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._marks_list.customContextMenuRequested.connect(self._marks_context_menu)
        self._marks_list.itemDoubleClicked.connect(
            lambda item: self._jump_to(item.data(Qt.ItemDataRole.UserRole))
        )
        ml.addWidget(self._marks_list, 1)

        nav_row = QHBoxLayout()
        self._count_lbl = QLabel("0 frames marked")
        self._count_lbl.setStyleSheet(f"color: {SUBTEXT0}; font-size: 11px;")
        sel_all = QPushButton("All")
        sel_all.setFixedHeight(28)
        sel_all.clicked.connect(self._marks_list.selectAll)
        self._del_sel_btn = QPushButton("Del Sel")
        self._del_sel_btn.setObjectName("dangerBtn")
        self._del_sel_btn.setFixedHeight(28)
        self._del_sel_btn.setEnabled(False)
        self._del_sel_btn.clicked.connect(self._delete_selected)
        self._clear_btn = QPushButton("Clear All")
        self._clear_btn.setObjectName("dangerBtn")
        self._clear_btn.setFixedHeight(28)
        self._clear_btn.setEnabled(False)
        self._clear_btn.clicked.connect(self.clear_marks)
        nav_row.addWidget(self._count_lbl)
        nav_row.addStretch()
        nav_row.addWidget(sel_all)
        nav_row.addWidget(self._del_sel_btn)
        nav_row.addWidget(self._clear_btn)
        ml.addLayout(nav_row)
        self._tabs.addTab(marks_tab, "Marks (0)")

        # Tab 2: Export
        export_tab = QWidget()
        el = QVBoxLayout(export_tab)
        el.setContentsMargins(10, 10, 10, 10)
        el.setSpacing(10)

        # Format
        fmt_g = QGroupBox("Format")
        fi = QVBoxLayout(fmt_g)
        fi.setSpacing(6)
        fmt_row = QHBoxLayout()
        fmt_row.addWidget(QLabel("Format:"))
        self._fmt_combo = QComboBox()
        self._fmt_combo.addItems([
            "PNG", "JPEG", "WebP", "TIFF", "TIFF 16-bit", "BMP",
            "GIF", "WebP Animation", "AVIF", "EXR",
        ])
        self._fmt_combo.currentTextChanged.connect(self._fmt_changed)
        fmt_row.addWidget(self._fmt_combo)
        fmt_row.addStretch()
        fi.addLayout(fmt_row)
        qual_row = QHBoxLayout()
        self._qual_lbl_l = QLabel("Quality:")
        self._qual_spin  = QSpinBox()
        self._qual_spin.setRange(1, 100)
        self._qual_spin.setValue(90)
        self._qual_spin.setSuffix("%")
        self._qual_spin.setFixedWidth(75)
        self._qual_lbl_l.setEnabled(False)
        self._qual_spin.setEnabled(False)
        qual_row.addWidget(self._qual_lbl_l)
        qual_row.addWidget(self._qual_spin)
        qual_row.addStretch()
        fi.addLayout(qual_row)
        el.addWidget(fmt_g)

        group_g = QGroupBox("Export Group")
        gi = QHBoxLayout(group_g)
        gi.addWidget(QLabel("Group:"))
        self._group_combo = QComboBox()
        self._group_combo.addItem("All")
        self._group_combo.setToolTip("Export only marks carrying the selected tag.")
        self._group_combo.currentTextChanged.connect(self._group_changed)
        gi.addWidget(self._group_combo, 1)
        el.addWidget(group_g)

        transform_g = QGroupBox("Export Transforms")
        ti = QVBoxLayout(transform_g)
        self._burn_check = QCheckBox("Burn timestamp, frame, and label")
        ti.addWidget(self._burn_check)
        crop_row = QHBoxLayout()
        self._crop_check = QCheckBox("Crop")
        crop_row.addWidget(self._crop_check)
        crop_row.addWidget(QLabel("X"))
        self._crop_x = QSpinBox()
        self._crop_x.setRange(0, 100000)
        crop_row.addWidget(self._crop_x)
        crop_row.addWidget(QLabel("Y"))
        self._crop_y = QSpinBox()
        self._crop_y.setRange(0, 100000)
        crop_row.addWidget(self._crop_y)
        crop_row.addWidget(QLabel("W"))
        self._crop_w = QSpinBox()
        self._crop_w.setRange(1, 100000)
        crop_row.addWidget(self._crop_w)
        crop_row.addWidget(QLabel("H"))
        self._crop_h = QSpinBox()
        self._crop_h.setRange(1, 100000)
        crop_row.addWidget(self._crop_h)
        ti.addLayout(crop_row)
        el.addWidget(transform_g)

        sheet_g = QGroupBox("Contact Sheet")
        si2 = QVBoxLayout(sheet_g)
        title_row = QHBoxLayout()
        title_row.addWidget(QLabel("Title:"))
        self._sheet_title = QLineEdit()
        self._sheet_title.setPlaceholderText("Optional sheet title")
        title_row.addWidget(self._sheet_title, 1)
        si2.addLayout(title_row)
        watermark_row = QHBoxLayout()
        watermark_row.addWidget(QLabel("Watermark:"))
        self._sheet_watermark = QLineEdit()
        self._sheet_watermark.setPlaceholderText("Optional watermark")
        watermark_row.addWidget(self._sheet_watermark, 1)
        si2.addLayout(watermark_row)
        sheet_options = QHBoxLayout()
        sheet_options.addWidget(QLabel("Columns:"))
        self._sheet_columns = QSpinBox()
        self._sheet_columns.setRange(0, 6)
        self._sheet_columns.setSpecialValueText("Auto")
        sheet_options.addWidget(self._sheet_columns)
        self._sheet_pdf = QCheckBox("Also save PDF")
        sheet_options.addWidget(self._sheet_pdf)
        sheet_options.addStretch()
        si2.addLayout(sheet_options)
        el.addWidget(sheet_g)

        # Scale
        scale_g = QGroupBox("Scale")
        si = QVBoxLayout(scale_g)
        si.setSpacing(6)
        scale_row = QHBoxLayout()
        scale_row.addWidget(QLabel("Scale:"))
        self._scale_combo = QComboBox()
        self._scale_combo.addItems(["100%", "75%", "50%", "25%", "Custom"])
        self._scale_combo.currentTextChanged.connect(self._scale_changed)
        scale_row.addWidget(self._scale_combo)
        scale_row.addStretch()
        si.addLayout(scale_row)
        cust_row = QHBoxLayout()
        self._cust_lbl  = QLabel("Width px:")
        self._cust_spin = QSpinBox()
        self._cust_spin.setRange(1, 7680)
        self._cust_spin.setValue(1280)
        self._cust_spin.setSingleStep(10)
        self._cust_lbl.setVisible(False)
        self._cust_spin.setVisible(False)
        cust_row.addWidget(self._cust_lbl)
        cust_row.addWidget(self._cust_spin)
        cust_row.addStretch()
        si.addLayout(cust_row)
        el.addWidget(scale_g)

        # Naming
        name_g = QGroupBox("Filename Template")
        ni = QVBoxLayout(name_g)
        ni.setSpacing(4)
        self._name_edit = QLineEdit(DEFAULT_TEMPLATE)
        self._name_edit.setPlaceholderText("{stem}_{frame}_{ts}")
        ni.addWidget(self._name_edit)
        hint = QLabel("Variables: {stem}  {frame}  {ts}  {label}  {n}")
        hint.setStyleSheet(f"color: {OVERLAY0}; font-size: 10px;")
        ni.addWidget(hint)
        el.addWidget(name_g)

        # Output
        out_g = QGroupBox("Output Folder")
        oi = QVBoxLayout(out_g)
        oi.setSpacing(6)
        dir_row = QHBoxLayout()
        self._dir_edit = QLineEdit(self._cfg.get("last_output_dir", ""))
        browse_btn = QPushButton("Browse...")
        browse_btn.setFixedHeight(30)
        browse_btn.clicked.connect(self.browse_dir)
        dir_row.addWidget(self._dir_edit, 1)
        dir_row.addWidget(browse_btn)
        oi.addLayout(dir_row)

        export_row = QHBoxLayout()
        self._export_btn = QPushButton("Export All Frames")
        self._export_btn.setObjectName("exportBtn")
        self._export_btn.setEnabled(False)
        self._export_btn.setFixedHeight(38)
        self._export_btn.clicked.connect(self.export_frames)
        self._open_dir_btn = QPushButton("Open Folder")
        self._open_dir_btn.setFixedHeight(38)
        self._open_dir_btn.clicked.connect(self.open_export_dir)
        export_row.addWidget(self._export_btn, 1)
        export_row.addWidget(self._open_dir_btn)
        oi.addLayout(export_row)

        self._sheet_btn = QPushButton("Contact Sheet...")
        self._sheet_btn.setObjectName("sheetBtn")
        self._sheet_btn.setEnabled(False)
        self._sheet_btn.setFixedHeight(34)
        self._sheet_btn.clicked.connect(self.export_contact_sheet)
        oi.addWidget(self._sheet_btn)
        self._ffmpeg_btn = QPushButton("FFmpeg Commands...")
        self._ffmpeg_btn.setFixedHeight(30)
        self._ffmpeg_btn.clicked.connect(self.show_ffmpeg_commands)
        oi.addWidget(self._ffmpeg_btn)
        el.addWidget(out_g)

        self._status_lbl = QLabel("")
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_lbl.setStyleSheet(f"color: {GREEN}; font-size: 12px;")
        self._status_lbl.setWordWrap(True)
        el.addWidget(self._status_lbl)
        el.addStretch()
        self._tabs.addTab(export_tab, "Export")

        splitter.addWidget(left_w)
        splitter.addWidget(right_w)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter)

    def _build_timer(self):
        self._timer = QTimer()
        self._timer.timeout.connect(self._advance)

    def _build_hover_popup(self):
        self._hover_popup = QWidget(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self._hover_popup.setFixedSize(192, 130)
        self._hover_popup.setStyleSheet(
            f"background: {CRUST}; border: 1px solid {SURFACE1}; border-radius: 6px;"
        )
        pl = QVBoxLayout(self._hover_popup)
        pl.setContentsMargins(4, 4, 4, 4)
        pl.setSpacing(3)
        self._hover_thumb_lbl = QLabel()
        self._hover_thumb_lbl.setFixedSize(184, 104)
        self._hover_thumb_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hover_thumb_lbl.setStyleSheet(f"background: {MANTLE}; border-radius: 4px;")
        self._hover_ts_lbl = QLabel("")
        self._hover_ts_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hover_ts_lbl.setStyleSheet(
            f"color: {MAUVE}; font-family: Consolas, monospace; font-size: 11px;"
        )
        pl.addWidget(self._hover_thumb_lbl)
        pl.addWidget(self._hover_ts_lbl)
        self._hover_popup.hide()

    def _apply_config(self):
        cfg = self._cfg
        self._fmt_combo.setCurrentText(cfg.get("export_format", "PNG"))
        self._qual_spin.setValue(cfg.get("export_quality", 90))
        self._scale_combo.setCurrentText(cfg.get("export_scale", "100%"))
        self._group_combo.setCurrentText(cfg.get("export_group", "All"))
        self._burn_check.setChecked(cfg.get("burn_overlay", False))
        self._crop_check.setChecked(cfg.get("crop_enabled", False))
        self._crop_x.setValue(cfg.get("crop_x", 0))
        self._crop_y.setValue(cfg.get("crop_y", 0))
        self._crop_w.setValue(cfg.get("crop_width", 1280))
        self._crop_h.setValue(cfg.get("crop_height", 720))
        self._sheet_title.setText(cfg.get("sheet_title", ""))
        self._sheet_watermark.setText(cfg.get("sheet_watermark", ""))
        self._sheet_columns.setValue(cfg.get("sheet_columns", 0))
        self._sheet_pdf.setChecked(cfg.get("sheet_pdf", False))
        self._name_edit.setText(cfg.get("naming_template", DEFAULT_TEMPLATE))
        self._speed_combo.setCurrentText(cfg.get("speed", "1x"))
        self._backend_combo.blockSignals(True)
        self._backend_combo.setCurrentText(self._backend)
        self._backend_combo.blockSignals(False)
        self._hardware_check.blockSignals(True)
        self._hardware_check.setChecked(self._hardware_accel)
        self._hardware_check.blockSignals(False)
        self._seek_combo.blockSignals(True)
        self._seek_combo.setCurrentText(self._seek_mode)
        self._seek_combo.blockSignals(False)
        self._proxy_check.blockSignals(True)
        self._proxy_check.setChecked(self._proxy_enabled)
        self._proxy_check.blockSignals(False)
        overlay_on = cfg.get("show_overlay", True)
        self._act_overlay.setChecked(overlay_on)
        self.display.set_show_overlay(overlay_on)

    def _backend_changed(self, backend: str):
        if backend not in BACKEND_OPTIONS:
            return
        previous = self._backend
        self._backend = backend
        self._cfg["backend"] = backend
        save_config(self._cfg)
        if self._video_path and self.cap:
            if not self._open_path(self._video_path,
                                   start_frame=self.current_frame,
                                   preserve_marks=True,
                                   record_recent=False):
                self._backend = previous
                self._cfg["backend"] = previous
                save_config(self._cfg)
                self._backend_combo.blockSignals(True)
                self._backend_combo.setCurrentText(previous)
                self._backend_combo.blockSignals(False)
            else:
                self._set_status(f"Decoder: {self.cap.backend_name}", BLUE)

    def _hardware_toggled(self, enabled: bool):
        previous = self._hardware_accel
        self._hardware_accel = enabled
        self._cfg["hardware_accel"] = enabled
        save_config(self._cfg)
        if self._video_path and self.cap:
            if not self._open_path(self._video_path,
                                   start_frame=self.current_frame,
                                   preserve_marks=True,
                                   record_recent=False):
                self._hardware_accel = previous
                self._cfg["hardware_accel"] = previous
                save_config(self._cfg)
                self._hardware_check.blockSignals(True)
                self._hardware_check.setChecked(previous)
                self._hardware_check.blockSignals(False)
            else:
                self._set_status(f"Decoder: {self.cap.backend_name}", BLUE)

    def _seek_changed(self, mode: str):
        if mode not in SEEK_OPTIONS:
            return
        previous = self._seek_mode
        self._seek_mode = mode
        self._cfg["seek_mode"] = mode
        save_config(self._cfg)
        if self._video_path and self.cap:
            if not self._open_path(self._video_path,
                                   start_frame=self.current_frame,
                                   preserve_marks=True,
                                   record_recent=False):
                self._seek_mode = previous
                self._cfg["seek_mode"] = previous
                save_config(self._cfg)
                self._seek_combo.blockSignals(True)
                self._seek_combo.setCurrentText(previous)
                self._seek_combo.blockSignals(False)
            else:
                self._set_status(f"Seek mode: {self._seek_mode}", BLUE)

    def _proxy_toggled(self, enabled: bool):
        self._proxy_enabled = enabled
        self._cfg["proxy_enabled"] = enabled
        save_config(self._cfg)
        if self._video_path and self.cap:
            self._open_path(self._video_path,
                            start_frame=self.current_frame,
                            preserve_marks=True,
                            record_recent=False)

    # ── Video loading ─────────────────────────────────────────────────────────

    def open_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Video", "", VIDEO_FILTER
        )
        if path:
            self._open_path(path)

    def _open_path(self, path: str, start_frame: int = 0,
                   preserve_marks: bool = False,
                   record_recent: bool = True) -> bool:
        if not os.path.isfile(path):
            QMessageBox.warning(self, "Not Found", f"File not found:\n{path}")
            return False

        cap = open_cap(
            path, self._backend, self._hardware_accel,
            self._seek_mode == "Exact frame",
        )
        if cap is None or not cap.isOpened():
            QMessageBox.critical(self, "Error",
                                 f"Cannot open video:\n{path}\n\n"
                                 f"Decoder: {self._backend}\n"
                                 "File may be unsupported or missing codec.")
            return False

        source_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        source_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        proxy_candidate: Path | None = None
        playback_path = path
        if (self._proxy_enabled
                and os.path.getsize(path) >= PROXY_MIN_BYTES
                and source_width > PROXY_MAX_WIDTH):
            proxy_candidate = proxy_cache_path(path)
            if proxy_candidate.is_file() and proxy_candidate.stat().st_size > 0:
                proxy_cap = open_cap(
                    str(proxy_candidate), self._backend,
                    self._hardware_accel,
                    self._seek_mode == "Exact frame",
                )
                if proxy_cap is not None and proxy_cap.isOpened():
                    cap.release()
                    cap = proxy_cap
                    playback_path = str(proxy_candidate)

        # BUG FIX: stop timer BEFORE releasing old cap
        self._timer.stop()
        self.is_playing = False
        self._btn_play.setText("Play")

        if self.cap:
            self.cap.release()
            self.cap = None

        self.cap = cap
        self._video_path = path
        self._playback_path = playback_path

        # BUG FIX: handle formats where FRAME_COUNT is 0 or -1
        raw_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.fps   = cap.get(cv2.CAP_PROP_FPS) or 30.0
        if raw_count > 0:
            self.total_frames = raw_count
        else:
            self.total_frames = 0   # unknown; slider will be disabled

        self.current_frame = 0
        self._cache.clear()

        # Marks remain useful when only the decoder is changed.
        if not preserve_marks:
            self.clear_marks()

        target_frame = max(0, min(start_frame, self.total_frames - 1)) \
            if self.total_frames > 0 else max(0, start_frame)

        self.slider.blockSignals(True)
        self.slider.setRange(0, max(0, self.total_frames - 1))
        self.slider.setValue(target_frame)
        self.slider.setEnabled(self.total_frames > 0)
        self.slider.blockSignals(False)

        if self.total_frames > 0:
            self._dur_lbl.setText(ms_to_ts(frame_to_ms(self.total_frames, self.fps)))
        else:
            self._dur_lbl.setText("--:--:--.---")

        self._file_lbl.setText(Path(path).name)

        vw  = source_width
        vh  = source_height
        sz  = os.path.getsize(path)
        tf  = f"{self.total_frames:,}" if self.total_frames else "unknown"
        audio = (f"{cap.audio_tracks} audio track"
                 f"{'s' if cap.audio_tracks != 1 else ''}"
                 if cap.audio_tracks is not None else "audio unknown")
        decoder = cap.backend_name
        if cap.hardware_fallback:
            decoder += " (software fallback)"
        if playback_path != path:
            decoder += f" + proxy {int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}"
        self._info_bar.setText(
            f"  {vw}x{vh}  |  {self.fps:.3f} fps  |  "
            f"{ms_to_ts(frame_to_ms(self.total_frames or 0, self.fps))}  |  "
            f"{tf} frames  |  {sizeof_fmt(sz)}  |  {decoder}  |  {audio}"
        )
        self._info_bar.show()

        for b in (self._btn_p10, self._btn_p1, self._btn_play,
                  self._btn_n1, self._btn_n10,
                  self._mark_btn, self._copy_btn):
            b.setEnabled(True)

        self._preview_thread.open_video(
            playback_path, self._backend, self._hardware_accel,
            self._seek_mode == "Exact frame",
        )
        self._waveform.set_loading()
        self._waveform_thread.request(path)
        self._thumbnail_strip.set_loading()
        self._thumbnail_thread.request(
            playback_path, self._backend, self._hardware_accel,
            self._seek_mode == "Exact frame",
        )
        self._show(target_frame)
        if proxy_candidate is not None and playback_path == path:
            self._set_status("Building playback proxy...", BLUE)
            self._proxy_thread.request(path, str(proxy_candidate))
        elif playback_path != path:
            self._set_status("Using cached playback proxy; exports remain full resolution.", BLUE)
        if record_recent:
            self._push_recent(path)
        return True

    # ── Playback ──────────────────────────────────────────────────────────────

    def _show(self, idx: int):
        if not self.cap:
            return
        if self.total_frames > 0:
            idx = max(0, min(idx, self.total_frames - 1))
        else:
            idx = max(0, idx)

        cached = self._cache.get(idx)
        if cached is not None:
            frame = cached
            # Only sync cap position when playing so _advance reads correctly
            if self.is_playing:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, idx + 1)
        else:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = self.cap.read()
            if not ret:
                return
            self._cache.put(idx, frame)

        self.current_frame = idx
        self._last_bgr     = frame
        self.display.show_frame(frame)
        ms = frame_to_ms(idx, self.fps)
        self._pos_lbl.setText(ms_to_ts(ms))
        tf  = f" / {self.total_frames:,}" if self.total_frames else ""
        self.display.set_overlay(f"Frame {idx:,}{tf}  |  {ms_to_ts(ms)}")
        self._waveform.set_position(ms / 1000.0)

        if not self._slider_held and self.total_frames > 0:
            self.slider.blockSignals(True)
            self.slider.setValue(idx)
            self.slider.blockSignals(False)

    def _advance(self):
        if not self.cap:
            return
        nxt = self.current_frame + 1

        # BUG FIX: total_frames == 0 means unknown — don't stop based on it
        if self.total_frames > 0 and nxt >= self.total_frames:
            if self._loop_mode:
                self._show(0)
                # Restart timer so cap position is correct
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 1)
            else:
                self.toggle_play()
            return

        ret, frame = self.cap.read()
        if not ret:
            # BUG FIX: resync cap on failure rather than silently drifting
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, nxt)
            ret, frame = self.cap.read()
            if not ret:
                self.toggle_play()
                return

        self._cache.put(nxt, frame)
        self.current_frame = nxt
        self._last_bgr     = frame
        self.display.show_frame(frame)
        ms = frame_to_ms(nxt, self.fps)
        self._pos_lbl.setText(ms_to_ts(ms))
        tf = f" / {self.total_frames:,}" if self.total_frames else ""
        self.display.set_overlay(f"Frame {nxt:,}{tf}  |  {ms_to_ts(ms)}")
        self._waveform.set_position(ms / 1000.0)

        if not self._slider_held and self.total_frames > 0:
            self.slider.blockSignals(True)
            self.slider.setValue(nxt)
            self.slider.blockSignals(False)

    def toggle_play(self):
        if not self.cap:
            return
        self.is_playing = not self.is_playing
        if self.is_playing:
            self._btn_play.setText("Pause")
            interval = max(1, int(1000.0 / (self.fps * self._speed)))
            self._timer.start(interval)
        else:
            self._btn_play.setText("Play")
            self._timer.stop()

    def step(self, delta: int):
        if not self.cap:
            return
        if self.is_playing:
            self.toggle_play()
        self._show(self.current_frame + delta)

    def _slider_press(self):
        self._slider_held = True
        if self.is_playing:
            self._timer.stop()

    def _slider_release(self):
        self._slider_held = False
        self._show(self.slider.value())
        if self.is_playing:
            interval = max(1, int(1000.0 / (self.fps * self._speed)))
            self._timer.start(interval)

    def _slider_changed(self, val: int):
        if self._slider_held:
            self._show(val)

    def _jump_to_thumbnail(self, frame_idx: int):
        if self.cap:
            self._show(frame_idx)

    def _speed_changed(self, text: str):
        try:
            self._speed = float(text.rstrip("x"))
        except ValueError:
            self._speed = 1.0
        if self.is_playing:
            interval = max(1, int(1000.0 / (self.fps * self._speed)))
            self._timer.setInterval(interval)
        self._cfg["speed"] = text
        save_config(self._cfg)

    def _loop_toggled(self, checked: bool):
        self._loop_mode = checked
        self._loop_btn.setProperty("active", "true" if checked else "false")
        self._loop_btn.style().unpolish(self._loop_btn)
        self._loop_btn.style().polish(self._loop_btn)

    # ── Hover preview ─────────────────────────────────────────────────────────

    def _slider_hovered(self, frame_idx: int, global_pos: QPoint):
        if not self.cap:
            return
        self._pending_hover_pos = global_pos
        self._preview_thread.request(frame_idx)

    def _slider_hover_left(self):
        self._hover_popup.hide()

    def _on_waveform_ready(self, path: str, samples, duration: float):
        if path != self._video_path:
            return
        self._waveform.set_waveform(samples, duration)
        self._waveform.set_position(frame_to_ms(self.current_frame, self.fps) / 1000.0)

    def _on_proxy_ready(self, source_path: str, output_path: str,
                        width: int, height: int):
        if (not self._proxy_enabled or source_path != self._video_path
                or not os.path.isfile(output_path)):
            return
        position = self.current_frame
        if self._open_path(source_path,
                           start_frame=position,
                           preserve_marks=True,
                           record_recent=False):
            self._set_status(
                f"Playback proxy ready: {width}x{height}; exports remain full resolution.",
                BLUE,
            )

    def _on_proxy_failed(self, source_path: str, error: str):
        if source_path == self._video_path and self._proxy_enabled:
            self._set_status(f"Proxy unavailable; using full-resolution playback. {error}", YELLOW)

    def _on_thumbnails_ready(self, path: str, frames):
        if path == self._playback_path:
            self._thumbnail_strip.set_frames(frames)

    def _on_preview_ready(self, frame_idx: int, bgr: np.ndarray):
        px = bgr_to_pixmap(bgr).scaled(
            184, 104,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._hover_thumb_lbl.setPixmap(px)
        self._hover_ts_lbl.setText(ms_to_ts(frame_to_ms(frame_idx, self.fps)))
        gp = self._pending_hover_pos
        x, y = gp.x() - 96, gp.y() - 148
        screen = QApplication.primaryScreen().availableGeometry()
        x = max(screen.left(), min(x, screen.right()  - 192))
        y = max(screen.top(),  min(y, screen.bottom() - 130))
        self._hover_popup.move(x, y)
        self._hover_popup.show()

    # ── Scene detection ──────────────────────────────────────────────────────

    def auto_mark_scenes(self):
        if not self.cap or not self._video_path:
            QMessageBox.information(self, "No Video", "Open a video before detecting scene cuts.")
            return
        if self.is_playing:
            self.toggle_play()
        min_gap = max(1, int(round(self.fps * 0.5)))
        self._set_status("Detecting scene cuts...", BLUE)
        self._scene_thread.request(
            self._video_path, self._backend, self._hardware_accel,
            self._seek_mode == "Exact frame", 0.45, min_gap,
        )

    def _on_scenes_ready(self, path: str, cuts):
        if path != self._video_path:
            return
        if not cuts:
            self._set_status("No scene cuts detected.", YELLOW)
            return
        original_position = self.current_frame
        for frame_idx in cuts:
            self._show(frame_idx)
            self.mark_frame()
        self._show(original_position)
        self._set_status(f"Auto-marked {len(cuts)} scene cut{'s' if len(cuts) != 1 else ''}.", GREEN)

    def _on_scenes_failed(self, path: str, error: str):
        if path == self._video_path:
            self._set_status(f"Scene detection failed: {error}", YELLOW)

    def auto_mark_chapters(self):
        if not self.cap or not self._video_path:
            QMessageBox.information(self, "No Video", "Open a video before loading chapters.")
            return
        chapters = extract_chapters(self._video_path)
        if not chapters:
            self._set_status("No embedded chapter markers found.", YELLOW)
            return
        original_position = self.current_frame
        added = 0
        for frame_idx, title in chapters:
            self._show(frame_idx)
            before = len(self.marked)
            self.mark_frame()
            if len(self.marked) > before and frame_idx in self.marked:
                self.marked[frame_idx]["label"] = title
                self.marked[frame_idx]["widget"].update_label(title)
                added += 1
        self._show(original_position)
        self._set_status(
            f"Loaded {added} chapter mark{'s' if added != 1 else ''}.", GREEN
        )

    # ── Marking ───────────────────────────────────────────────────────────────

    def mark_frame(self):
        if not self.cap:
            return
        if self.is_playing:
            self.toggle_play()
        idx = self.current_frame
        if idx in self.marked:
            self._marks_list.setCurrentItem(self.marked[idx]["item"])
            self._set_status(f"Already marked: {ms_to_ts(frame_to_ms(idx, self.fps))}", YELLOW)
            return

        thumb  = make_thumb(self._last_bgr) if self._last_bgr is not None else None
        color  = MAUVE
        widget = FrameItemWidget(idx, self.fps, thumb, color=color)
        widget.remove_requested.connect(self._remove_mark)
        widget.jump_requested.connect(self._jump_to)

        list_item = QListWidgetItem()
        list_item.setSizeHint(QSize(0, 90))
        list_item.setData(Qt.ItemDataRole.UserRole, idx)

        pos = self._marks_list.count()
        for i in range(self._marks_list.count()):
            if self._marks_list.item(i).data(Qt.ItemDataRole.UserRole) > idx:
                pos = i
                break
        self._marks_list.insertItem(pos, list_item)
        self._marks_list.setItemWidget(list_item, widget)
        self.marked[idx] = {
            "item": list_item, "widget": widget, "label": "",
            "color": color, "tags": "", "comment": "",
        }

        self.slider.set_marks({k: v["color"] for k, v in self.marked.items()})
        self._update_marks_ui()
        self._set_status(f"Marked: {ms_to_ts(frame_to_ms(idx, self.fps))}", GREEN)
        self._tabs.setCurrentIndex(0)

    def _remove_mark(self, idx: int):
        if idx not in self.marked:
            return
        item = self.marked.pop(idx)["item"]
        self._marks_list.takeItem(self._marks_list.row(item))
        self.slider.set_marks({k: v["color"] for k, v in self.marked.items()})
        self._update_marks_ui()

    def _ripple_delete(self, idx: int):
        if idx not in self.marked:
            return
        self._remove_mark(idx)
        self._set_status(
            "Ripple deleted mark; subsequent export numbers were compacted.", BLUE
        )

    def _delete_selected(self):
        for item in list(self._marks_list.selectedItems()):
            idx = item.data(Qt.ItemDataRole.UserRole)
            if idx in self.marked:
                self.marked.pop(idx)
                self._marks_list.takeItem(self._marks_list.row(item))
        self.slider.set_marks({k: v["color"] for k, v in self.marked.items()})
        self._update_marks_ui()

    def clear_marks(self):
        self._marks_list.clear()
        self.marked.clear()
        self.slider.set_marks({})
        self._update_marks_ui()

    def _update_marks_ui(self):
        n   = len(self.marked)
        self._count_lbl.setText(f"{n} frame{'s' if n != 1 else ''} marked")
        self._tabs.setTabText(0, f"Marks ({n})")
        has = n > 0
        self._export_btn.setEnabled(has)
        self._sheet_btn.setEnabled(has)
        self._ffmpeg_btn.setEnabled(has)
        self._clear_btn.setEnabled(has)
        self._del_sel_btn.setEnabled(has)
        self._btn_prev_mark.setEnabled(has)
        self._btn_next_mark.setEnabled(has)
        self._refresh_group_filter()

    def _refresh_group_filter(self):
        if not hasattr(self, "_group_combo"):
            return
        current = self._group_combo.currentText() or self._cfg.get("export_group", "All")
        groups = sorted({
            tag for mark in self.marked.values()
            for tag in parse_tags(mark.get("tags", ""))
        }, key=str.casefold)
        self._group_combo.blockSignals(True)
        self._group_combo.clear()
        self._group_combo.addItem("All")
        self._group_combo.addItems(groups)
        self._group_combo.setCurrentText(current if current in ["All", *groups] else "All")
        self._group_combo.blockSignals(False)
        self._cfg["export_group"] = self._group_combo.currentText()

    def _group_changed(self, group: str):
        self._cfg["export_group"] = group
        save_config(self._cfg)

    def _marks_context_menu(self, pos):
        item = self._marks_list.itemAt(pos)
        if not item:
            return
        idx  = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        act_jump  = menu.addAction("Jump to Frame")
        act_copy  = menu.addAction("Copy Frame to Clipboard")
        menu.addSeparator()
        act_label = menu.addAction("Edit Label...")
        act_tags = menu.addAction("Edit Tags...")
        act_comment = menu.addAction("Edit Comment...")
        # Color submenu
        color_menu = menu.addMenu("Set Color")
        color_acts = {}
        for name, hex_val in MARK_COLORS.items():
            ca = color_menu.addAction(name)
            color_acts[ca] = (name, hex_val)
        menu.addSeparator()
        act_del = menu.addAction("Remove")
        act_ripple = menu.addAction("Ripple Delete")

        chosen = menu.exec(self._marks_list.mapToGlobal(pos))
        if chosen is None:
            return
        if chosen == act_jump:
            self._jump_to(idx)
        elif chosen == act_copy:
            self._copy_mark_frame(idx)
        elif chosen == act_label:
            self._edit_label(idx)
        elif chosen == act_tags:
            self._edit_tags(idx)
        elif chosen == act_comment:
            self._edit_comment(idx)
        elif chosen == act_del:
            self._remove_mark(idx)
        elif chosen == act_ripple:
            self._ripple_delete(idx)
        elif chosen in color_acts:
            _, hex_val = color_acts[chosen]
            self._set_mark_color(idx, hex_val)

    def _set_mark_color(self, idx: int, color_hex: str):
        if idx not in self.marked:
            return
        self.marked[idx]["color"] = color_hex
        self.marked[idx]["widget"].set_color(color_hex)
        self.slider.set_marks({k: v["color"] for k, v in self.marked.items()})

    def _jump_to(self, idx: int):
        if self.is_playing:
            self.toggle_play()
        self._show(idx)

    def jump_prev_mark(self):
        keys = sorted(k for k in self.marked if k < self.current_frame)
        if keys:
            self._jump_to(keys[-1])

    def jump_next_mark(self):
        keys = sorted(k for k in self.marked if k > self.current_frame)
        if keys:
            self._jump_to(keys[0])

    def _edit_label(self, idx: int):
        if idx not in self.marked:
            return
        text, ok = QInputDialog.getText(
            self, "Edit Label", "Label for this mark:",
            text=self.marked[idx]["label"],
        )
        if ok:
            self.marked[idx]["label"] = text
            self.marked[idx]["widget"].update_label(text)

    def _edit_tags(self, idx: int):
        if idx not in self.marked:
            return
        text, ok = QInputDialog.getText(
            self, "Edit Tags", "Comma-separated tags for this mark:",
            text=self.marked[idx].get("tags", ""),
        )
        if ok:
            tags = ", ".join(parse_tags(text))
            self.marked[idx]["tags"] = tags
            self.marked[idx]["widget"].update_tags(tags)
            self._refresh_group_filter()

    def _edit_comment(self, idx: int):
        if idx not in self.marked:
            return
        text, ok = QInputDialog.getMultiLineText(
            self, "Edit Comment", "Shot note for this mark:",
            self.marked[idx].get("comment", ""),
        )
        if ok:
            comment = text.strip()
            self.marked[idx]["comment"] = comment
            self.marked[idx]["widget"].update_comment(comment)

    # ── Clipboard ─────────────────────────────────────────────────────────────

    def copy_frame_clipboard(self):
        if self._last_bgr is None:
            return
        QApplication.clipboard().setPixmap(bgr_to_pixmap(self._last_bgr))
        self._set_status("Frame copied to clipboard.", BLUE)

    def _copy_mark_frame(self, idx: int):
        if not self.cap:
            return
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = self.cap.read()
        # BUG FIX: restore cap position regardless of read success
        self._show(self.current_frame)
        if ret:
            QApplication.clipboard().setPixmap(bgr_to_pixmap(frame))
            self._set_status("Mark frame copied to clipboard.", BLUE)

    # ── Export ────────────────────────────────────────────────────────────────

    def browse_dir(self):
        d = QFileDialog.getExistingDirectory(
            self, "Select Output Folder", self._dir_edit.text()
        )
        if d:
            self._dir_edit.setText(d)

    def open_export_dir(self):
        d = self._dir_edit.text().strip()
        if not d or not os.path.isdir(d):
            return
        if sys.platform == "win32":
            os.startfile(d)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", d])
        else:
            subprocess.Popen(["xdg-open", d])

    def _collect_frames(self, group: str | None = None) -> list[tuple[int, np.ndarray, str]]:
        """Seek and read each marked frame. Returns [(idx, bgr, label), ...]."""
        results = []
        selected_group = group or self._group_combo.currentText()
        reader = open_cap(
            self._video_path, self._backend, self._hardware_accel,
            self._seek_mode == "Exact frame",
        )
        if reader is None or not reader.isOpened():
            return results
        try:
            for idx in ordered_mark_indices(self.marked, selected_group):
                reader.set(cv2.CAP_PROP_POS_FRAMES, idx)
                ret, frame = reader.read()
                if ret:
                    results.append((idx, frame, self.marked[idx]["label"]))
        finally:
            reader.release()
        self._show(self.current_frame)
        return results

    def _apply_scale(self, frame: np.ndarray, scale: str) -> np.ndarray:
        scale_map = {"100%": 1.0, "75%": 0.75, "50%": 0.5, "25%": 0.25}
        f = scale_map.get(scale)
        if f and f != 1.0:
            h, w = frame.shape[:2]
            return cv2.resize(frame, (int(w * f), int(h * f)),
                              interpolation=cv2.INTER_LANCZOS4)
        if scale == "Custom":
            cw = self._cust_spin.value()
            h, w = frame.shape[:2]
            return cv2.resize(frame, (cw, int(h * cw / w)),
                              interpolation=cv2.INTER_LANCZOS4)
        return frame

    def _apply_export_transform(self, frame: np.ndarray,
                                frame_idx: int, label: str) -> np.ndarray:
        if self._crop_check.isChecked():
            frame = crop_frame(
                frame, self._crop_x.value(), self._crop_y.value(),
                self._crop_w.value(), self._crop_h.value(),
            )
        frame = self._apply_scale(frame, self._scale_combo.currentText())
        if self._burn_check.isChecked():
            frame = burn_in_overlay(frame, frame_idx, self.fps, label)
        return frame

    def _write_export_frame(self, path: str, frame: np.ndarray,
                            fmt: str, quality: int,
                            enc_flags: list) -> bool:
        try:
            if fmt == "AVIF":
                if not PilFeatures.check("avif"):
                    return False
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                PilImage.fromarray(rgb).save(path, format="AVIF", quality=quality)
                return True
            if fmt == "TIFF 16-bit":
                return bool(cv2.imwrite(path, to_uint16_frame(frame)))
            if fmt == "EXR":
                float_frame = frame.astype(np.float32) / 255.0
                flags = [cv2.IMWRITE_EXR_TYPE, cv2.IMWRITE_EXR_TYPE_FLOAT]
                return bool(cv2.imwrite(path, float_frame, flags))
            return bool(cv2.imwrite(path, frame, enc_flags))
        except (OSError, ValueError, cv2.error):
            return False

    def export_frames(self):
        if not self.cap or not self.marked:
            return
        out_dir  = self._dir_edit.text().strip() or str(Path.home() / "Desktop")
        fmt      = self._fmt_combo.currentText()
        quality  = self._qual_spin.value()
        scale    = self._scale_combo.currentText()
        template = self._name_edit.text().strip() or DEFAULT_TEMPLATE
        group    = self._group_combo.currentText()
        stem     = Path(self._video_path).stem
        os.makedirs(out_dir, exist_ok=True)

        ext_map  = {
            "PNG": ".png", "JPEG": ".jpg", "WebP": ".webp",
            "TIFF": ".tif", "TIFF 16-bit": ".tif", "BMP": ".bmp",
            "GIF": ".gif", "WebP Animation": ".webp", "AVIF": ".avif",
            "EXR": ".exr",
        }
        ext      = ext_map.get(fmt, ".png")
        enc_flags: list = []
        if fmt == "JPEG":
            enc_flags = [cv2.IMWRITE_JPEG_QUALITY, quality]
        elif fmt in ("WebP", "WebP Animation", "AVIF"):
            enc_flags = [cv2.IMWRITE_WEBP_QUALITY, quality]

        frames_data = self._collect_frames(group)
        if not frames_data:
            self._set_status(f"No marks in export group: {group}", YELLOW)
            return
        exported, errors = 0, 0

        if fmt in ("GIF", "WebP Animation"):
            self._export_animation(frames_data, out_dir, stem, fmt, quality)
            self._update_export_config(out_dir, fmt, quality, scale, template, group)
            return

        sequence = export_sequence(self.marked, group)
        for idx, frame, label in frames_data:
            frame = self._apply_export_transform(frame, idx, label)
            fname = apply_template(
                template, stem, idx, self.fps, label, sequence[idx]
            ) + ext
            ok = self._write_export_frame(
                os.path.join(out_dir, fname), frame, fmt, quality, enc_flags
            )
            if ok:
                exported += 1
            else:
                errors += 1

        self._update_export_config(out_dir, fmt, quality, scale, template, group)
        color = YELLOW if errors else GREEN
        self._set_status(
            f"Exported {exported} frame{'s' if exported != 1 else ''}"
            + (f" ({errors} failed)" if errors else "")
            + (f" [{group}]" if group != "All" else "")
            + f"\n{out_dir}", color
        )
        self._tabs.setCurrentIndex(1)

    def show_ffmpeg_commands(self):
        if not self.cap or not self.marked:
            return
        group = self._group_combo.currentText()
        output_dir = self._dir_edit.text().strip() or str(Path.home() / "Desktop")
        template = self._name_edit.text().strip() or DEFAULT_TEMPLATE
        fmt = self._fmt_combo.currentText()
        ext = {
            "PNG": ".png", "JPEG": ".jpg", "WebP": ".webp",
            "TIFF": ".tif", "TIFF 16-bit": ".tif", "BMP": ".bmp",
            "GIF": ".gif", "WebP Animation": ".webp", "AVIF": ".avif",
            "EXR": ".exr",
        }.get(fmt, ".png")
        sequence = export_sequence(self.marked, group)
        lines = []
        for position, idx in enumerate(ordered_mark_indices(self.marked, group), 1):
            label = self.marked[idx].get("label", "")
            filename = apply_template(
                template, Path(self._video_path).stem, idx, self.fps,
                label, sequence.get(idx, position),
            ) + ext
            lines.append(ffmpeg_extract_command(
                self._video_path, idx, self.fps,
                os.path.join(output_dir, filename),
            ))
        if not lines:
            self._set_status(f"No marks in export group: {group}", YELLOW)
            return
        QMessageBox.information(
            self, "FFmpeg Commands", "\n".join(lines),
        )

    def _export_animation(self, frames_data: list, out_dir: str, stem: str,
                          fmt: str, quality: int):
        if not frames_data:
            return
        pil_frames = []
        for idx, bgr, label in frames_data:
            bgr = self._apply_export_transform(bgr, idx, label)
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            image = PilImage.fromarray(rgb)
            if fmt == "GIF":
                image = image.convert("P", palette=PilImage.ADAPTIVE, dither=0)
            pil_frames.append(image)
        group = self._group_combo.currentText()
        suffix = "" if group == "All" else f"_{safe_filename(group)}"
        extension = "gif" if fmt == "GIF" else "webp"
        out_path = os.path.join(out_dir, f"{safe_filename(stem)}{suffix}_marks.{extension}")
        save_kwargs = {
            "save_all": True,
            "append_images": pil_frames[1:],
            "duration": 500,
            "loop": 0,
        }
        if fmt == "GIF":
            save_kwargs["optimize"] = True
        else:
            save_kwargs["quality"] = quality
            save_kwargs["method"] = 6
        pil_frames[0].save(out_path, format=extension.upper(), **save_kwargs)
        self._set_status(
            f"Exported animated {fmt} ({len(pil_frames)} frames)\n{out_dir}", GREEN
        )
        self._tabs.setCurrentIndex(1)

    def export_contact_sheet(self):
        if not self.cap or not self.marked:
            return
        out_dir = self._dir_edit.text().strip() or str(Path.home() / "Desktop")
        os.makedirs(out_dir, exist_ok=True)

        group = self._group_combo.currentText()
        frames_data = self._collect_frames(group)
        if not frames_data:
            self._set_status(f"No marks in export group: {group}", YELLOW)
            return
        n    = len(frames_data)
        configured_cols = self._sheet_columns.value()
        cols = (max(1, min(6, configured_cols)) if configured_cols
                else max(2, min(6, math.ceil(math.sqrt(n)))))
        rows = math.ceil(n / cols)

        cell_w, cell_h, label_h = 320, 180, 26
        title = self._sheet_title.text().strip()
        watermark = self._sheet_watermark.text().strip()
        title_h = 34 if title else 0
        pad_c = [int(c * 0.9) for c in [30, 30, 46]]   # BASE in BGR

        sheet_w = cols * cell_w
        sheet_h = title_h + rows * (cell_h + label_h)
        sheet   = np.full((sheet_h, sheet_w, 3), pad_c, dtype=np.uint8)
        if title:
            cv2.putText(sheet, title, (8, 24), cv2.FONT_HERSHEY_SIMPLEX,
                        0.72, (203, 166, 247), 2, cv2.LINE_AA)

        for i, (idx, frame, label) in enumerate(frames_data):
            r, c = divmod(i, cols)
            x = c * cell_w
            y = title_h + r * (cell_h + label_h)
            frame = self._apply_export_transform(frame, idx, label)
            # Fit frame into cell
            fh, fw = frame.shape[:2]
            scale_f = min(cell_w / fw, cell_h / fh)
            nw, nh  = int(fw * scale_f), int(fh * scale_f)
            resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)
            ox = (cell_w - nw) // 2
            oy = (cell_h - nh) // 2
            sheet[y + oy:y + oy + nh, x + ox:x + ox + nw] = resized
            # Timestamp + label
            ts  = ms_to_ts(frame_to_ms(idx, self.fps))
            txt = f"{ts}" + (f"  {label}" if label else "")
            cv2.putText(sheet, txt, (x + 4, y + cell_h + 18),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.42,
                        (203, 166, 247), 1, cv2.LINE_AA)

        if watermark:
            text_size = cv2.getTextSize(
                watermark, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1
            )[0]
            cv2.putText(
                sheet, watermark,
                (max(6, sheet_w - text_size[0] - 8), sheet_h - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (166, 173, 200), 1, cv2.LINE_AA,
            )

        stem     = Path(self._video_path).stem
        suffix = "" if group == "All" else f"_{safe_filename(group)}"
        out_path = os.path.join(out_dir, f"{safe_filename(stem)}{suffix}_contact_sheet.png")
        cv2.imwrite(out_path, sheet)
        pdf_path = ""
        if self._sheet_pdf.isChecked():
            pdf_path = os.path.join(
                out_dir, f"{safe_filename(stem)}{suffix}_contact_sheet.pdf"
            )
            with PilImage.open(out_path) as image:
                image.convert("RGB").save(pdf_path, "PDF", resolution=150.0)
        self._cfg.update({
            "sheet_title": title,
            "sheet_watermark": watermark,
            "sheet_columns": configured_cols,
            "sheet_pdf": self._sheet_pdf.isChecked(),
        })
        save_config(self._cfg)
        group_note = f" [{group}]" if group != "All" else ""
        output_note = f"\n{pdf_path}" if pdf_path else ""
        self._set_status(
            f"Contact sheet saved ({n} frames){group_note}\n{out_path}{output_note}", TEAL
        )
        self._tabs.setCurrentIndex(1)

    def _update_export_config(self, out_dir, fmt, quality, scale, template, group="All"):
        self._cfg.update({
            "last_output_dir": out_dir,
            "export_format":   fmt,
            "export_quality":  quality,
            "export_scale":    scale,
            "naming_template": template,
            "export_group":     group,
            "burn_overlay":     self._burn_check.isChecked(),
            "crop_enabled":     self._crop_check.isChecked(),
            "crop_x":            self._crop_x.value(),
            "crop_y":            self._crop_y.value(),
            "crop_width":        self._crop_w.value(),
            "crop_height":       self._crop_h.value(),
        })
        save_config(self._cfg)

    # ── Session ───────────────────────────────────────────────────────────────

    def save_session(self):
        if not self._video_path:
            QMessageBox.warning(self, "No Video", "Open a video before saving a session.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Session", "", "FrameSnap Session (*.fsnap)"
        )
        if not path:
            return
        if not path.endswith(".fsnap"):
            path += ".fsnap"
        data = {
            "version":     "2.1",
            "video_path":  self._video_path,
            "position":    self.current_frame,
            "marks": [
                {"frame": idx, "label": m["label"], "color": m["color"],
                 "tags": m.get("tags", ""),
                 "comment": m.get("comment", "")}
                for idx, m in sorted(self.marked.items())
            ],
        }
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")
        self._set_status(f"Session saved: {Path(path).name}", GREEN)

    def load_session(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Session", "", "FrameSnap Session (*.fsnap)"
        )
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not read session:\n{e}")
            return

        video = data.get("video_path", "")
        if video and video != self._video_path:
            self._open_path(video)
            if not self.cap:
                return

        self.clear_marks()
        for entry in data.get("marks", []):
            fidx  = entry.get("frame", 0)
            label = entry.get("label", "")
            color = entry.get("color", MAUVE)
            tags  = ", ".join(parse_tags(entry.get("tags", "")))
            comment = str(entry.get("comment", "")).strip()
            if 0 <= fidx < max(self.total_frames, fidx + 1):
                # Temporarily set current_frame so mark_frame() uses it
                self.current_frame = fidx
                cached = self._cache.get(fidx)
                if cached is None:
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, fidx)
                    ret, frame = self.cap.read()
                    if ret:
                        self._last_bgr = frame
                        self._cache.put(fidx, frame)
                else:
                    self._last_bgr = cached
                self.mark_frame()
                if fidx in self.marked:
                    if label:
                        self.marked[fidx]["label"] = label
                        self.marked[fidx]["widget"].update_label(label)
                    self.marked[fidx]["tags"] = tags
                    self.marked[fidx]["widget"].update_tags(tags)
                    self.marked[fidx]["comment"] = comment
                    self.marked[fidx]["widget"].update_comment(comment)
                    self._set_mark_color(fidx, color)

        self._refresh_group_filter()
        pos = data.get("position", 0)
        self._show(min(pos, max(0, self.total_frames - 1)) if self.total_frames else pos)
        self._set_status(f"Session loaded: {len(self.marked)} marks.", GREEN)

    # ── View toggles ──────────────────────────────────────────────────────────

    def _toggle_overlay(self, checked: bool):
        self.display.set_show_overlay(checked)
        self._cfg["show_overlay"] = checked
        save_config(self._cfg)

    def _fmt_changed(self, fmt: str):
        lossy = fmt in ("JPEG", "WebP", "WebP Animation", "AVIF")
        self._qual_lbl_l.setEnabled(lossy)
        self._qual_spin.setEnabled(lossy)

    def _scale_changed(self, scale: str):
        custom = scale == "Custom"
        self._cust_lbl.setVisible(custom)
        self._cust_spin.setVisible(custom)

    # ── Status ────────────────────────────────────────────────────────────────

    def _set_status(self, msg: str, color: str = GREEN):
        self._status_lbl.setStyleSheet(f"color: {color}; font-size: 12px;")
        self._status_lbl.setText(msg)
        QTimer.singleShot(6000, lambda: self._status_lbl.setText(""))

    # ── Window drag-drop ──────────────────────────────────────────────────────

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if urls:
            self._open_path(urls[0].toLocalFile())

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        self._timer.stop()
        self._hover_popup.hide()
        self._preview_thread.stop()
        self._waveform_thread.stop()
        self._proxy_thread.stop()
        self._thumbnail_thread.stop()
        self._scene_thread.stop()
        if self.cap:
            self.cap.release()
        super().closeEvent(event)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    branding_icon = QIcon(str(_branding_icon_path()))
    app.setWindowIcon(branding_icon)
    app.setApplicationName("FrameSnap")
    app.setApplicationVersion("2.1.0")
    app.setStyleSheet(STYLESHEET)

    icon_path = Path(__file__).parent / "icon.svg"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    win = MainWindow()

    win.setWindowIcon(branding_icon)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
