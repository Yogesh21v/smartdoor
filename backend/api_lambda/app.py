"""
API Gateway-backed Lambda exposing SmartDoor's stored state:

  GET  /access-log            -> recent access attempts, newest first
  GET  /access-log/{logId}    -> one access attempt's full detail
  GET  /authorized-people      -> everyone currently enrolled
  POST /enroll-url            -> presigned S3 PUT URL for a new enrollment photo
  POST /capture-url           -> presigned S3 PUT URL for a new doorbell capture

The presigned-URL endpoints are what a real doorbell device or an admin
enrollment app would call; demo/enroll.py and demo/simulate_visitor.py in
this repo instead upload straight to S3 with boto3 credentials, which is
simpler for a local demo but isn't how an actual device would authenticate.
"""
import json
import os
import uuid
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

_dynamodb = boto3.resource("dynamodb")
_s3 = boto3.client("s3")

ACCESS_LOG_TABLE = os.environ.get("ACCESS_LOG_TABLE", "AccessLog")
AUTHORIZED_PEOPLE_TABLE = os.environ.get("AUTHORIZED_PEOPLE_TABLE", "AuthorizedPeople")
MEDIA_BUCKET = os.environ.get("MEDIA_BUCKET", "")

ACCESS_LOG_GSI = "AccessTimeIndex"
AUTHORIZED_PEOPLE_GSI = "EnrollTimeIndex"
ACCESS_LOG_RECORD_TYPE = "ACCESS_LOG"
AUTHORIZED_PERSON_RECORD_TYPE = "AUTHORIZED_PERSON"


def _json_default(value):
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    return str(value)


def _response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=_json_default),
    }


def _newest_first(table, gsi_name: str, record_type: str, time_field: str, limit: int):
    """Shared newest-first listing helper for both tables: they're both
    partitioned on a constant RecordType value so all their items land in
    one logical GSI partition (a known small-scale limitation, not an
    oversight -- see the README), with a scan fallback if the GSI is
    unavailable."""
    try:
        result = table.query(
            IndexName=gsi_name,
            KeyConditionExpression=Key("RecordType").eq(record_type),
            ScanIndexForward=False,
            Limit=limit,
        )
        return result.get("Items", [])
    except Exception:
        result = table.scan(Limit=limit)
        return result.get("Items", [])


def list_access_log(table, limit: int = 20):
    return _newest_first(table, ACCESS_LOG_GSI, ACCESS_LOG_RECORD_TYPE, "Timestamp", limit)


def list_authorized_people(table, limit: int = 50):
    return _newest_first(table, AUTHORIZED_PEOPLE_GSI, AUTHORIZED_PERSON_RECORD_TYPE, "EnrolledAt", limit)


def get_access_log_entry(table, log_id: str):
    return table.get_item(Key={"LogId": log_id}).get("Item")


def generate_presigned_put(key: str) -> str:
    return _s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": MEDIA_BUCKET, "Key": key},
        ExpiresIn=300,
    )


def _handle_list_access_log(event, access_log_table):
    params = event.get("queryStringParameters") or {}
    try:
        limit = int(params.get("limit", 20))
    except (TypeError, ValueError):
        return _response(400, {"error": "limit must be an integer"})
    return _response(200, {"entries": list_access_log(access_log_table, limit=limit)})


def _handle_get_access_log_entry(event, access_log_table):
    log_id = (event.get("pathParameters") or {}).get("logId")
    if not log_id:
        return _response(400, {"error": "logId is required"})
    item = get_access_log_entry(access_log_table, log_id)
    if item is None:
        return _response(404, {"error": "not found"})
    return _response(200, item)


def _handle_list_authorized_people(event, people_table):
    return _response(200, {"people": list_authorized_people(people_table)})


def _handle_enroll_url(event):
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _response(400, {"error": "body must be valid JSON"})
    name = body.get("name")
    filename = body.get("filename")
    if not name or not filename:
        return _response(400, {"error": "name and filename are required"})
    key = f"enroll/{name}/{filename}"
    return _response(200, {"uploadUrl": generate_presigned_put(key), "key": key})


def _handle_capture_url(event):
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _response(400, {"error": "body must be valid JSON"})
    filename = body.get("filename")
    if not filename:
        return _response(400, {"error": "filename is required"})
    capture_id = str(uuid.uuid4())
    key = f"captures/{capture_id}/{filename}"
    return _response(200, {"uploadUrl": generate_presigned_put(key), "key": key, "captureId": capture_id})


def lambda_handler(event, context):
    access_log_table = _dynamodb.Table(ACCESS_LOG_TABLE)
    people_table = _dynamodb.Table(AUTHORIZED_PEOPLE_TABLE)
    method = event.get("httpMethod")
    path = event.get("path", "")

    if method == "GET" and path == "/access-log":
        return _handle_list_access_log(event, access_log_table)
    if method == "GET" and path.startswith("/access-log/"):
        return _handle_get_access_log_entry(event, access_log_table)
    if method == "GET" and path == "/authorized-people":
        return _handle_list_authorized_people(event, people_table)
    if method == "POST" and path == "/enroll-url":
        return _handle_enroll_url(event)
    if method == "POST" and path == "/capture-url":
        return _handle_capture_url(event)

    return _response(404, {"error": "not found"})
