"""
The "real camera" version of enroll.py: instead of enrolling from a photo
you already have, this grabs a live frame from your laptop's webcam right
now and enrolls that.

Usage:
    python demo/enroll_from_webcam.py "Your Name" \\
        --bucket smartdoor-media-123456789012-us-east-1 \\
        --api-url https://abc123.execute-api.us-east-1.amazonaws.com/Prod \\
        [--camera-index 0]
"""
import argparse

from enroll import poll_for_enrollment, upload_enrollment_photo
from webcam import capture_frame


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("name", help="Name to enroll this face under")
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--camera-index", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()

    print("Capturing from webcam...")
    photo_path = capture_frame(camera_index=args.camera_index)
    print(f"Captured frame saved to {photo_path}")

    key = upload_enrollment_photo(args.bucket, args.name, photo_path)
    print(f"Uploaded to s3://{args.bucket}/{key}")

    person = poll_for_enrollment(args.api_url, args.name, timeout=args.timeout)
    print(f"Enrolled: {person['Name']} (FaceId {person['FaceId']}, confidence {person.get('Confidence')})")


if __name__ == "__main__":
    main()
