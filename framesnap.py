#!/usr/bin/env python3
"""
FrameSnap v2.2.0
Browse any video, mark frames, and export screenshots — all formats, all features.
"""

import sys
import os
import json
import argparse
import csv
import multiprocessing
import subprocess
import math
import hashlib
import shutil
import tempfile
from pathlib import Path

from framesnap_version import __version__


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


# ── Dependency checks ─────────────────────────────────────────────────────────

def _bootstrap():
    """Fail with an install hint instead of mutating the user's environment."""
    if getattr(sys, "frozen", False):
        return
    import importlib
    missing = []
    for mod, pkg in [
        ("cv2",   "opencv-python"),
        ("numpy", "numpy"),
        ("PIL",   "Pillow"),
    ]:
        try:
            importlib.import_module(mod)
        except ImportError:
            missing.append(pkg)
    try:
        importlib.import_module("PyQt6")
    except ImportError:
        missing.append("PyQt6")
    if not missing:
        return
    project_root = Path(__file__).resolve().parent
    lock_path = project_root / "packaging" / "requirements-win-py312.txt"
    if lock_path.exists():
        install_hint = (
            f"python -m pip install --require-hashes --only-binary=:all: "
            f"-r {lock_path}"
        )
    else:
        install_hint = "python -m pip install -e ."
    raise RuntimeError(
        "FrameSnap cannot start because these dependencies are missing: "
        f"{', '.join(missing)}.\n"
        "Install the declared dependencies in a virtual environment, then retry:\n"
        f"  {install_hint}"
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
    QApplication, QMainWindow, QDialog, QWidget, QVBoxLayout, QHBoxLayout,
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

THEME_NAMES = (
    "Catppuccin Mocha", "Catppuccin Latte", "GitHub Dark", "AMOLED Black",
)
THEME_OVERRIDES = {
    "Catppuccin Mocha": "",
    "Catppuccin Latte": """
QMainWindow, QDialog, QWidget { background-color: #eff1f5; color: #4c4f69; }
QLabel { color: #4c4f69; }
QMenuBar, QMenu { background-color: #e6e9ef; color: #4c4f69; }
QMenuBar { border-bottom-color: #ccd0da; }
QMenu { border-color: #bcc0cc; }
QMenu::item:selected { background-color: #ccd0da; color: #8839ef; }
QPushButton { background-color: #e6e9ef; color: #4c4f69; border-color: #bcc0cc; }
QPushButton:hover { background-color: #ccd0da; border-color: #8839ef; color: #8839ef; }
QLineEdit, QListWidget { background-color: #e6e9ef; color: #4c4f69; border-color: #bcc0cc; }
QComboBox, QSpinBox { background-color: #e6e9ef; color: #4c4f69; border-color: #bcc0cc; }
QComboBox QAbstractItemView { background-color: #e6e9ef; color: #4c4f69; }
QGroupBox, QTabWidget::pane { border-color: #bcc0cc; background: #e6e9ef; }
QGroupBox::title { color: #8839ef; }
QTabBar::tab { background-color: #ccd0da; color: #6c6f85; }
QTabBar::tab:selected { background-color: #8839ef; color: #eff1f5; }
QScrollBar:vertical { background-color: #e6e9ef; }
QScrollBar::handle:vertical { background-color: #9ca0b0; }
QSlider::groove:horizontal { background-color: #ccd0da; }
QSlider::handle:horizontal, QSlider::sub-page:horizontal { background-color: #8839ef; }
QPushButton#markBtn { background-color: #8839ef; color: #eff1f5; }
QPushButton#exportBtn { background-color: #40a02b; color: #eff1f5; }
QPushButton#sheetBtn { background-color: #179299; color: #eff1f5; }
QPushButton#copyBtn { background-color: #1e66f5; color: #eff1f5; }
""",
    "GitHub Dark": """
QMainWindow, QDialog, QWidget { background-color: #0d1117; color: #e6edf3; }
QLabel { color: #e6edf3; }
QMenuBar, QMenu { background-color: #161b22; color: #e6edf3; }
QMenuBar { border-bottom-color: #30363d; }
QMenu { border-color: #484f58; }
QMenu::item:selected { background-color: #30363d; color: #58a6ff; }
QPushButton { background-color: #21262d; color: #e6edf3; border-color: #30363d; }
QPushButton:hover { background-color: #30363d; border-color: #58a6ff; color: #58a6ff; }
QLineEdit, QListWidget { background-color: #161b22; color: #e6edf3; border-color: #30363d; }
QComboBox, QSpinBox { background-color: #21262d; color: #e6edf3; border-color: #30363d; }
QComboBox QAbstractItemView { background-color: #161b22; color: #e6edf3; }
QGroupBox, QTabWidget::pane { border-color: #30363d; background: #161b22; }
QGroupBox::title { color: #d2a8ff; }
QTabBar::tab { background-color: #21262d; color: #8b949e; }
QTabBar::tab:selected { background-color: #238636; color: #ffffff; }
QScrollBar:vertical { background-color: #161b22; }
QScrollBar::handle:vertical { background-color: #484f58; }
QSlider::groove:horizontal { background-color: #30363d; }
QSlider::handle:horizontal, QSlider::sub-page:horizontal { background-color: #58a6ff; }
QPushButton#markBtn { background-color: #a371f7; color: #0d1117; }
QPushButton#exportBtn { background-color: #3fb950; color: #0d1117; }
QPushButton#sheetBtn { background-color: #39c5cf; color: #0d1117; }
QPushButton#copyBtn { background-color: #58a6ff; color: #0d1117; }
""",
    "AMOLED Black": """
QMainWindow, QDialog, QWidget { background-color: #000000; color: #f5f5f5; }
QLabel { color: #f5f5f5; }
QMenuBar, QMenu { background-color: #000000; color: #f5f5f5; }
QMenuBar { border-bottom-color: #252525; }
QMenu { border-color: #353535; }
QMenu::item:selected { background-color: #252525; color: #00e5ff; }
QPushButton { background-color: #151515; color: #f5f5f5; border-color: #353535; }
QPushButton:hover { background-color: #252525; border-color: #00e5ff; color: #00e5ff; }
QLineEdit, QListWidget { background-color: #050505; color: #f5f5f5; border-color: #353535; }
QComboBox, QSpinBox { background-color: #151515; color: #f5f5f5; border-color: #353535; }
QComboBox QAbstractItemView { background-color: #050505; color: #f5f5f5; }
QGroupBox, QTabWidget::pane { border-color: #353535; background: #050505; }
QGroupBox::title { color: #00e5ff; }
QTabBar::tab { background-color: #151515; color: #aaaaaa; }
QTabBar::tab:selected { background-color: #00e5ff; color: #000000; }
QScrollBar:vertical { background-color: #050505; }
QScrollBar::handle:vertical { background-color: #555555; }
QSlider::groove:horizontal { background-color: #252525; }
QSlider::handle:horizontal, QSlider::sub-page:horizontal { background-color: #00e5ff; }
QPushButton#markBtn { background-color: #ff00aa; color: #000000; }
QPushButton#exportBtn { background-color: #00e676; color: #000000; }
QPushButton#sheetBtn { background-color: #00e5ff; color: #000000; }
QPushButton#copyBtn { background-color: #448aff; color: #000000; }
""",
}


def stylesheet_for_theme(theme: str) -> str:
    return STYLESHEET + THEME_OVERRIDES.get(theme, "")

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


def ab_frame_limit(left_count: int, right_count: int) -> int:
    """Return the last shared A/B slider position for two frame counts."""
    return max(0, max(int(left_count), int(right_count)) - 1)


def clamp_frame_position(position: int, frame_count: int) -> int:
    """Clamp a frame position when a stream exposes a known frame count."""
    position = max(0, int(position))
    if frame_count > 0:
        return min(position, int(frame_count) - 1)
    return position


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


SESSION_VERSION = "2.2"
TEMPLATE_VERSION = "1"
CONFIG_VERSION = 1


class PersistenceError(ValueError):
    """Raised when a FrameSnap JSON document cannot be safely read or written."""


def _schema_version(value, default: str, kind: str) -> tuple[int, ...]:
    text = str(value if value is not None else default).strip()
    try:
        parts = tuple(int(part) for part in text.split("."))
    except (TypeError, ValueError):
        raise PersistenceError(f"{kind} has an invalid schema version: {text!r}") from None
    if not parts or any(part < 0 for part in parts):
        raise PersistenceError(f"{kind} has an invalid schema version: {text!r}")
    return parts


def _check_schema_version(value, current: str, default: str, kind: str) -> None:
    if _schema_version(value, default, kind) > _schema_version(current, current, kind):
        raise PersistenceError(
            f"{kind} version {value!s} is newer than this FrameSnap release "
            f"({current}); open it with a newer version."
        )


def _read_json_file(path: str | Path, kind: str) -> dict:
    target = Path(path)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PersistenceError(
            f"Could not read {kind} {target.name}: invalid JSON at line "
            f"{exc.lineno}, column {exc.colno}."
        ) from exc
    except OSError as exc:
        raise PersistenceError(
            f"Could not read {kind} {target.name}: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise PersistenceError(f"{kind} {target.name} must contain a JSON object.")
    return payload


def atomic_write_json(path: str | Path, payload: dict) -> None:
    """Write JSON beside its target, preserving the old file and one backup."""
    target = Path(path).expanduser()
    temp_path: Path | None = None
    backup_temp: Path | None = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
        )
        temp_path = Path(temp_name)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())

        backup = target.with_name(f"{target.name}.bak")
        if target.exists():
            backup_descriptor, backup_name = tempfile.mkstemp(
                prefix=f".{backup.name}.", suffix=".tmp", dir=str(target.parent)
            )
            os.close(backup_descriptor)
            backup_temp = Path(backup_name)
            shutil.copy2(target, backup_temp)
            os.replace(backup_temp, backup)
            backup_temp = None
        os.replace(temp_path, target)
        temp_path = None
    except (OSError, TypeError, ValueError) as exc:
        raise PersistenceError(f"Could not write {target.name}: {exc}") from exc
    finally:
        for leftover in (temp_path, backup_temp):
            if leftover is not None:
                try:
                    leftover.unlink()
                except OSError:
                    pass


