import os
import math
import json
import sys
import importlib
import re
from pathlib import Path
import numpy as np
import pytest
import wave
from PIL import Image

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import cv2  # noqa: E402
import framesnap as framesnap_module  # noqa: E402

from framesnap import av as pyav
from framesnap import (
    _bootstrap,
    CancellationToken,
    JobCancelled,
    PersistenceError,
    apply_template,
    atomic_write_json,
    atomic_write_export_frame,
    ab_frame_limit,
    batch_export_markers,
    burn_in_overlay,
    build_video_proxy,
    crop_frame,
    clamp_frame_position,
    detect_scene_cuts,
    detect_codes,
    extract_audio_waveform,
    extract_chapters,
    find_similar_frames,
    ffmpeg_extract_command,
    frame_time_identity,
    frame_to_ms,
    hamming_distance,
    main,
    load_config,
    load_marker_list,
    diff_session_data,
    default_export_manifest_path,
    ensure_output_path,
    merge_session_data,
    ms_to_ts,
    session_template_from_data,
    stylesheet_for_theme,
    THEME_NAMES,
    template_to_marks,
    open_cap,
    parse_tags,
    perceptual_hash,
    normalize_session_data,
    normalize_seek_mode,
    normalize_template_data,
    save_config,
    safe_filename,
    SEEK_OPTIONS,
    set_wheel_step_for_video,
    wheel_step_for_video,
    proxy_cache_path,
    resolve_collision_path,
    sha256_file,
    export_sequence,
    ordered_mark_indices,
    thumbnail_frame_indices,
    to_uint16_frame,
)


def test_missing_dependency_check_is_actionable(monkeypatch):
    real_import_module = importlib.import_module

    def missing_qt(module_name):
        if module_name == "PyQt6":
            raise ImportError("test-missing")
        return real_import_module(module_name)

    monkeypatch.setattr(importlib, "import_module", missing_qt)
    with pytest.raises(RuntimeError) as error:
        _bootstrap()
    assert "PyQt6" in str(error.value)
    assert "requirements-win-py312" in str(error.value)


def test_version_metadata_is_synced():
    version = importlib.import_module("framesnap_version").__version__
    root = Path(__file__).resolve().parent
    readme = (root / "README.md").read_text(encoding="utf-8")
    source = (root / "framesnap.py").read_text(encoding="utf-8")
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    metainfo = (
        root / "packaging" / "com.sysadmindoc.FrameSnap.metainfo.xml"
    ).read_text(encoding="utf-8")
    assert f"version-{version}-" in readme
    assert f"FrameSnap v{version}" in source
    assert f"## [v{version}]" in changelog
    assert re.search(rf'<release version="{re.escape(version)}"', metainfo)


def _write_test_video(path, count=5, fps=10.0):
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (32, 24)
    )
    assert writer.isOpened()
    for index in range(count):
        writer.write(np.full((24, 32, 3), index * 40, dtype=np.uint8))
    writer.release()


def test_timestamp_and_template_helpers():
    assert ms_to_ts(3723004) == "01:02:03.004"
    assert frame_to_ms(10, 25) == 400.0
    result = apply_template(
        "{stem}_{frame}_{ts}_{label}_{n}", "clip", 12, 25, "hero/close", 3
    )
    assert result == "clip_000012_00-00-00-480_hero_close_003"
    assert parse_tags(" hero, HERO, close-up,  ") == ["hero", "close-up"]
    marked = {
        2: {"tags": "hero"}, 9: {"tags": "cut"}, 15: {"tags": "hero"}
    }
    assert ordered_mark_indices(marked, "hero") == [2, 15]
    assert export_sequence(marked, "hero") == {2: 1, 15: 2}


def test_mouse_wheel_step_is_persisted_per_video():
    config = {"wheel_steps": {}}
    path = r"C:\clips\one.mp4"
    assert set_wheel_step_for_video(config, path, 12) == 12
    assert wheel_step_for_video(config, path) == 12
    assert set_wheel_step_for_video(config, path, 5000) == 1000
    assert wheel_step_for_video(config, path) == 1000


def test_ab_viewer_frame_position_helpers():
    assert ab_frame_limit(5, 11) == 10
    assert ab_frame_limit(0, 0) == 0
    assert clamp_frame_position(-4, 10) == 0
    assert clamp_frame_position(20, 10) == 9
    assert clamp_frame_position(20, 0) == 20


