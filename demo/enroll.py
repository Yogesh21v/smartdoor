"""
Enrolls a person into SmartDoor: uploads a photo of their face straight to
S3 (using boto3 credentials on this machine, bypassing the presigned
/enroll-url API endpoint a real enrollment app would use) under
`enroll/<name>/<filename>`, then polls the /authorized-people API until
that name shows up, confirming enroll_lambda successfully indexed the face.

Usage:
    python demo/enroll.py "Yogesh Venkataramanan" path/to/photo.jpg \\
        --bucket smartdoor-media-123456789012-us-east-1 \\
        --api-url https://abc123.execute-api.us-east-1.amazonaws.com/Prod
"""
import argparse
import json
import time
import urllib.request
from pathlib import Path

import boto3


def upload_enrollment_photo(bucket: str, name: str, image_path: str) -> str:
    filename = Path(image_path).name
    key = f"enroll/{name}/{filename}"
    boto3.client("s3").upload_file(image_path, bucket, key)
    return key


def poll_for_enrollment(api_base_url: str, name: str, timeout: int = 30, interval: int = 2) -> dict:
    url = f"{api_base_url.rstrip('/')}/authorized-people"
    deadline = time.time() + timeout
    while time.time() < deadline:
        with urllib.request.urlopen(url, timeout=10) as response:
            body = json.loads(response.read())
        for person in body.get("people", []):
            if person.get("Name") == name:
                return person
        time.sleep(interval)
    raise TimeoutError(f"'{name}' was not enrolled within {timeout}s -- check the photo had a clear, single face")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("name", help="Name to enroll this face under")
    parser.add_argument("image_path")
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()

    key = upload_enrollment_photo(args.bucket, args.name, args.image_path)
    print(f"Uploaded to s3://{args.bucket}/{key}")

    person = poll_for_enrollment(args.api_url, args.name, timeout=args.timeout)
    print(f"Enrolled: {person['Name']} (FaceId {person['FaceId']}, confidence {person.get('Confidence')})")


if __name__ == "__main__":
    main()