def _clean_session_mark(entry: dict, frame: int) -> dict:
    return {
        "frame": int(frame),
        "label": str(entry.get("label", "")).strip(),
        "color": str(entry.get("color", MAUVE)),
        "tags": ", ".join(parse_tags(str(entry.get("tags", "")))),
        "comment": str(entry.get("comment", "")).strip(),
    }


def normalize_session_data(data: dict) -> dict:
    """Validate and normalize a .fsnap payload for interchange operations."""
    if not isinstance(data, dict):
        raise ValueError("Session payload must be a JSON object")
    _check_schema_version(
        data.get("version"), SESSION_VERSION, "2.1", "Session"
    )
    marks = {}
    for entry in data.get("marks", []):
        if not isinstance(entry, dict):
            continue
        try:
            frame = int(entry.get("frame", 0))
        except (TypeError, ValueError):
            continue
        if frame < 0:
            continue
        marks[frame] = _clean_session_mark(entry, frame)
    try:
        position = max(0, int(data.get("position", 0)))
    except (TypeError, ValueError):
        position = 0
    return {
        "version": SESSION_VERSION,
        "video_path": str(data.get("video_path", "")),
        "position": position,
        "marks": [marks[idx] for idx in sorted(marks)],
    }


def read_session_file(path: str | Path) -> dict:
    return normalize_session_data(_read_json_file(path, "session"))


def session_data_from_marks(video_path: str, position: int,
                            marked: dict) -> dict:
    return normalize_session_data({
        "version": SESSION_VERSION,
        "video_path": video_path,
        "position": position,
        "marks": [
            {"frame": idx, "label": mark.get("label", ""),
             "color": mark.get("color", MAUVE),
             "tags": mark.get("tags", ""),
             "comment": mark.get("comment", "")}
            for idx, mark in sorted(marked.items())
        ],
    })


def session_video_key(path: str) -> str:
    if not path:
        return ""
    return os.path.normcase(os.path.abspath(os.path.expanduser(path)))


def merge_session_data(left: dict, right: dict) -> dict:
    """Merge two normalized sessions, using the left mark as the primary."""
    left = normalize_session_data(left)
    right = normalize_session_data(right)
    if session_video_key(left["video_path"]) != session_video_key(right["video_path"]):
        raise ValueError("Sessions reference different videos")

    by_frame = {
        mark["frame"]: dict(mark) for mark in left["marks"]
    }
    for incoming in right["marks"]:
        current = by_frame.get(incoming["frame"])
        if current is None:
            by_frame[incoming["frame"]] = dict(incoming)
            continue
        current["label"] = current["label"] or incoming["label"]
        current["color"] = current["color"] or incoming["color"]
        current["tags"] = ", ".join(parse_tags(
            f"{current['tags']}, {incoming['tags']}"
        ))
        if incoming["comment"] and incoming["comment"] != current["comment"]:
            if current["comment"]:
                current["comment"] += f"\n{incoming['comment']}"
            else:
                current["comment"] = incoming["comment"]
    return {
        "version": left["version"],
        "video_path": left["video_path"] or right["video_path"],
        "position": left["position"],
        "marks": [by_frame[idx] for idx in sorted(by_frame)],
    }


def diff_session_data(left: dict, right: dict) -> list[dict]:
    """Return frame-level additions, removals, and metadata changes."""
    left = normalize_session_data(left)
    right = normalize_session_data(right)
    left_marks = {mark["frame"]: mark for mark in left["marks"]}
    right_marks = {mark["frame"]: mark for mark in right["marks"]}
    differences = []
    for frame in sorted(set(left_marks) | set(right_marks)):
        before = left_marks.get(frame)
        after = right_marks.get(frame)
        if before is None:
            differences.append({"frame": frame, "kind": "only-right",
                                "left": None, "right": after})
        elif after is None:
            differences.append({"frame": frame, "kind": "only-left",
                                "left": before, "right": None})
        elif before != after:
            differences.append({"frame": frame, "kind": "changed",
                                "left": before, "right": after})
    return differences


def session_template_from_data(data: dict, fps: float) -> dict:
    if fps <= 0:
        raise ValueError("Template export requires a positive frame rate")
    normalized = normalize_session_data(data)
    return {
        "version": TEMPLATE_VERSION,
        "marks": [
            {key: mark[key] for key in ("time_ms", "label", "color", "tags", "comment")}
            for mark in [
                {"time_ms": round(frame_to_ms(item["frame"], fps), 3), **item}
                for item in normalized["marks"]
            ]
        ],
    }