def test_ab_viewer_supports_time_alignment_offsets_and_boundaries(tmp_path):
    app = framesnap_module.QApplication.instance()
    if app is None:
        app = framesnap_module.QApplication([])
    left = tmp_path / "ab-left.mp4"
    right = tmp_path / "ab-right.mp4"
    _write_test_video(left)
    _write_test_video(right, count=3)

    dialog = framesnap_module.ABViewerDialog(
        None, str(left), str(right), "OpenCV", False, True,
    )
    assert [
        dialog._alignment_combo.itemText(index)
        for index in range(dialog._alignment_combo.count())
    ] == ["Frame index", "Presentation time"]
    assert dialog._slider.maximum() == 4
    assert "Frame index alignment" in dialog._status_label.text()

    dialog._offset_spin.setValue(-2)
    assert "offset B -2 frames" in dialog._status_label.text()
    dialog._show_position(0)
    assert "No frame at -2 in video B" in dialog._right_display.text()

    dialog._alignment_combo.setCurrentText("Presentation time")
    assert dialog._slider.maximum() == 500
    assert dialog._offset_label.text() == "Offset B (ms):"
    dialog._offset_spin.setValue(0)
    dialog._show_position(400)
    assert "No frame at 00:00:00.400 in video B" in dialog._status_label.text()
    dialog._offset_spin.setValue(100)
    dialog._show_position(200)
    assert "Presentation time alignment" in dialog._status_label.text()
    assert "offset B +100 ms" in dialog._status_label.text()
    assert "No frame at 00:00:00.300 in video B" in dialog._status_label.text()

    dialog._show_position(500)
    assert dialog._position == 500
    assert "No frame at 00:00:00.500 in video A" in dialog._status_label.text()
    dialog.close()


def test_pyav_time_seek_uses_presentation_timestamp(tmp_path):
    if pyav is None:
        pytest.skip("PyAV is optional")
    path = tmp_path / "timestamp-seek.mp4"
    _write_test_video(path)
    reader = open_cap(str(path), "PyAV", exact_seek=True)
    assert reader is not None and reader.isOpened()
    assert reader.seek_time_ms(350)
    ok, frame = reader.read()
    identity = reader.last_frame_info
    duration_ms = reader.duration_ms
    reader.release()
    assert ok and frame is not None
    assert identity["timestamp_source"] == "pts"
    assert identity["display_time_ms"] >= 350
    assert duration_ms >= 500


def test_export_transforms_preserve_expected_dimensions_and_metadata():
    frame = np.zeros((40, 60, 3), dtype=np.uint8)
    cropped = crop_frame(frame, 10, 8, 20, 16)
    burned = burn_in_overlay(cropped, 12, 25, "hero")
    assert cropped.shape == (16, 20, 3)
    assert burned.shape == cropped.shape
    assert np.any(burned != cropped)
    assert to_uint16_frame(cropped).dtype == np.uint16
    assert int(to_uint16_frame(cropped).max()) == 0


def test_ffmpeg_command_echo_is_replayable():
    command = ffmpeg_extract_command(
        r"C:\Videos\sample clip.mp4", 25, 25.0,
        r"C:\Exports\sample_000025.png",
    )
    assert command == (
        'ffmpeg -ss 1.000 -i "C:\\Videos\\sample clip.mp4" '
        '-frames:v 1 -y "C:\\Exports\\sample_000025.png"'
    )


def test_session_merge_and_diff_preserve_mark_metadata():
    left = {
        "version": "2.1", "video_path": r"C:\clip.mp4", "position": 4,
        "marks": [
            {"frame": 4, "label": "hero", "tags": "wide",
             "comment": "first note", "color": "#cba6f7"},
            {"frame": 20, "label": "left-only", "color": "#f38ba8"},
        ],
    }
    right = {
        "version": "2.1", "video_path": r"C:\clip.mp4", "position": 9,
        "marks": [
            {"frame": 4, "label": "", "tags": "hero",
             "comment": "second note", "color": "#cba6f7"},
            {"frame": 30, "label": "right-only", "color": "#a6e3a1"},
        ],
    }
    merged = merge_session_data(left, right)
    assert [mark["frame"] for mark in merged["marks"]] == [4, 20, 30]
    shared = merged["marks"][0]
    assert shared["label"] == "hero"
    assert shared["tags"] == "wide, hero"
    assert shared["comment"] == "first note\nsecond note"
    differences = diff_session_data(left, right)
    assert [change["kind"] for change in differences] == [
        "changed", "only-left", "only-right"
    ]


