import cv2
import math
import numpy as np
import pytest
import wave

from framesnap import av as pyav
from framesnap import (
    apply_template,
    build_video_proxy,
    extract_audio_waveform,
    frame_to_ms,
    ms_to_ts,
    open_cap,
    proxy_cache_path,
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