def normalize_template_data(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("Template payload must be a JSON object")
    _check_schema_version(
        data.get("version"), TEMPLATE_VERSION, TEMPLATE_VERSION, "Template"
    )
    marks = []
    for entry in data.get("marks", []):
        if not isinstance(entry, dict):
            continue
        try:
            time_ms = float(entry.get("time_ms", 0))
        except (TypeError, ValueError):
            continue
        if time_ms < 0:
            continue
        marks.append({
            "time_ms": time_ms,
            **_clean_session_mark(entry, 0),
        })
    return {"version": TEMPLATE_VERSION, "marks": marks}


def read_template_file(path: str | Path) -> dict:
    return normalize_template_data(_read_json_file(path, "template"))


def template_to_marks(template: dict, fps: float,
                      total_frames: int = 0) -> list[dict]:
    if fps <= 0:
        raise ValueError("Template application requires a positive frame rate")
    normalized = normalize_template_data(template)
    marks = {}
    for entry in normalized["marks"]:
        frame = max(0, round(entry["time_ms"] * fps / 1000.0))
        if total_frames > 0 and frame >= total_frames:
            continue
        marks[frame] = {
            "frame": frame,
            "label": entry["label"],
            "color": entry["color"],
            "tags": entry["tags"],
            "comment": entry["comment"],
        }
    return [marks[idx] for idx in sorted(marks)]


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


def _value_present(value) -> bool:
    return value is not None and str(value).strip() != ""


def _parse_marker_time_ms(value) -> float | None:
    if not _value_present(value):
        return None
    text = str(value).strip()
    if ":" not in text:
        return float(text) * 1000.0
    parts = text.split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid timestamp: {value}")
    hours, minutes, seconds = parts
    return (float(hours) * 3600.0 + float(minutes) * 60.0
            + float(seconds)) * 1000.0


def _resolve_marker_video(value: str, default_video: str,
                          base_dir: Path) -> str:
    raw = str(value or default_video).strip()
    if not raw:
        raise ValueError("Each marker needs a video_path or --video")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return str(path.resolve())


def load_marker_list(path: str | Path, video_path: str = "") -> list[dict]:
    """Load CSV/JSON frame markers for noninteractive batch export."""
    marker_path = Path(path)
    if marker_path.suffix.casefold() == ".csv":
        with marker_path.open(newline="", encoding="utf-8-sig") as handle:
            payload = list(csv.DictReader(handle))
        default_video = video_path
    else:
        raw = json.loads(marker_path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            default_video = str(raw.get("video_path", raw.get("video", video_path)))
            payload = raw.get("marks", raw.get("markers", []))
        else:
            default_video = video_path
            payload = raw
    if not isinstance(payload, list):
        raise ValueError("Marker list must be a JSON array or an object with marks")

    entries = []
    base_dir = marker_path.parent.resolve()
    for number, raw_entry in enumerate(payload, 1):
        if not isinstance(raw_entry, dict):
            raise ValueError(f"Marker {number} must be an object")
        frame = None
        if _value_present(raw_entry.get("frame")):
            frame = int(float(raw_entry["frame"]))
            if frame < 0:
                raise ValueError(f"Marker {number} has a negative frame")
        time_ms = None
        if frame is None:
            if _value_present(raw_entry.get("time_ms")):
                time_ms = float(raw_entry["time_ms"])
            else:
                time_ms = _parse_marker_time_ms(
                    raw_entry.get("seconds", raw_entry.get("time",
                                               raw_entry.get("timestamp")))
                )
            if time_ms is None or time_ms < 0:
                raise ValueError(f"Marker {number} needs frame or timestamp")
        entries.append({
            "video_path": _resolve_marker_video(
                raw_entry.get("video_path", raw_entry.get("video",
                                     raw_entry.get("path", ""))),
                default_video, base_dir,
            ),
            "frame": frame,
            "time_ms": time_ms,
            "label": str(raw_entry.get("label", "")).strip(),
            "tags": ", ".join(parse_tags(str(raw_entry.get("tags", "")))),
            "comment": str(raw_entry.get("comment", "")).strip(),
        })
    if not entries:
        raise ValueError("Marker list is empty")
    return entries


def scale_export_frame(frame: np.ndarray, scale: str) -> np.ndarray:
    scale_map = {"100%": 1.0, "75%": 0.75, "50%": 0.5, "25%": 0.25}
    factor = scale_map.get(scale, 1.0)
    if factor == 1.0:
        return frame
    height, width = frame.shape[:2]
    return cv2.resize(frame, (max(1, int(width * factor)),
                              max(1, int(height * factor))),
                      interpolation=cv2.INTER_LANCZOS4)


def transform_export_frame(frame: np.ndarray, frame_idx: int, fps: float,
                           label: str, scale: str = "100%",
                           burn_overlay: bool = False,
                           crop: tuple[int, int, int, int] | None = None) -> np.ndarray:
    if crop is not None:
        frame = crop_frame(frame, *crop)
    frame = scale_export_frame(frame, scale)
    if burn_overlay:
        frame = burn_in_overlay(frame, frame_idx, fps, label)
    return frame


def export_extension(fmt: str) -> str:
    return {
        "PNG": ".png", "JPEG": ".jpg", "WebP": ".webp",
        "TIFF": ".tif", "TIFF 16-bit": ".tif", "BMP": ".bmp",
        "AVIF": ".avif", "EXR": ".exr",
    }.get(fmt, ".png")


def write_export_frame(path: str, frame: np.ndarray, fmt: str,
                       quality: int = 90) -> bool:
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
            return bool(cv2.imwrite(
                path, float_frame,
                [cv2.IMWRITE_EXR_TYPE, cv2.IMWRITE_EXR_TYPE_FLOAT],
            ))
        flags = []
        if fmt == "JPEG":
            flags = [cv2.IMWRITE_JPEG_QUALITY, quality]
        elif fmt == "WebP":
            flags = [cv2.IMWRITE_WEBP_QUALITY, quality]
        return bool(cv2.imwrite(path, frame, flags))
    except (OSError, ValueError, cv2.error):
        return False


def batch_export_markers(marker_path: str | Path, output_dir: str | Path,
                         video_path: str = "", fmt: str = "PNG",
                         quality: int = 90, scale: str = "100%",
                         template: str = DEFAULT_TEMPLATE,
                         burn_overlay: bool = False,
                         crop: tuple[int, int, int, int] | None = None) -> dict:
    if fmt in ("GIF", "WebP Animation"):
        raise ValueError("Batch marker export supports still-image formats only")
    entries = load_marker_list(marker_path, video_path)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    by_video: dict[str, list[dict]] = {}
    for entry in entries:
        by_video.setdefault(entry["video_path"], []).append(entry)

    exported = 0
    failures = []
    extension = export_extension(fmt)
    for source, source_entries in by_video.items():
        reader = open_cap(source, "Auto", False, True)
        if reader is None or not reader.isOpened():
            failures.append(f"Could not open {source}")
            continue
        try:
            fps = reader.get(cv2.CAP_PROP_FPS) or 30.0
            resolved = []
            for entry in source_entries:
                frame = entry["frame"]
                if frame is None:
                    frame = max(0, round(entry["time_ms"] * fps / 1000.0))
                resolved.append((frame, entry))
            resolved.sort(key=lambda item: item[0])
            stem = Path(source).stem
            for sequence, (frame_idx, entry) in enumerate(resolved, 1):
                reader.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                ret, frame = reader.read()
                if not ret:
                    failures.append(f"{source}: could not read frame {frame_idx}")
                    continue
                frame = transform_export_frame(
                    frame, frame_idx, fps, entry["label"], scale,
                    burn_overlay, crop,
                )
                name = apply_template(
                    template, stem, frame_idx, fps, entry["label"], sequence
                ) + extension
                path = output / name
                if write_export_frame(str(path), frame, fmt, quality):
                    exported += 1
                else:
                    failures.append(f"{source}: could not write {path}")
        finally:
            reader.release()
    return {"exported": exported, "failed": failures, "videos": len(by_video)}


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


def perceptual_hash(frame: np.ndarray, hash_size: int = 8) -> int:
    """Return a compact DCT perceptual hash for a BGR or grayscale frame."""
    if frame is None or frame.size == 0:
        return 0
    hash_size = max(2, min(16, int(hash_size)))
    if frame.ndim == 3:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    else:
        gray = frame
    side = hash_size * 4
    resized = cv2.resize(gray, (side, side), interpolation=cv2.INTER_AREA)
    coefficients = cv2.dct(resized.astype(np.float32))[:hash_size, :hash_size]
    baseline = float(np.median(coefficients[1:, :]))
    digest = 0
    for bit in (coefficients > baseline).flat:
        digest = (digest << 1) | int(bool(bit))
    return digest


def hamming_distance(left: int, right: int) -> int:
    """Return the number of differing bits between two perceptual hashes."""
    return (int(left) ^ int(right)).bit_count()


def _code_points(points) -> list[list[float]]:
    if points is None:
        return []
    try:
        return [
            [round(float(point[0]), 2), round(float(point[1]), 2)]
            for point in np.asarray(points).reshape(-1, 2)
        ]
    except (TypeError, ValueError):
        return []


def detect_codes(frame: np.ndarray) -> list[dict]:
    """Decode QR and supported 1-D barcodes from one BGR frame."""
    if frame is None or frame.size == 0:
        return []
    detected: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add_code(kind: str, value: str, points=None, code_type: str = ""):
        value = str(value or "").strip()
        if not value:
            return
        label = code_type.strip() or kind
        key = (label, value)
        if key in seen:
            return
        seen.add(key)
        detected.append({
            "type": label,
            "data": value,
            "points": _code_points(points),
        })

    try:
        qr_detector = cv2.QRCodeDetector()
        multi = qr_detector.detectAndDecodeMulti(frame)
        if len(multi) == 4:
            found, values, points, _ = multi
            if found:
                for index, value in enumerate(values if values is not None else []):
                    polygon = points[index] if points is not None else None
                    add_code("QR", value, polygon)
        else:
            value, points, _ = qr_detector.detectAndDecode(frame)
            add_code("QR", value, points)
    except (AttributeError, cv2.error, TypeError, ValueError):
        pass

    barcode_detector_type = getattr(cv2, "barcode_BarcodeDetector", None)
    if barcode_detector_type is not None:
        try:
            barcode_detector = barcode_detector_type()
            found, values, types, points = barcode_detector.detectAndDecodeWithType(frame)
            if found:
                values = values if values is not None else []
                types = types if types is not None else []
                for index, value in enumerate(values):
                    code_type = types[index] if index < len(types) else "Barcode"
                    polygon = points[index] if points is not None else None
                    add_code("Barcode", value, polygon, code_type)
        except (AttributeError, cv2.error, TypeError, ValueError):
            pass
    return detected


class _HammingHashIndex:
    """Small BK-tree index for bounded-distance integer hash lookups."""

    def __init__(self):
        self._root: list | None = None

    def add(self, digest: int, frame_idx: int) -> None:
        if self._root is None:
            self._root = [digest, [frame_idx], {}]
            return
        node = self._root
        while True:
            distance = hamming_distance(digest, node[0])
            if distance == 0:
                node[1].append(frame_idx)
                return
            child = node[2].get(distance)
            if child is None:
                node[2][distance] = [digest, [frame_idx], {}]
                return
            node = child

    def query(self, digest: int, threshold: int) -> list[tuple[int, int]]:
        if self._root is None:
            return []
        matches = []
        pending = [self._root]
        while pending:
            node = pending.pop()
            distance = hamming_distance(digest, node[0])
            if distance <= threshold:
                matches.append((distance, node[1][0]))
            lower = distance - threshold
            upper = distance + threshold
            pending.extend(
                child for edge, child in node[2].items()
                if lower <= edge <= upper
            )
        return matches


def find_similar_frames(path: str, backend: str = "Auto",
                        hardware_accel: bool = False,
                        exact_seek: bool = True,
                        threshold: int = 8,
                        sample_step: int = 5,
                        hash_size: int = 8,
                        max_matches: int = 2000) -> dict:
    """Scan sampled frames and return earlier near-duplicate matches."""
    hash_size = max(2, min(16, int(hash_size)))
    threshold = max(0, min(hash_size * hash_size, int(threshold)))
    sample_step = max(1, int(sample_step))
    max_matches = max(1, int(max_matches))
    reader = open_cap(path, backend, hardware_accel, exact_seek)
    result = {"scanned": 0, "matches": [], "truncated": False}
    if reader is None or not reader.isOpened():
        return result

    index = _HammingHashIndex()
    frame_idx = 0
    try:
        while True:
            ok, frame = reader.read()
            if not ok or frame is None:
                break
            if frame_idx % sample_step == 0:
                digest = perceptual_hash(frame, hash_size)
                result["scanned"] += 1
                candidates = index.query(digest, threshold)
                if candidates:
                    distance, similar_to = min(
                        candidates, key=lambda item: (item[0], item[1])
                    )
                    if len(result["matches"]) < max_matches:
                        result["matches"].append({
                            "frame": frame_idx,
                            "similar_to": similar_to,
                            "distance": distance,
                        })
                    else:
                        result["truncated"] = True
                index.add(digest, frame_idx)
            frame_idx += 1
    finally:
        reader.release()
    return result


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

def wheel_step_for_video(cfg: dict, path: str) -> int:
    """Return the persisted mouse-wheel step for one video path."""
    entries = cfg.get("wheel_steps", {})
    if not isinstance(entries, dict):
        return 1
    try:
        value = int(entries.get(str(Path(path).expanduser().resolve()), 1))
    except (TypeError, ValueError):
        value = 1
    return max(1, min(1000, value))


def set_wheel_step_for_video(cfg: dict, path: str, step: int) -> int:
    """Persist and return a clamped mouse-wheel step for one video path."""
    entries = cfg.setdefault("wheel_steps", {})
    if not isinstance(entries, dict):
        entries = {}
        cfg["wheel_steps"] = entries
    value = max(1, min(1000, int(step)))
    entries[str(Path(path).expanduser().resolve())] = value
    return value


def _config_defaults() -> dict:
    return {
        "config_version": CONFIG_VERSION,
        "recent": [],
        "theme": "Catppuccin Mocha",
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
        "similarity_threshold": 8,
        "similarity_step": 5,
        "wheel_steps": {},
    }


def normalize_config(data: dict) -> dict:
    if not isinstance(data, dict):
        raise PersistenceError("Configuration must be a JSON object.")
    try:
        version = int(data.get("config_version", 1))
    except (TypeError, ValueError):
        raise PersistenceError("Configuration has an invalid schema version.") from None
    if version < 0 or version > CONFIG_VERSION:
        raise PersistenceError(
            f"Configuration version {version} is not supported by this release."
        )
    defaults = _config_defaults()
    defaults.update(data)
    defaults["config_version"] = CONFIG_VERSION
    return defaults


def load_config() -> dict:
    if CONFIG_PATH.exists():
        return normalize_config(_read_json_file(CONFIG_PATH, "configuration"))
    return _config_defaults()


def save_config(cfg: dict) -> None:
    atomic_write_json(CONFIG_PATH, normalize_config(cfg))


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


class SimilarityThread(QThread):
    """Search perceptual hashes away from the UI thread."""
    similar_ready = pyqtSignal(str, object)
    similar_failed = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mutex = QMutex()
        self._cond = QWaitCondition()
        self._pending: tuple[str, str, bool, bool, int, int] | None = None
        self._running = True

    def request(self, path: str, backend: str, hardware_accel: bool,
                exact_seek: bool, threshold: int, sample_step: int) -> None:
        self._mutex.lock()
        self._pending = (path, backend, hardware_accel, exact_seek,
                         threshold, sample_step)
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
            path, backend, hardware_accel, exact_seek, threshold, sample_step = pending
            try:
                matches = find_similar_frames(
                    path, backend, hardware_accel, exact_seek,
                    threshold, sample_step,
                )
                self.similar_ready.emit(path, matches)
            except Exception as exc:
                self.similar_failed.emit(path, str(exc))


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
    file_dropped = pyqtSignal(list)

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

    def show_message(self, message: str):
        self._bgr = None
        self.clear()
        self._placeholder()
        self.setText(message)

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
        paths = [url.toLocalFile() for url in event.mimeData().urls()
                 if url.isLocalFile()]
        if paths:
            self.file_dropped.emit(paths)


# ── A/B Viewer ───────────────────────────────────────────────────────────────

class ABViewerDialog(QDialog):
    """Compare two videos at the same numeric frame position."""

    def __init__(self, parent, left_path: str, right_path: str,
                 backend: str, hardware_accel: bool, exact_seek: bool,
                 start_frame: int = 0):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("FrameSnap · Side-by-Side A/B Viewer")
        self.setMinimumSize(1060, 700)
        self.resize(1280, 800)

        self._left_path = left_path
        self._right_path = right_path
        self._left_reader = open_cap(left_path, backend, hardware_accel, exact_seek)
        self._right_reader = open_cap(right_path, backend, hardware_accel, exact_seek)
        if self._left_reader is None or self._right_reader is None:
            if self._left_reader is not None:
                self._left_reader.release()
            if self._right_reader is not None:
                self._right_reader.release()
            raise RuntimeError("The selected videos could not be opened by the chosen decoder.")

        self._left_count = max(0, self._left_reader.frame_count)
        self._right_count = max(0, self._right_reader.frame_count)
        self._max_count = max(self._left_count, self._right_count)
        self._position = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        viewers = QSplitter(Qt.Orientation.Horizontal)
        viewers.setChildrenCollapsible(False)
        left_panel, self._left_display = self._make_display(
            "A", left_path, self._left_count, viewers
        )
        right_panel, self._right_display = self._make_display(
            "B", right_path, self._right_count, viewers
        )
        viewers.addWidget(left_panel)
        viewers.addWidget(right_panel)
        viewers.setSizes([1, 1])
        root.addWidget(viewers, 1)

        control_row = QHBoxLayout()
        previous = QPushButton("−1")
        previous.setToolTip("Show the previous frame position in both videos")
        previous.clicked.connect(lambda: self._show_position(self._position - 1))
        next_button = QPushButton("+1")
        next_button.setToolTip("Show the next frame position in both videos")
        next_button.clicked.connect(lambda: self._show_position(self._position + 1))
        self._position_label = QLabel("Frame 0")
        self._position_label.setMinimumWidth(90)
        self._position_label.setStyleSheet(
            f"color: {MAUVE}; font-family: Consolas, monospace;"
        )
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(0, ab_frame_limit(self._left_count, self._right_count))
        self._slider.setEnabled(self._max_count > 0)
        self._slider.valueChanged.connect(self._show_position)
        control_row.addWidget(previous)
        control_row.addWidget(next_button)
        control_row.addWidget(self._position_label)
        control_row.addWidget(self._slider, 1)
        root.addLayout(control_row)

        count_text = (
            f"A: {self._count_text(self._left_count)} frames  ·  "
            f"B: {self._count_text(self._right_count)} frames  ·  "
            "Frame positions are compared by index"
        )
        self._status_label = QLabel(count_text)
        self._status_label.setStyleSheet(f"color: {SUBTEXT0}; font-size: 11px;")
        root.addWidget(self._status_label)

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        root.addWidget(close_button, 0, Qt.AlignmentFlag.AlignRight)

        self._show_position(start_frame)

    @staticmethod
    def _count_text(count: int) -> str:
        return f"{count:,}" if count > 0 else "unknown"

    @staticmethod
    def _make_display(title: str, path: str, count: int, parent=None):
        panel = QWidget(parent)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        heading = QLabel(f"{title}  ·  {Path(path).name}")
        heading.setToolTip(path)
        heading.setStyleSheet(f"color: {TEXT}; font-weight: bold;")
        display = VideoDisplay()
        display.setMinimumSize(320, 180)
        layout.addWidget(heading)
        layout.addWidget(display, 1)
        return panel, display

    def _read_at(self, reader: VideoReader, count: int,
                 position: int) -> np.ndarray | None:
        if count > 0 and position >= count:
            return None
        if not reader.set(cv2.CAP_PROP_POS_FRAMES, position):
            return None
        ok, frame = reader.read()
        return frame if ok else None

    def _show_position(self, position: int):
        if self._max_count > 0:
            position = clamp_frame_position(position, self._max_count)
        else:
            position = max(0, int(position))
        self._position = position
        self._slider.blockSignals(True)
        self._slider.setValue(position)
        self._slider.blockSignals(False)
        self._position_label.setText(f"Frame {position:,}")

        left_frame = self._read_at(self._left_reader, self._left_count, position)
        right_frame = self._read_at(self._right_reader, self._right_count, position)
        if left_frame is None:
            self._left_display.show_message(f"No frame {position:,} in video A")
        else:
            self._left_display.show_frame(left_frame)
            self._left_display.set_overlay(f"Frame {position:,}")
        if right_frame is None:
            self._right_display.show_message(f"No frame {position:,} in video B")
        else:
            self._right_display.show_frame(right_frame)
            self._right_display.set_overlay(f"Frame {position:,}")

    def closeEvent(self, event):
        self._left_reader.release()
        self._right_reader.release()
        super().closeEvent(event)


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
        self.setWindowTitle(f"FrameSnap v{__version__}")
        self.setMinimumSize(1100, 680)
        self.resize(1380, 860)
        self.setAcceptDrops(True)

        try:
            self._cfg = load_config()
            self._config_load_error = None
        except PersistenceError as exc:
            self._cfg = _config_defaults()
            self._config_load_error = str(exc)
        self._theme = self._cfg.get("theme", THEME_NAMES[0])
        if self._theme not in THEME_NAMES:
            self._theme = THEME_NAMES[0]
        self._apply_theme(self._theme, persist=False)
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
        self._ab_dialog: ABViewerDialog | None = None
        self._video_path = ""
        self._playback_path = ""
        self._video_queue: list[str] = []
        self._queue_index = -1
        self.total_frames = 0       # 0 means unknown
        self.fps          = 30.0
        self.current_frame = 0
        self.is_playing   = False
        self._loop_mode   = False
        self._speed       = 1.0
        self._wheel_step  = 1
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
        self._similarity_thread = SimilarityThread(self)
        self._similarity_thread.similar_ready.connect(self._on_similarity_ready)
        self._similarity_thread.similar_failed.connect(self._on_similarity_failed)
        self._similarity_thread.start()
        self._pending_hover_pos = QPoint()

        self._build_menu()
        self._build_ui()
        self._build_timer()
        self._build_hover_popup()
        self._apply_config()
        if self._config_load_error:
            QTimer.singleShot(0, self._show_config_load_error)

    # ── Menu ──────────────────────────────────────────────────────────────────

    def _build_menu(self):
        mb = self.menuBar()

        file_menu = mb.addMenu("File")
        self._recent_menu = QMenu("Recent Files", self)
        file_menu.addAction(self._make_act("Open Video...", self.open_video))
        file_menu.addAction(self._make_act(
            "Open Side-by-Side A/B Viewer...", self.open_ab_viewer
        ))
        file_menu.addSeparator()
        file_menu.addMenu(self._recent_menu)
        file_menu.addSeparator()
        file_menu.addAction(self._make_act("Save Session...", self.save_session))
        file_menu.addAction(self._make_act("Load Session...", self.load_session))
        file_menu.addAction(self._make_act("Merge Sessions...", self.merge_sessions))
        file_menu.addAction(self._make_act("Compare Sessions...", self.diff_sessions))
        file_menu.addSeparator()
        file_menu.addAction(self._make_act(
            "Save Session Template...", self.save_session_template
        ))
        file_menu.addAction(self._make_act(
            "Apply Session Template...", self.apply_session_template
        ))
        file_menu.addSeparator()
        file_menu.addAction(self._make_act("Exit", self.close))

        edit_menu = mb.addMenu("Edit")
        edit_menu.addAction(self._make_act("Mark Current Frame", self.mark_frame))
        edit_menu.addAction(self._make_act("Auto-mark Scene Cuts", self.auto_mark_scenes))
        edit_menu.addAction(self._make_act("Auto-mark Chapters", self.auto_mark_chapters))
        edit_menu.addAction(self._make_act("Find Similar Frames...", self.find_similar_frames))
        edit_menu.addAction(self._make_act(
            "Detect QR/Barcodes in Current Frame", self.detect_codes_current_frame
        ))
        edit_menu.addAction(self._make_act(
            "Set Mouse-Wheel Step...", self.set_mouse_wheel_step
        ))
        edit_menu.addAction(self._make_act("Clear All Marks",    self.clear_marks))
        edit_menu.addSeparator()
        edit_menu.addAction(self._make_act("Copy Current Frame to Clipboard",
                                            self.copy_frame_clipboard))

        view_menu = mb.addMenu("View")
        self._act_overlay = self._make_act("Frame Overlay", self._toggle_overlay,
                                            checkable=True,
                                            checked=self._cfg.get("show_overlay", True))
        view_menu.addAction(self._act_overlay)
        theme_menu = view_menu.addMenu("Theme")
        self._theme_actions = {}
        for theme in THEME_NAMES:
            action = self._make_act(
                theme, lambda _checked, choice=theme: self._apply_theme(choice),
                checkable=True, checked=theme == self._theme,
            )
            self._theme_actions[theme] = action
            theme_menu.addAction(action)

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
        self._save_config()
        self._refresh_recent_menu()

    def _save_config(self):
        try:
            save_config(self._cfg)
        except PersistenceError as exc:
            self._set_status(f"Preferences not saved: {exc}", RED)

    def _show_config_load_error(self):
        if not self._config_load_error:
            return
        QMessageBox.warning(
            self,
            "Preferences Reset",
            "FrameSnap could not load its preferences and is using defaults.\n\n"
            f"{self._config_load_error}\n\n"
            "Your previous file was left untouched. Save a preference to create "
            "a new file and backup.",
        )
        self._set_status("Preferences reset to defaults; review the warning.", PEACH)

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
        self._queue_lbl = QLabel("Queue: 0/0")
        self._queue_lbl.setStyleSheet(f"color: {OVERLAY0}; font-size: 11px;")
        self._queue_prev_btn = QPushButton("◀")
        self._queue_prev_btn.setFixedSize(28, 28)
        self._queue_prev_btn.setToolTip("Previous video in queue")
        self._queue_prev_btn.clicked.connect(self.previous_queue_video)
        self._queue_next_btn = QPushButton("▶")
        self._queue_next_btn.setFixedSize(28, 28)
        self._queue_next_btn.setToolTip("Next video in queue")
        self._queue_next_btn.clicked.connect(self.next_queue_video)
        top_bar.addWidget(self._queue_lbl)
        top_bar.addWidget(self._queue_prev_btn)
        top_bar.addWidget(self._queue_next_btn)
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
        self.display.wheel_delta.connect(
            lambda direction: self.step(direction * self._wheel_step)
        )
        self.display.file_dropped.connect(self._open_queue)
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
        self._update_queue_ui()

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
        self._save_config()
        if self._video_path and self.cap:
            if not self._open_path(self._video_path,
                                   start_frame=self.current_frame,
                                   preserve_marks=True,
                                   record_recent=False):
                self._backend = previous
                self._cfg["backend"] = previous
                self._save_config()
                self._backend_combo.blockSignals(True)
                self._backend_combo.setCurrentText(previous)
                self._backend_combo.blockSignals(False)
            else:
                self._set_status(f"Decoder: {self.cap.backend_name}", BLUE)

    def _hardware_toggled(self, enabled: bool):
        previous = self._hardware_accel
        self._hardware_accel = enabled
        self._cfg["hardware_accel"] = enabled
        self._save_config()
        if self._video_path and self.cap:
            if not self._open_path(self._video_path,
                                   start_frame=self.current_frame,
                                   preserve_marks=True,
                                   record_recent=False):
                self._hardware_accel = previous
                self._cfg["hardware_accel"] = previous
                self._save_config()
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
        self._save_config()
        if self._video_path and self.cap:
            if not self._open_path(self._video_path,
                                   start_frame=self.current_frame,
                                   preserve_marks=True,
                                   record_recent=False):
                self._seek_mode = previous
                self._cfg["seek_mode"] = previous
                self._save_config()
                self._seek_combo.blockSignals(True)
                self._seek_combo.setCurrentText(previous)
                self._seek_combo.blockSignals(False)
            else:
                self._set_status(f"Seek mode: {self._seek_mode}", BLUE)

    def _proxy_toggled(self, enabled: bool):
        self._proxy_enabled = enabled
        self._cfg["proxy_enabled"] = enabled
        self._save_config()
        if self._video_path and self.cap:
            self._open_path(self._video_path,
                            start_frame=self.current_frame,
                            preserve_marks=True,
                            record_recent=False)

    # ── Video loading ─────────────────────────────────────────────────────────

    def open_video(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Open Video", "", VIDEO_FILTER
        )
        if paths:
            self._open_queue(paths)

    def open_ab_viewer(self):
        first_path = self._video_path if os.path.isfile(self._video_path) else ""
        if not first_path:
            first_path, _ = QFileDialog.getOpenFileName(
                self, "Choose A Video", "", VIDEO_FILTER
            )
        if not first_path:
            return
        second_path, _ = QFileDialog.getOpenFileName(
            self, "Choose B Video", "", VIDEO_FILTER
        )
        if not second_path:
            return
        if os.path.normcase(os.path.abspath(first_path)) == os.path.normcase(
                os.path.abspath(second_path)):
            QMessageBox.information(
                self, "Choose Two Videos",
                "Choose two different video files for an A/B comparison.",
            )
            return
        if self._ab_dialog is not None:
            self._ab_dialog.close()
        try:
            dialog = ABViewerDialog(
                self, first_path, second_path, self._backend,
                self._hardware_accel, self._seek_mode == "Exact frame",
                self.current_frame,
            )
        except RuntimeError as exc:
            QMessageBox.critical(self, "A/B Viewer Failed", str(exc))
            return
        self._ab_dialog = dialog
        dialog.finished.connect(lambda _result: setattr(self, "_ab_dialog", None))
        dialog.show()

    def _open_queue(self, paths: list[str]):
        unique = []
        seen = set()
        for path in paths:
            key = os.path.normcase(os.path.abspath(path))
            if path and key not in seen:
                unique.append(path)
                seen.add(key)
        if not unique:
            return
        self._video_queue = unique
        self._queue_index = 0
        if not self._open_path(unique[0], update_queue=False):
            self._video_queue = []
            self._queue_index = -1
        self._update_queue_ui()

    def _open_queue_index(self, index: int) -> bool:
        if not self._video_queue or not 0 <= index < len(self._video_queue):
            return False
        self._queue_index = index
        opened = self._open_path(
            self._video_queue[index], preserve_marks=True,
            update_queue=False,
        )
        self._update_queue_ui()
        return opened

    def previous_queue_video(self):
        self._open_queue_index(self._queue_index - 1)

    def next_queue_video(self):
        self._open_queue_index(self._queue_index + 1)

    def _update_queue_ui(self):
        if not hasattr(self, "_queue_lbl"):
            return
        count = len(self._video_queue)
        current = self._queue_index + 1 if self._queue_index >= 0 else 0
        self._queue_lbl.setText(f"Queue: {current}/{count}")
        self._queue_prev_btn.setEnabled(self._queue_index > 0)
        self._queue_next_btn.setEnabled(
            self._queue_index >= 0 and self._queue_index < count - 1
        )

    def _open_path(self, path: str, start_frame: int = 0,
                   preserve_marks: bool = False,
                   record_recent: bool = True,
                   update_queue: bool = True) -> bool:
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
        self._wheel_step = wheel_step_for_video(self._cfg, path)
        if update_queue and not preserve_marks:
            self._video_queue = [path]
            self._queue_index = 0
        self._update_queue_ui()

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

    def set_mouse_wheel_step(self):
        if not self._video_path:
            QMessageBox.information(
                self, "No Video", "Open a video before setting its mouse-wheel step."
            )
            return
        step, accepted = QInputDialog.getInt(
            self, "Mouse-Wheel Step",
            "Frames to move per mouse-wheel notch:",
            self._wheel_step, 1, 1000,
        )
        if not accepted:
            return
        self._wheel_step = set_wheel_step_for_video(
            self._cfg, self._video_path, step
        )
        self._save_config()
        self._set_status(
            f"Mouse wheel moves {self._wheel_step} frame"
            f"{'s' if self._wheel_step != 1 else ''} for this video.",
            GREEN,
        )

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
        self._save_config()

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

    # ── Similarity search ────────────────────────────────────────────────────

    def find_similar_frames(self):
        if not self.cap or not self._video_path:
            QMessageBox.information(
                self, "No Video", "Open a video before searching for similar frames."
            )
            return
        threshold, accepted = QInputDialog.getInt(
            self, "Find Similar Frames",
            "Maximum perceptual hash distance (0–64):",
            int(self._cfg.get("similarity_threshold", 8)), 0, 64,
        )
        if not accepted:
            return
        sample_step, accepted = QInputDialog.getInt(
            self, "Find Similar Frames",
            "Sample every N frames (1 scans every frame):",
            int(self._cfg.get("similarity_step", 5)), 1, 1000,
        )
        if not accepted:
            return
        self._cfg.update({
            "similarity_threshold": threshold,
            "similarity_step": sample_step,
        })
        self._save_config()
        if self.is_playing:
            self.toggle_play()
        self._set_status(
            f"Searching {Path(self._video_path).name} for near-duplicates...", BLUE
        )
        self._similarity_thread.request(
            self._video_path, self._backend, self._hardware_accel,
            self._seek_mode == "Exact frame", threshold, sample_step,
        )

    def _on_similarity_ready(self, path: str, result: dict):
        if path != self._video_path:
            return
        matches = result.get("matches", [])
        if not matches:
            self._set_status(
                f"No near-duplicate frames found in {result.get('scanned', 0):,} samples.",
                YELLOW,
            )
            return
        shown = matches[:80]
        lines = [
            f"Scanned {result.get('scanned', 0):,} sampled frames.",
            f"Found {len(matches):,}{'+' if result.get('truncated') else ''} near-duplicates.",
            "",
        ]
        lines.extend(
            f"Frame {match['frame']:,} ≈ {match['similar_to']:,} "
            f"(distance {match['distance']})"
            for match in shown
        )
        if len(matches) > len(shown) or result.get("truncated"):
            lines.append("…additional matches omitted from this summary.")
        QMessageBox.information(self, "Similar Frames", "\n".join(lines))
        self._set_status(
            f"Found {len(matches):,}{'+' if result.get('truncated') else ''} near-duplicate frames.",
            GREEN,
        )

    def _on_similarity_failed(self, path: str, error: str):
        if path == self._video_path:
            self._set_status(f"Similarity search failed: {error}", YELLOW)

    # ── QR and barcode detection ────────────────────────────────────────────

    def detect_codes_current_frame(self):
        if self._last_bgr is None:
            QMessageBox.information(
                self, "No Frame", "Open a video before detecting codes."
            )
            return
        codes = detect_codes(self._last_bgr)
        if not codes:
            self._set_status("No QR codes or barcodes detected in the current frame.", YELLOW)
            return
        lines = [f"Detected {len(codes)} code{'s' if len(codes) != 1 else ''}:", ""]
        lines.extend(f"{code['type']}: {code['data']}" for code in codes)
        QMessageBox.information(self, "QR/Barcode Detection", "\n".join(lines))
        self._set_status(
            f"Detected {len(codes)} QR/barcode{'s' if len(codes) != 1 else ''}.",
            GREEN,
        )

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
        self._save_config()

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
        self._save_config()
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
        self._save_config()

    # ── Session ───────────────────────────────────────────────────────────────

    def _apply_session_data(self, data: dict) -> bool:
        data = normalize_session_data(data)
        video = data["video_path"]
        if video and session_video_key(video) != session_video_key(self._video_path):
            if not self._open_path(video):
                return False
        if not self.cap:
            QMessageBox.warning(self, "No Video", "Open the session's video first.")
            return False

        self.clear_marks()
        for entry in data["marks"]:
            fidx = entry["frame"]
            if self.total_frames > 0 and fidx >= self.total_frames:
                continue
            self.current_frame = fidx
            cached = self._cache.get(fidx)
            if cached is None:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, fidx)
                ret, frame = self.cap.read()
                if not ret:
                    continue
                self._last_bgr = frame
                self._cache.put(fidx, frame)
            else:
                self._last_bgr = cached
            self.mark_frame()
            if fidx not in self.marked:
                continue
            self.marked[fidx]["label"] = entry["label"]
            self.marked[fidx]["widget"].update_label(entry["label"])
            self.marked[fidx]["tags"] = entry["tags"]
            self.marked[fidx]["widget"].update_tags(entry["tags"])
            self.marked[fidx]["comment"] = entry["comment"]
            self.marked[fidx]["widget"].update_comment(entry["comment"])
            self._set_mark_color(fidx, entry["color"])

        self._refresh_group_filter()
        pos = data["position"]
        self._show(min(pos, max(0, self.total_frames - 1))
                   if self.total_frames else pos)
        return True

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
        data = session_data_from_marks(
            self._video_path, self.current_frame, self.marked
        )
        try:
            atomic_write_json(path, data)
        except PersistenceError as exc:
            QMessageBox.critical(self, "Session Save Failed", str(exc))
            return
        self._set_status(f"Session saved: {Path(path).name}", GREEN)

    def load_session(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Session", "", "FrameSnap Session (*.fsnap)"
        )
        if not path:
            return
        try:
            data = read_session_file(path)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not read session:\n{e}")
            return
        if self._apply_session_data(data):
            self._set_status(f"Session loaded: {len(self.marked)} marks.", GREEN)

    def merge_sessions(self):
        first, _ = QFileDialog.getOpenFileName(
            self, "Select First Session", "", "FrameSnap Session (*.fsnap)"
        )
        if not first:
            return
        second, _ = QFileDialog.getOpenFileName(
            self, "Select Second Session", "", "FrameSnap Session (*.fsnap)"
        )
        if not second:
            return
        try:
            left = read_session_file(first)
            right = read_session_file(second)
            merged = merge_session_data(left, right)
        except (OSError, ValueError, json.JSONDecodeError) as e:
            QMessageBox.critical(self, "Merge Failed", str(e))
            return
        if not self._apply_session_data(merged):
            return
        overlap = len({mark["frame"] for mark in left["marks"]}
                       & {mark["frame"] for mark in right["marks"]})
        self._set_status(
            f"Merged {len(merged['marks'])} marks ({overlap} overlapping).", GREEN
        )

    def diff_sessions(self):
        first, _ = QFileDialog.getOpenFileName(
            self, "Select First Session", "", "FrameSnap Session (*.fsnap)"
        )
        if not first:
            return
        second, _ = QFileDialog.getOpenFileName(
            self, "Select Second Session", "", "FrameSnap Session (*.fsnap)"
        )
        if not second:
            return
        try:
            left = read_session_file(first)
            right = read_session_file(second)
        except (OSError, ValueError, json.JSONDecodeError) as e:
            QMessageBox.critical(self, "Compare Failed", str(e))
            return
        if session_video_key(left["video_path"]) != session_video_key(right["video_path"]):
            QMessageBox.warning(
                self, "Different Videos",
                "The sessions reference different videos and cannot be compared.",
            )
            return
        differences = diff_session_data(left, right)
        lines = [
            f"{len(differences)} difference{'s' if len(differences) != 1 else ''}.",
            f"Video: {left['video_path'] or '(unspecified)'}",
            "",
        ]
        for change in differences:
            frame = change["frame"]
            if change["kind"] == "only-left":
                lines.append(f"Frame {frame:,}: only in first session")
            elif change["kind"] == "only-right":
                lines.append(f"Frame {frame:,}: only in second session")
            else:
                lines.append(f"Frame {frame:,}: metadata changed")
                lines.append(f"  first:  {change['left']}")
                lines.append(f"  second: {change['right']}")
        QMessageBox.information(self, "Session Diff", "\n".join(lines))

    def save_session_template(self):
        if not self._video_path or not self.marked:
            QMessageBox.warning(self, "No Marks", "Mark frames before saving a template.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Session Template", "", "FrameSnap Template (*.fstpl)"
        )
        if not path:
            return
        if not path.endswith(".fstpl"):
            path += ".fstpl"
        data = session_template_from_data(
            session_data_from_marks(self._video_path, 0, self.marked), self.fps
        )
        try:
            atomic_write_json(path, data)
        except PersistenceError as exc:
            QMessageBox.critical(self, "Template Save Failed", str(exc))
            return
        self._set_status(f"Template saved: {Path(path).name}", GREEN)

    def apply_session_template(self):
        if not self.cap:
            QMessageBox.warning(self, "No Video", "Open a video before applying a template.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Apply Session Template", "", "FrameSnap Template (*.fstpl)"
        )
        if not path:
            return
        try:
            template = read_template_file(path)
            entries = template_to_marks(template, self.fps, self.total_frames)
        except (OSError, ValueError, json.JSONDecodeError) as e:
            QMessageBox.critical(self, "Template Failed", str(e))
            return
        original_position = self.current_frame
        added = 0
        updated = 0
        for entry in entries:
            fidx = entry["frame"]
            if fidx not in self.marked:
                self._show(fidx)
                before = len(self.marked)
                self.mark_frame()
                if len(self.marked) == before or fidx not in self.marked:
                    continue
                added += 1
            else:
                updated += 1
            mark = self.marked[fidx]
            mark["label"] = entry["label"]
            mark["widget"].update_label(entry["label"])
            mark["tags"] = entry["tags"]
            mark["widget"].update_tags(entry["tags"])
            mark["comment"] = entry["comment"]
            mark["widget"].update_comment(entry["comment"])
            self._set_mark_color(fidx, entry["color"])
        self._refresh_group_filter()
        self._show(original_position)
        self._set_status(
            f"Applied template: {added} added, {updated} updated.", GREEN
        )

    # ── View toggles ──────────────────────────────────────────────────────────

    def _apply_theme(self, theme: str, persist: bool = True):
        if theme not in THEME_NAMES:
            theme = THEME_NAMES[0]
        self._theme = theme
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(stylesheet_for_theme(theme))
        for name, action in getattr(self, "_theme_actions", {}).items():
            action.blockSignals(True)
            action.setChecked(name == theme)
            action.blockSignals(False)
        if persist:
            self._cfg["theme"] = theme
            self._save_config()

    def _toggle_overlay(self, checked: bool):
        self.display.set_show_overlay(checked)
        self._cfg["show_overlay"] = checked
        self._save_config()

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
        paths = [url.toLocalFile() for url in event.mimeData().urls()
                 if url.isLocalFile()]
        if paths:
            self._open_queue(paths)

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        self._timer.stop()
        self._hover_popup.hide()
        if self._ab_dialog is not None:
            self._ab_dialog.close()
            self._ab_dialog = None
        self._preview_thread.stop()
        self._waveform_thread.stop()
        self._proxy_thread.stop()
        self._thumbnail_thread.stop()
        self._scene_thread.stop()
        self._similarity_thread.stop()
        if self.cap:
            self.cap.release()
        super().closeEvent(event)


# ── Entry point ───────────────────────────────────────────────────────────────

def configure_high_dpi() -> bool:
    """Opt into Windows per-monitor-v2 scaling before Qt creates a screen."""
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        user32 = ctypes.windll.user32
        setter = user32.SetProcessDpiAwarenessContext
        setter.argtypes = [ctypes.c_void_p]
        setter.restype = ctypes.c_bool
        if setter(ctypes.c_void_p(-4)):  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
            return True
    except (AttributeError, OSError, OverflowError):
        pass
    try:
        import ctypes
        return ctypes.windll.shcore.SetProcessDpiAwareness(2) in (0, 0x80070005)
    except (AttributeError, OSError):
        return False


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="FrameSnap video marker exporter and desktop viewer."
    )
    parser.add_argument(
        "--batch-markers", "--markers", dest="marker_path",
        help="CSV or JSON marker list for noninteractive export",
    )
    parser.add_argument(
        "--video", default="",
        help="Default video when marker rows omit video_path",
    )
    parser.add_argument("--output-dir", default=".")
    parser.add_argument(
        "--format", default="PNG",
        choices=["PNG", "JPEG", "WebP", "TIFF", "TIFF 16-bit", "BMP", "AVIF", "EXR"],
    )
    parser.add_argument("--quality", type=int, default=90, choices=range(1, 101))
    parser.add_argument(
        "--scale", default="100%", choices=["100%", "75%", "50%", "25%"],
    )
    parser.add_argument("--template", default=DEFAULT_TEMPLATE)
    parser.add_argument("--burn-in", action="store_true")
    parser.add_argument(
        "--crop", nargs=4, type=int, metavar=("X", "Y", "W", "H"),
    )
    parser.add_argument("--version", action="version", version=f"FrameSnap {__version__}")
    return parser