def test_json_persistence_is_atomic_and_keeps_one_backup(tmp_path):
    target = tmp_path / "session.fsnap"
    target.write_text(json.dumps({"version": "2.1", "marks": []}), encoding="utf-8")

    atomic_write_json(target, {"version": "2.2", "marks": [{"frame": 4}]})
    assert json.loads(target.read_text(encoding="utf-8"))["version"] == "2.2"

    atomic_write_json(target, {"version": "2.2", "marks": [{"frame": 8}]})
    backup = target.with_name("session.fsnap.bak")
    assert json.loads(backup.read_text(encoding="utf-8"))["marks"][0]["frame"] == 4
    assert not list(tmp_path.glob(".session.fsnap.*.tmp"))

    with pytest.raises(PersistenceError):
        atomic_write_json(target, {"invalid": object()})
    assert json.loads(target.read_text(encoding="utf-8"))["marks"][0]["frame"] == 8


def test_persistence_migrations_normalize_legacy_and_reject_future_versions():
    session = normalize_session_data({
        "version": "2.1",
        "video_path": "clip.mp4",
        "marks": [{"frame": 3}],
    })
    assert session["version"] == "2.2"
    assert normalize_template_data({"marks": []})["version"] == "1"
    with pytest.raises(PersistenceError, match="newer"):
        normalize_session_data({"version": "99.0", "marks": []})


def test_config_persistence_has_schema_and_backup(tmp_path, monkeypatch):
    config_path = tmp_path / "framesnap-config.json"
    monkeypatch.setattr(framesnap_module, "CONFIG_PATH", config_path)
    save_config({"theme": "GitHub Dark"})
    assert load_config()["config_version"] == 1
    save_config({"theme": "Catppuccin Latte"})
    backup = config_path.with_name("framesnap-config.json.bak")
    assert json.loads(backup.read_text(encoding="utf-8"))["theme"] == "GitHub Dark"
    config_path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(PersistenceError, match="invalid JSON"):
        load_config()


def test_session_template_round_trips_relative_timestamps():
    session = {
        "video_path": "clip.mp4",
        "marks": [
            {"frame": 0, "label": "start", "color": "#cba6f7"},
            {"frame": 30, "label": "later", "tags": "hero"},
        ],
    }
    template = session_template_from_data(session, 10.0)
    assert [mark["time_ms"] for mark in template["marks"]] == [0.0, 3000.0]
    applied = template_to_marks(template, 20.0, total_frames=100)
    assert [mark["frame"] for mark in applied] == [0, 60]
    assert applied[1]["label"] == "later"
    assert applied[1]["tags"] == "hero"


def test_batch_marker_export_supports_csv_json_and_cli(tmp_path):
    video = tmp_path / "batch.mp4"
    _write_test_video(video)
    csv_path = tmp_path / "markers.csv"
    csv_path.write_text("frame,label\n0,first\n3,last\n", encoding="utf-8")
    csv_output = tmp_path / "csv-output"
    result = batch_export_markers(csv_path, csv_output, str(video), "PNG")
    assert result["exported"] == 2
    assert result["failed"] == []
    assert result["videos"] == 1
    assert result["resumed"] == 0
    assert result["skipped"] == 0
    assert len(list(csv_output.glob("*.png"))) == 2
    manifest = Path(result["manifest"])
    assert manifest == default_export_manifest_path(csv_path, csv_output)
    records = json.loads(manifest.read_text(encoding="utf-8"))["items"]
    assert len(records) == 2
    assert all(
        record["status"] == "complete"
        and record["source_path"] == str(video.resolve())
        and record["sha256"] == sha256_file(record["output_path"])
        for record in records.values()
    )
    resumed = batch_export_markers(csv_path, csv_output, str(video), "PNG")
    assert resumed["exported"] == 0
    assert resumed["resumed"] == 2

    json_path = tmp_path / "markers.json"
    json_path.write_text(
        json.dumps({"video_path": str(video), "marks": [{"time_ms": 200}]}),
        encoding="utf-8",
    )
    json_output = tmp_path / "json-output"
    assert main([
        "--batch-markers", str(json_path),
        "--output-dir", str(json_output),
        "--format", "JPEG",
    ]) == 0
    assert len(list(json_output.glob("*.jpg"))) == 1


