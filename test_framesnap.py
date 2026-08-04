import os
import math
import json
import sys
import numpy as np
import pytest
import wave
from PIL import Image

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")
import cv2  # noqa: E402

from framesnap import av as pyav
from framesnap import (
    apply_template,
    batch_export_markers,
    burn_in_overlay,
    build_video_proxy,
    crop_frame,
    detect_scene_cuts,
    extract_audio_waveform,
    extract_chapters,
    find_similar_frames,
    ffmpeg_extract_command,
    frame_to_ms,
    hamming_distance,
    main,
    diff_session_data,
    merge_session_data,
    ms_to_ts,
    session_template_from_data,
    stylesheet_for_theme,
    THEME_NAMES,
    template_to_marks,
    open_cap,
    parse_tags,
    perceptual_hash,
    proxy_cache_path,
    export_sequence,
    ordered_mark_indices,
    thumbnail_frame_indices,
    to_uint16_frame,
)


def _write_test_video(path):
    writer = cv2.VideoWriter(
        str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (32, 24)
    )
    assert writer.isOpened()
    for index in range(5):
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
    assert result == {"exported": 2, "failed": [], "videos": 1}
    assert len(list(csv_output.glob("*.png"))) == 2

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


def test_chapter_extraction_handles_container_without_chapters(tmp_path):
    path = tmp_path / "no-chapters.mp4"
    _write_test_video(path)
    assert extract_chapters(str(path)) == []