def _run_batch_cli(args: argparse.Namespace) -> int:
    crop = tuple(args.crop) if args.crop else None
    try:
        result = batch_export_markers(
            args.marker_path, args.output_dir, args.video, args.format,
            args.quality, args.scale, args.template, args.burn_in, crop,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Batch export failed: {exc}", file=sys.stderr)
        return 2
    print(
        f"Exported {result['exported']} frame(s) from {result['videos']} video(s)"
    )
    for failure in result["failed"]:
        print(f"Warning: {failure}", file=sys.stderr)
    return 1 if result["failed"] else 0


def main(argv: list[str] | None = None):
    argv = sys.argv[1:] if argv is None else argv
    if argv:
        if sys.stdout is None:
            sys.stdout = open(os.devnull, "w", encoding="utf-8")
        if sys.stderr is None:
            sys.stderr = open(os.devnull, "w", encoding="utf-8")
        parser = _build_cli_parser()
        args = parser.parse_args(argv)
        if not args.marker_path:
            parser.print_help()
            return 0
        return _run_batch_cli(args)

    configure_high_dpi()
    app = QApplication(sys.argv)
    branding_icon = QIcon(str(_branding_icon_path()))
    app.setWindowIcon(branding_icon)
    app.setApplicationName("FrameSnap")
    app.setApplicationVersion(__version__)
    app.setStyleSheet(stylesheet_for_theme(THEME_NAMES[0]))

    icon_path = Path(__file__).parent / "icon.svg"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    win = MainWindow()

    win.setWindowIcon(branding_icon)
    win.show()
    return app.exec()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
