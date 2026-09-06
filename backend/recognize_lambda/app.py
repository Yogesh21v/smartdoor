"""
S3-triggered Lambda: the "someone's at the door" side of SmartDoor.
Triggered by an upload to `captures/<capture-id>/<filename>` (a simulated
doorbell snapshot -- see demo/simulate_visitor.py), it searches the
Rekognition face collection for a match, logs the outcome to DynamoDB, and
publishes an SNS alert for anything that isn't a clean match against an
enrolled person.
"""
import os
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import boto3

_rekognition = boto3.client("rekognition")
_dynamodb = boto3.resource("dynamodb")
_sns = boto3.client("sns")

ACCESS_LOG_TABLE = os.environ.get("ACCESS_LOG_TABLE", "AccessLog")
COLLECTION_ID = os.environ.get("COLLECTION_ID", "smartdoor-authorized-faces")
ALERT_TOPIC_ARN = os.environ.get("ALERT_TOPIC_ARN", "")
SIMILARITY_THRESHOLD = float(os.environ.get("SIMILARITY_THRESHOLD", "80"))
RECORD_TYPE = "ACCESS_LOG"
CAPTURE_PREFIX = "captures/"

_CAPTURE_ID_RE = re.compile(rf"^{re.escape(CAPTURE_PREFIX)}([^/]+)/")


class NoFaceDetectedError(Exception):
    """Raised when Rekognition can't find any face at all in the captured
    image (as opposed to finding a face that just doesn't match anyone
    enrolled) -- e.g. the doorbell caught an empty porch or a package."""


def parse_capture_id_from_key(key: str) -> str:
    """Extracts the client-chosen capture id from a
    'captures/<capture-id>/<filename>' key, falling back to a fresh uuid4
    for a key that doesn't match that shape."""
    match = _CAPTURE_ID_RE.match(key)
    if match:
        return match.group(1)
    return str(uuid.uuid4())


def search_face(bucket: str, key: str) -> dict:
    """Calls Rekognition SearchFacesByImage. Split out so tests can stub
    just this one AWS call (moto doesn't support Rekognition). Rekognition
    itself raises InvalidParameterException when it can't find any face in
    the source image at all -- translated here to NoFaceDetectedError so
    callers don't need to know a Rekognition-specific exception type."""
    try:
        return _rekognition.search_faces_by_image(
            CollectionId=COLLECTION_ID,
            Image={"S3Object": {"Bucket": bucket, "Name": key}},
            FaceMatchThreshold=SIMILARITY_THRESHOLD,
            MaxFaces=1,
        )
    except _rekognition.exceptions.InvalidParameterException as e:
        raise NoFaceDetectedError(str(e)) from e


def decide_access(face_matches, threshold: float = SIMILARITY_THRESHOLD) -> dict:
    """Pure decision logic, kept free of any AWS I/O:
    - face_matches is None            -> no face was visible in the capture at all
    - face_matches is an empty list   -> a face was visible but matched no one enrolled
    - otherwise                       -> the best match decides GRANTED/DENIED against `threshold`
    """
    if face_matches is None:
        return {"decision": "NO_FACE_DETECTED", "person_name": None, "similarity": None}
    if not face_matches:
        return {"decision": "DENIED", "person_name": None, "similarity": None}

    top_match = max(face_matches, key=lambda m: m["Similarity"])
    similarity = top_match["Similarity"]
    if similarity >= threshold:
        return {"decision": "GRANTED", "person_name": top_match["Face"]["ExternalImageId"], "similarity": similarity}
    return {"decision": "DENIED", "person_name": None, "similarity": similarity}


def build_access_log_record(capture_id: str, bucket: str, key: str, outcome: dict, timestamp: str = None) -> dict:
    return {
        "LogId": capture_id,
        "RecordType": RECORD_TYPE,
        "Timestamp": timestamp or datetime.now(timezone.utc).isoformat(),
        "Decision": outcome["decision"],
        "PersonName": outcome["person_name"],
        "Similarity": outcome["similarity"],
        "S3Bucket": bucket,
        "S3Key": key,
    }


def _floats_to_decimal(value):
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _floats_to_decimal(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_floats_to_decimal(v) for v in value]
    return value


def notify_alert(item: dict) -> None:
    """Publishes an SNS alert for anything other than a clean GRANTED
    match. A no-op if ALERT_TOPIC_ARN isn't configured (e.g. running
    locally without a real SNS topic)."""
    if not ALERT_TOPIC_ARN:
        return

    if item["Decision"] == "NO_FACE_DETECTED":
        message = f"SmartDoor: motion detected at the door but no face was visible (capture {item['LogId']})."
    else:
        message = f"SmartDoor: unrecognized visitor at the door (capture {item['LogId']})."

    _sns.publish(TopicArn=ALERT_TOPIC_ARN, Subject="SmartDoor Alert", Message=message)


def process_s3_record(record: dict, table) -> dict:
    bucket = record["s3"]["bucket"]["name"]
    key = record["s3"]["object"]["key"].replace("+", " ")
    capture_id = parse_capture_id_from_key(key)

    try:
        response = search_face(bucket, key)
        face_matches = response.get("FaceMatches", [])
    except NoFaceDetectedError:
        face_matches = None

    outcome = decide_access(face_matches)
    item = build_access_log_record(capture_id, bucket, key, outcome)
    table.put_item(Item=_floats_to_decimal(item))

    if outcome["decision"] != "GRANTED":
        notify_alert(item)

    return item


def lambda_handler(event, context):
    table = _dynamodb.Table(ACCESS_LOG_TABLE)
    items = [process_s3_record(record, table) for record in event.get("Records", [])]
    return {"processed": len(items), "items": items}
