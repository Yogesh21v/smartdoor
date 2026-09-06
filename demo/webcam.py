"""
Grabs a single still frame from a local webcam -- this is what the real
SmartDoor project actually used as its "camera" (a laptop's built-in
webcam standing in for a real doorbell camera), rather than a pre-existing
photo file. `simulate_visitor.py` and `enroll.py` work from a photo you
already have; the `*_from_webcam.py` scripts in this folder use this
module to capture one live instead.
"""
import os
import tempfile

import cv2


def capture_frame(camera_index: int = 0, warmup_frames: int = 5, save_path: str = None) -> str:
    """Opens the given camera, discards a few "warmup" frames, and saves
    the next one to `save_path` (a new temp file if not given). Warmup
    frames matter because most webcams return dark or miscalibrated frames
    for the first several reads right after opening, before auto-exposure
    and auto-white-balance settle -- skipping them is the difference
    between a usable photo and a near-black one that Rekognition can't
    find a face in.

    Returns the path the frame was saved to. Raises RuntimeError if the
    camera can't be opened or doesn't return a frame."""
    capture = cv2.VideoCapture(camera_index)
    if not capture.isOpened():
        raise RuntimeError(
            f"Could not open camera index {camera_index} -- is a webcam connected, "
            "and not already in use by another app (Zoom, Teams, etc.)?"
        )

    try:
        frame = None
        for _ in range(max(warmup_frames, 1)):
            ok, frame = capture.read()
            if not ok:
                raise RuntimeError(f"Camera index {camera_index} opened but did not return a frame")

        if save_path is None:
            fd, save_path = tempfile.mkstemp(suffix=".jpg", prefix="smartdoor_capture_")
            os.close(fd)

        if not cv2.imwrite(save_path, frame):
            raise RuntimeError(f"Failed to write captured frame to {save_path}")
        return save_path
    finally:
        capture.release()
