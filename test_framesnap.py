import cv2
import numpy as np
import pytest

from framesnap import av as pyav
from framesnap import apply_template, frame_to_ms, ms_to_ts, open_cap


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
