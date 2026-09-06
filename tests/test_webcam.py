"""
Tests demo/webcam.py's capture logic against a fake cv2.VideoCapture --
there's obviously no real webcam available in a CI/test environment, so
these verify the warmup-frame discarding and error handling instead of
actual image capture.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "demo"))

import webcam  # noqa: E402


class FakeCapture:
    """Stands in for cv2.VideoCapture: `reads` is a list of (ok, frame)
    tuples returned in order, one per .read() call."""

    def __init__(self, opened=True, reads=None):
        self._opened = opened
        self._reads = list(reads or [])
        self.released = False

    def isOpened(self):
        return self._opened

    def read(self):
        if not self._reads:
            return False, None
        return self._reads.pop(0)

    def release(self):
        self.released = True


def test_capture_frame_raises_if_camera_will_not_open(monkeypatch):
    monkeypatch.setattr(webcam.cv2, "VideoCapture", lambda index: FakeCapture(opened=False))
    with pytest.raises(RuntimeError, match="Could not open camera"):
        webcam.capture_frame(camera_index=0)


def test_capture_frame_raises_if_no_frame_returned(monkeypatch):
    fake = FakeCapture(opened=True, reads=[(False, None)])
    monkeypatch.setattr(webcam.cv2, "VideoCapture", lambda index: fake)
    with pytest.raises(RuntimeError, match="did not return a frame"):
        webcam.capture_frame(camera_index=0, warmup_frames=1)
    assert fake.released  # camera must be released even on failure


def test_capture_frame_discards_warmup_frames_and_saves_last_one(monkeypatch, tmp_path):
    sentinel_frame = "final-frame-data"
    reads = [(True, "warmup-1"), (True, "warmup-2"), (True, sentinel_frame)]
    fake = FakeCapture(opened=True, reads=reads)
    monkeypatch.setattr(webcam.cv2, "VideoCapture", lambda index: fake)

    written = {}

    def fake_imwrite(path, frame):
        written["path"] = path
        written["frame"] = frame
        return True

    monkeypatch.setattr(webcam.cv2, "imwrite", fake_imwrite)

    save_path = str(tmp_path / "out.jpg")
    result_path = webcam.capture_frame(camera_index=0, warmup_frames=3, save_path=save_path)

    assert result_path == save_path
    assert written["frame"] == sentinel_frame  # the *last* read frame, not an earlier warmup one
    assert fake.released


def test_capture_frame_generates_a_temp_path_when_none_given(monkeypatch):
    fake = FakeCapture(opened=True, reads=[(True, "frame")])
    monkeypatch.setattr(webcam.cv2, "VideoCapture", lambda index: fake)
    monkeypatch.setattr(webcam.cv2, "imwrite", lambda path, frame: True)

    result_path = webcam.capture_frame(camera_index=0, warmup_frames=1)
    assert result_path.endswith(".jpg")
    assert "smartdoor_capture_" in result_path


def test_capture_frame_raises_if_imwrite_fails(monkeypatch, tmp_path):
    fake = FakeCapture(opened=True, reads=[(True, "frame")])
    monkeypatch.setattr(webcam.cv2, "VideoCapture", lambda index: fake)
    monkeypatch.setattr(webcam.cv2, "imwrite", lambda path, frame: False)

    with pytest.raises(RuntimeError, match="Failed to write"):
        webcam.capture_frame(camera_index=0, warmup_frames=1, save_path=str(tmp_path / "out.jpg"))


def test_capture_frame_releases_camera_even_when_imwrite_raises(monkeypatch, tmp_path):
    fake = FakeCapture(opened=True, reads=[(True, "frame")])
    monkeypatch.setattr(webcam.cv2, "VideoCapture", lambda index: fake)

    def broken_imwrite(path, frame):
        raise OSError("disk full")

    monkeypatch.setattr(webcam.cv2, "imwrite", broken_imwrite)

    with pytest.raises(OSError):
        webcam.capture_frame(camera_index=0, warmup_frames=1, save_path=str(tmp_path / "out.jpg"))
    assert fake.released
