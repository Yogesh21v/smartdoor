"""
The "real camera" version of simulate_visitor.py: instead of uploading a
photo you already have, this grabs a live frame from your laptop's webcam
right now, then runs it through the exact same upload-and-poll flow.

Usage:
    python demo/simulate_visitor_from_webcam.py \\
        --bucket smartdoor-media-123456789012-us-east-1 \\
        --api-url https://abc123.execute-api.us-east-1.amazonaws.com/Prod \\
        [--camera-index 0]
"""
import argparse

from simulate_visitor import poll_for_decision, print_decision, upload_capture
from webcam import capture_frame


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--camera-index", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()

    print("Capturing from webcam...")
    photo_path = capture_frame(camera_index=args.camera_index)
    print(f"Captured frame saved to {photo_path}")

    capture_id, key = upload_capture(args.bucket, photo_path)
    print(f"Uploaded to s3://{args.bucket}/{key}  (capture id: {capture_id})")

    entry = poll_for_decision(args.api_url, capture_id, timeout=args.timeout)
    print_decision(entry)


if __name__ == "__main__":
    main()
