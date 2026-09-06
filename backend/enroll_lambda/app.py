"""
S3-triggered Lambda: enrolls a new authorized person into the SmartDoor
Rekognition face collection. Triggered by an upload to
`enroll/<person-name>/<filename>` -- the person's name is embedded in the
S3 key by whoever uploads it (see demo/enroll.py), the same client-chosen-
identifier pattern used elsewhere in this account's rebuilt projects.

Calls Rekognition's IndexFaces, which both detects the face in the photo
*and* adds it to the collection in one call, returning a FaceId used as
that person's unique identifier from then on (a person can be re-enrolled
with multiple photos -- each gets its own FaceId, all tagged with the same
ExternalImageId so recognize_lambda can report a name, not just a FaceId).
"""
import os
import re
import urllib.parse
from datetime import datetime, timezone
from decimal import Decimal

import boto3

_rekognition = boto3.client("rekognition")
_dynamodb = boto3.resource("dynamodb")

TABLE_NAME = os.environ.get("AUTHORIZED_PEOPLE_TABLE", "AuthorizedPeople")
COLLECTION_ID = os.environ.get("COLLECTION_ID", "smartdoor-authorized-faces")
RECORD_TYPE = "AUTHORIZED_PERSON"
ENROLL_PREFIX = "enroll/"

_NAME_FROM_KEY_RE = re.compile(rf"^{re.escape(ENROLL_PREFIX)}([^/]+)/")


def parse_name_from_key(key: str) -> str:
    """Extracts and URL-decodes the person's name from an
    'enroll/<name>/<filename>' key. Raises ValueError for a key that
    doesn't match that shape, since (unlike a missing image id elsewhere in
    this account) there's no reasonable fallback for "whose face is this"."""
    match = _NAME_FROM_KEY_RE.match(key)
    if not match:
        raise ValueError(f"enrollment key {key!r} doesn't match 'enroll/<name>/<filename>'")
    return urllib.parse.unquote_plus(match.group(1))


def enroll_face(bucket: str, key: str, name: str) -> dict:
    """Calls Rekognition IndexFaces. Split out so tests can stub just this
    one AWS call (moto doesn't support Rekognition)."""
    return _rekognition.index_faces(
        CollectionId=COLLECTION_ID,
        Image={"S3Object": {"Bucket": bucket, "Name": key}},
        ExternalImageId=name,
        MaxFaces=1,
        QualityFilter="AUTO",
        DetectionAttributes=[],
    )


def build_enrollment_record(name: str, bucket: str, key: str, index_faces_response: dict, enrolled_at: str = None) -> dict:
    """Pure function: an IndexFaces response -> the DynamoDB item this
    project stores, or None if no usable face was found in the photo (a
    blurry photo, sunglasses, etc. can all make IndexFaces return zero
    FaceRecords even though it didn't error)."""
    face_records = index_faces_response.get("FaceRecords", [])
    if not face_records:
        return None

    face = face_records[0]["Face"]
    return {
        "FaceId": face["FaceId"],
        "RecordType": RECORD_TYPE,
        "Name": name,
        "S3Bucket": bucket,
        "S3Key": key,
        "Confidence": face.get("Confidence"),
        "EnrolledAt": enrolled_at or datetime.now(timezone.utc).isoformat(),
    }


def _floats_to_decimal(value):
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _floats_to_decimal(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_floats_to_decimal(v) for v in value]
    return value


def process_s3_record(record: dict, table) -> dict:
    bucket = record["s3"]["bucket"]["name"]
    key = record["s3"]["object"]["key"].replace("+", " ")
    name = parse_name_from_key(key)

    response = enroll_face(bucket, key, name)
    item = build_enrollment_record(name, bucket, key, response)
    if item is None:
        return {"enrolled": False, "name": name, "reason": "no usable face detected in photo"}

    table.put_item(Item=_floats_to_decimal(item))
    return {"enrolled": True, "item": item}


def lambda_handler(event, context):
    table = _dynamodb.Table(TABLE_NAME)
    results = [process_s3_record(record, table) for record in event.get("Records", [])]
    return {"processed": len(results), "results": results}