def test_collision_policy_and_transactional_export(tmp_path, monkeypatch):
    target = tmp_path / "frame.png"
    target.write_bytes(b"original")
    assert resolve_collision_path(target, "skip") is None
    assert resolve_collision_path(target, "suffix") == tmp_path / "frame (1).png"
    assert resolve_collision_path(target, "overwrite") == target

    frame = np.zeros((8, 8, 3), dtype=np.uint8)
    monkeypatch.setattr(framesnap_module, "write_export_frame", lambda *args: False)
    assert not atomic_write_export_frame(target, frame, "PNG")
    assert target.read_bytes() == b"original"
    assert not list(tmp_path.glob(".frame.*.png"))


def test_marker_validation_and_output_containment(tmp_path):
    marker_path = tmp_path / "markers.json"
    marker_path.write_text(
        json.dumps({"video_path": "clip.mp4", "marks": [{"frame": 100_000_001}]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="between 0"):
        load_marker_list(marker_path)

    marker_path.write_text(
        json.dumps({"video_path": "clip.mp4", "marks": [{"time_ms": "NaN"}]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="invalid time_ms"):
        load_marker_list(marker_path)

    marker_path.write_text(
        json.dumps({
            "video_path": "clip.mp4",
            "marks": [{"frame": 0, "label": "x" * 513}],
        }),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="label exceeds"):
        load_marker_list(marker_path)

    assert safe_filename("CON.txt") == "_CON.txt"
    assert safe_filename("bad\x00name/with\\separators") == "bad_name_with_separators"
    assert len(safe_filename("x" * 500)) == 180

    output = tmp_path / "exports"
    with pytest.raises(ValueError, match="escapes"):
        ensure_output_path(output, output / ".." / "outside.png")


def test_windowed_cli_version_handles_missing_streams(monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    with pytest.raises(SystemExit) as error:
        main(["--version"])
    assert error.value.code == 0


def test_alternative_theme_stylesheets_are_available():
    for theme in THEME_NAMES:
        stylesheet = stylesheet_for_theme(theme)
        assert "QMainWindow" in stylesheet
        assert stylesheet.startswith("\nQMainWindow")


def test_main_window_accessibility_and_keyboard_contract(tmp_path, monkeypatch):
    app = framesnap_module.QApplication.instance()
    if app is None:
        app = framesnap_module.QApplication([])
    monkeypatch.setattr(
        framesnap_module, "CONFIG_PATH", tmp_path / "framesnap-config.json"
    )
    window = framesnap_module.MainWindow()
    try:
        for widget in (
            window._open_btn, window.display, window.slider,
            window._thumbnail_strip, window._marks_list, window._mark_btn,
            window._export_btn, window._status_lbl,
        ):
            assert widget.accessibleName()
            assert widget.accessibleDescription()

        assert window._thumbnail_strip.focusPolicy().name == "StrongFocus"
        assert window._tabs.widget(1).__class__.__name__ == "QScrollArea"
        assert "#ffff00" in stylesheet_for_theme("High Contrast")
        assert "#00ffff" in stylesheet_for_theme("High Contrast")
        assert window._play_action.shortcut().toString() == "Ctrl+Space"
        assert window._step_previous_action.shortcut().toString() == "Ctrl+Left"
        assert window._step_next_action.shortcut().toString() == "Ctrl+Right"
        assert window._mark_menu_action.shortcut().toString() == "Shift+F10"

        window._loop_toggled(True)
        assert "on" in window._loop_btn.accessibleDescription()
        window._set_status("Accessibility test status", framesnap_module.BLUE)
        assert window._status_lbl.accessibleDescription() == "Accessibility test status"
    finally:
        window.close()
        app.processEvents()


def test_export_codecs_write_avif_tiff16_and_exr(tmp_path):
    frame = np.full((12, 16, 3), 128, dtype=np.uint8)
    avif = tmp_path / "frame.avif"
    Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).save(
        avif, format="AVIF", quality=80
    )
    assert avif.is_file()

    tiff = tmp_path / "frame16.tif"
    assert cv2.imwrite(str(tiff), to_uint16_frame(frame))
    assert cv2.imread(str(tiff), cv2.IMREAD_UNCHANGED).dtype == np.uint16

    exr = tmp_path / "frame.exr"
    assert cv2.imwrite(
        str(exr), frame.astype(np.float32) / 255.0,
        [cv2.IMWRITE_EXR_TYPE, cv2.IMWRITE_EXR_TYPE_FLOAT],
    )
    assert exr.is_file()


@pytest.mark.parametrize("backend", ["OpenCV", "PyAV"])
def test_reader_seek_is_frame_accurate(tmp_path, backend):
    if backend == "PyAV" and pyav is None:
        pytest.skip("PyAV is optional")
    path = tmp_path / "reader-test.mp4"
    _write_test_video(path)

    reader = open_cap(str(path), backend)
    assert reader is not None and reader.isOpened()
    assert reader.frame_count >= 5
    assert reader.set(cv2.CAP_PROP_POS_FRAMES, 3)
    ok, frame = reader.read()
    reader.release()

    assert ok and frame is not None
    assert abs(float(frame.mean()) - 120.0) < 12.0


@pytest.mark.parametrize("exact_seek", [True, False])
def test_reader_seek_mode_is_explicit(tmp_path, exact_seek):
    if pyav is None:
        pytest.skip("PyAV is optional")
    path = tmp_path / "seek-mode.mp4"
    _write_test_video(path)
    reader = open_cap(str(path), "PyAV", exact_seek=exact_seek)
    assert reader is not None and reader.exact_seek is exact_seek
    assert reader.set(cv2.CAP_PROP_POS_FRAMES, 3)
    ok, frame = reader.read()
    reader.release()
    assert ok and frame is not None


def test_reader_preserves_frame_time_identity_and_final_frame(tmp_path):
    path = tmp_path / "identity.mp4"
    _write_test_video(path)
    reader = open_cap(str(path), "OpenCV")
    assert reader is not None and reader.isOpened()
    assert reader.set(cv2.CAP_PROP_POS_FRAMES, 4)
    ok, frame = reader.read()
    identity = reader.last_frame_info
    assert ok and frame is not None
    assert identity["frame"] == 4
    assert identity["pts"] is None
    assert identity["timestamp_source"] == "nominal_fps"
    assert identity["display_time_ms"] == 400.0
    reader.release()

    if pyav is not None:
        reader = open_cap(str(path), "PyAV")
        assert reader is not None and reader.isOpened()
        assert reader.set(cv2.CAP_PROP_POS_FRAMES, 4)
        ok, frame = reader.read()
        identity = reader.last_frame_info
        reader.release()
        assert ok and frame is not None
        assert identity["timestamp_source"] == "pts"
        assert identity["pts"] is not None
        assert identity["time_base"]
        assert identity["presentation_time_ms"] is not None


def test_frame_time_contract_migrates_legacy_marks_and_seek_modes():
    identity = frame_time_identity(7, 0.0)
    assert identity["timestamp_source"] == "unknown"
    assert identity["display_time_ms"] is None
    assert normalize_seek_mode("Fast keyframe") == "Approximate keyframe"
    assert normalize_seek_mode("not-a-mode", exact_seek=False) == "Approximate keyframe"
    assert SEEK_OPTIONS == [
        "Exact frame", "Approximate keyframe", "Nearest timestamp"
    ]

    session = normalize_session_data({
        "video_path": "clip.mp4",
        "marks": [{
            "frame": 7,
            "pts": 231,
            "time_base": "1/1000",
            "presentation_time_ms": 231,
            "display_time_ms": 100.5,
            "timestamp_source": "pts",
        }],
    })
    mark = session["marks"][0]
    assert mark["pts"] == 231
    assert mark["time_base"] == "1/1000"
    assert mark["display_time_ms"] == 100.5
    assert mark["timestamp_source"] == "pts"


def test_auto_reader_and_hardware_request(tmp_path):
    path = tmp_path / "auto-test.mp4"
    _write_test_video(path)

    reader = open_cap(str(path), "Auto", True)
    assert reader is not None and reader.isOpened()
    ok, frame = reader.read()
    assert ok and frame is not None
    assert reader.backend_name
    assert reader.hardware_accel or reader.hardware_fallback or pyav is None
    reader.release()


def test_waveform_without_audio_is_empty(tmp_path):
    path = tmp_path / "silent-video.mp4"
    _write_test_video(path)
    samples, duration = extract_audio_waveform(str(path))
    assert samples == []
    assert duration == 0.0


def test_waveform_extracts_audio_levels(tmp_path):
    path = tmp_path / "tone.wav"
    sample_rate = 8_000
    sample_count = sample_rate // 2
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(sample_rate)
        values = [
            int(12_000 * math.sin(2 * math.pi * 440 * index / sample_rate))
            for index in range(sample_count)
        ]
        audio.writeframes(np.asarray(values, dtype="<i2").tobytes())

    samples, duration = extract_audio_waveform(str(path), bucket_count=32)
    assert len(samples) == 32
    assert 0.45 < duration < 0.55
    assert max(samples) > 0.8


def test_proxy_generation_is_cached_and_downscaled(tmp_path):
    source = tmp_path / "source.mp4"
    output = tmp_path / "cache" / "proxy.mp4"
    _write_test_video(source)
    width, height = build_video_proxy(source, output, max_width=16)
    assert (width, height) == (16, 12)
    assert output.is_file() and output.stat().st_size > 0
    reader = cv2.VideoCapture(str(output))
    assert int(reader.get(cv2.CAP_PROP_FRAME_WIDTH)) == 16
    assert int(reader.get(cv2.CAP_PROP_FRAME_HEIGHT)) == 12
    reader.release()
    assert proxy_cache_path(source) == proxy_cache_path(source)


def test_analysis_jobs_abort_without_leaving_partial_proxy(tmp_path):
    source = tmp_path / "cancel.mp4"
    output = tmp_path / "cache" / "proxy.mp4"
    _write_test_video(source)

    def cancelled():
        return True

    with pytest.raises(JobCancelled):
        build_video_proxy(source, output, max_width=16, cancelled=cancelled)
    with pytest.raises(JobCancelled):
        detect_scene_cuts(str(source), "OpenCV", cancelled=cancelled)
    with pytest.raises(JobCancelled):
        find_similar_frames(str(source), "OpenCV", cancelled=cancelled)

    assert not output.exists()
    assert not list(output.parent.glob(".*.partial.mp4"))


def test_cancellation_token_is_one_way():
    token = CancellationToken()
    assert not token.is_cancelled()
    token.cancel()
    assert token.is_cancelled()


def test_thumbnail_indices_cover_the_full_video():
    assert thumbnail_frame_indices(100, 4) == [0, 33, 66, 99]
    assert thumbnail_frame_indices(1, 18) == [0]
    assert thumbnail_frame_indices(0, 18) == []


def test_scene_detection_marks_histogram_cuts(tmp_path):
    path = tmp_path / "scenes.mp4"
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (32, 24)
    )
    assert writer.isOpened()
    for value in ([0] * 8) + ([220] * 8):
        writer.write(np.full((24, 32, 3), value, dtype=np.uint8))
    writer.release()
    cuts = detect_scene_cuts(str(path), "OpenCV", threshold=0.4, min_gap_frames=3)
    assert any(7 <= cut <= 9 for cut in cuts)


def test_perceptual_hashes_and_similarity_search(tmp_path):
    frame = np.zeros((24, 32, 3), dtype=np.uint8)
    altered = frame.copy()
    altered[4:12, 8:20] = 255
    digest = perceptual_hash(frame)
    assert perceptual_hash(frame) == digest
    assert hamming_distance(digest, digest ^ 0b1011) == 3
    assert hamming_distance(digest, perceptual_hash(altered)) > 0

    path = tmp_path / "similar.mp4"
    _write_test_video(path)
    result = find_similar_frames(
        str(path), "OpenCV", threshold=0, sample_step=1,
    )
    assert result["scanned"] == 5
    assert result["matches"]
    assert all(match["frame"] > match["similar_to"] for match in result["matches"])


def test_qr_detection_decodes_current_frame():
    if not hasattr(cv2, "QRCodeEncoder_create"):
        pytest.skip("OpenCV QR encoder is unavailable")
    encoded = cv2.QRCodeEncoder_create().encode("framesnap-test")
    encoded = cv2.copyMakeBorder(
        encoded, 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=255
    )
    encoded = cv2.resize(encoded, None, fx=12, fy=12,
                         interpolation=cv2.INTER_NEAREST)
    frame = cv2.cvtColor(encoded, cv2.COLOR_GRAY2BGR)
    codes = detect_codes(frame)
    assert any(code["type"] == "QR" and code["data"] == "framesnap-test"
               for code in codes)


def test_chapter_extraction_handles_container_without_chapters(tmp_path):
    path = tmp_path / "no-chapters.mp4"
    _write_test_video(path)
    assert extract_chapters(str(path)) == []
