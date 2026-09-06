"""
Simulates a doorbell capture: uploads a photo straight to S3 (bypassing the
presigned /capture-url endpoint a real doorbell device would use) under
`captures/<capture-id>/<filename>`, using a client-chosen capture id so this
script can poll /access-log/{captureId} for the exact result immediately
after upload, then prints the GRANTED/DENIED/NO_FACE_DETECTED decision.

Usage:
    python demo/simulate_visitor.py path/to/photo.jpg \\
        --bucket smartdoor-media-123456789012-us-east-1 \\
        --api-url https://abc123.execute-api.us-east-1.amazonaws.com/Prod
"""
import argparse
import json
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import boto3


def upload_capture(bucket: str, image_path: str) -> tuple[str, str]:
    capture_id = str(uuid.uuid4())
    filename = Path(image_path).name
    key = f"captures/{capture_id}/{filename}"
    boto3.client("s3").upload_file(image_path, bucket, key)
    return capture_id, key


def poll_for_decision(api_base_url: str, capture_id: str, timeout: int = 30, interval: int = 2) -> dict:
    url = f"{api_base_url.rstrip('/')}/access-log/{capture_id}"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=10) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
        time.sleep(interval)
    raise TimeoutError(f"No access decision for capture {capture_id} after {timeout}s")


def print_decision(entry: dict) -> None:
    decision = entry["Decision"]
    if decision == "GRANTED":
        print(f"ACCESS GRANTED -- welcome, {entry['PersonName']} (similarity {entry['Similarity']:.1f}%)")
    elif decision == "DENIED":
        print("ACCESS DENIED -- face detected but not recognized as an authorized person")
    else:
        print("NO FACE DETECTED -- nothing to check access for")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("image_path")
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()

    capture_id, key = upload_capture(args.bucket, args.image_path)
    print(f"Uploaded to s3://{args.bucket}/{key}  (capture id: {capture_id})")

    entry = poll_for_decision(args.api_url, capture_id, timeout=args.timeout)
    print_decision(entry)


if __name__ == "__main__":
    main()
