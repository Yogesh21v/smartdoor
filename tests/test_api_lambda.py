import json
import os
from decimal import Decimal

import pytest

from loader import load_lambda_module

API_APP_PATH = os.path.join(os.path.dirname(__file__), "..", "backend", "api_lambda", "app.py")
api_app = load_lambda_module(API_APP_PATH, "smartdoor_api_app")


def _seed_access_log(table, log_id, timestamp, decision="GRANTED", person_name="Yogesh"):
    table.put_item(
        Item={
            "LogId": log_id,
            "RecordType": "ACCESS_LOG",
            "Timestamp": timestamp,
            "Decision": decision,
            "PersonName": person_name if decision == "GRANTED" else None,
            "Similarity": Decimal("95.5") if decision == "GRANTED" else None,
            "S3Bucket": "smartdoor-media-test",
            "S3Key": f"captures/{log_id}/photo.jpg",
        }
    )


def _seed_person(table, face_id, name, enrolled_at):
    table.put_item(
        Item={
            "FaceId": face_id,
            "RecordType": "AUTHORIZED_PERSON",
            "Name": name,
            "S3Bucket": "smartdoor-media-test",
            "S3Key": f"enroll/{name}/photo.jpg",
            "Confidence": Decimal("99.8"),
            "EnrolledAt": enrolled_at,
        }
    )


def test_list_access_log_newest_first(aws):
    table = aws["access_log_table"]
    _seed_access_log(table, "log-1", "2024-01-01T00:00:00+00:00")
    _seed_access_log(table, "log-2", "2024-01-02T00:00:00+00:00")
    _seed_access_log(table, "log-3", "2024-01-03T00:00:00+00:00")

    entries = api_app.list_access_log(table, limit=10)
    assert [e["LogId"] for e in entries] == ["log-3", "log-2", "log-1"]


def test_list_authorized_people_newest_first(aws):
    table = aws["people_table"]
    _seed_person(table, "face-1", "Alice", "2024-01-01T00:00:00+00:00")
    _seed_person(table, "face-2", "Bob", "2024-01-02T00:00:00+00:00")

    people = api_app.list_authorized_people(table)
    assert [p["Name"] for p in people] == ["Bob", "Alice"]


def test_get_access_log_entry_returns_none_for_missing(aws):
    assert api_app.get_access_log_entry(aws["access_log_table"], "nope") is None


def test_handle_list_access_log_returns_200(aws):
    _seed_access_log(aws["access_log_table"], "log-1", "2024-01-01T00:00:00+00:00")
    event = {"queryStringParameters": None}
    response = api_app._handle_list_access_log(event, aws["access_log_table"])
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert len(body["entries"]) == 1


def test_handle_list_access_log_rejects_bad_limit(aws):
    event = {"queryStringParameters": {"limit": "abc"}}
    response = api_app._handle_list_access_log(event, aws["access_log_table"])
    assert response["statusCode"] == 400


def test_handle_get_access_log_entry_404(aws):
    event = {"pathParameters": {"logId": "nope"}}
    response = api_app._handle_get_access_log_entry(event, aws["access_log_table"])
    assert response["statusCode"] == 404


def test_handle_get_access_log_entry_converts_decimals(aws):
    _seed_access_log(aws["access_log_table"], "log-9", "2024-01-01T00:00:00+00:00")
    event = {"pathParameters": {"logId": "log-9"}}
    response = api_app._handle_get_access_log_entry(event, aws["access_log_table"])
    body = json.loads(response["body"])
    assert body["Similarity"] == pytest.approx(95.5)


def test_handle_list_authorized_people(aws):
    _seed_person(aws["people_table"], "face-1", "Alice", "2024-01-01T00:00:00+00:00")
    event = {}
    response = api_app._handle_list_authorized_people(event, aws["people_table"])
    body = json.loads(response["body"])
    assert body["people"][0]["Name"] == "Alice"


def test_handle_enroll_url_requires_name_and_filename():
    event = {"body": json.dumps({"filename": "photo.jpg"})}
    response = api_app._handle_enroll_url(event)
    assert response["statusCode"] == 400


def test_handle_enroll_url_builds_correct_key(monkeypatch):
    monkeypatch.setattr(api_app, "generate_presigned_put", lambda key: f"https://example.com/{key}?signed=1")
    event = {"body": json.dumps({"name": "Yogesh", "filename": "photo.jpg"})}
    response = api_app._handle_enroll_url(event)
    body = json.loads(response["body"])
    assert body["key"] == "enroll/Yogesh/photo.jpg"


def test_handle_capture_url_generates_capture_id(monkeypatch):
    monkeypatch.setattr(api_app, "generate_presigned_put", lambda key: f"https://example.com/{key}?signed=1")
    event = {"body": json.dumps({"filename": "photo.jpg"})}
    response = api_app._handle_capture_url(event)
    body = json.loads(response["body"])
    assert body["key"] == f"captures/{body['captureId']}/photo.jpg"


def test_handle_capture_url_requires_filename():
    event = {"body": json.dumps({})}
    response = api_app._handle_capture_url(event)
    assert response["statusCode"] == 400


def test_lambda_handler_routes_all_endpoints(aws, monkeypatch):
    monkeypatch.setattr(api_app, "generate_presigned_put", lambda key: "https://example.com/signed")

    assert api_app.lambda_handler({"httpMethod": "GET", "path": "/access-log", "queryStringParameters": None}, None)["statusCode"] == 200
    assert api_app.lambda_handler({"httpMethod": "GET", "path": "/authorized-people"}, None)["statusCode"] == 200
    assert api_app.lambda_handler(
        {"httpMethod": "POST", "path": "/enroll-url", "body": json.dumps({"name": "A", "filename": "x.jpg"})}, None
    )["statusCode"] == 200
    assert api_app.lambda_handler(
        {"httpMethod": "POST", "path": "/capture-url", "body": json.dumps({"filename": "x.jpg"})}, None
    )["statusCode"] == 200
    assert api_app.lambda_handler({"httpMethod": "DELETE", "path": "/access-log"}, None)["statusCode"] == 404
