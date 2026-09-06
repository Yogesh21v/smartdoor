import os

import pytest

from loader import load_lambda_module

RECOGNIZE_APP_PATH = os.path.join(os.path.dirname(__file__), "..", "backend", "recognize_lambda", "app.py")
recognize_app = load_lambda_module(RECOGNIZE_APP_PATH, "recognize_app")


def _match(name, similarity):
    return {"Similarity": similarity, "Face": {"ExternalImageId": name}}


def test_parse_capture_id_from_key_extracts_client_chosen_id():
    key = "captures/6b1f2b2e-27b2-4b8a-9a4c-111111111111/snapshot.jpg"
    assert recognize_app.parse_capture_id_from_key(key) == "6b1f2b2e-27b2-4b8a-9a4c-111111111111"


def test_parse_capture_id_from_key_falls_back_for_unrecognized_shape():
    capture_id = recognize_app.parse_capture_id_from_key("captures/random.jpg")
    assert isinstance(capture_id, str) and len(capture_id) > 0


def test_decide_access_no_face_detected_when_matches_is_none():
    outcome = recognize_app.decide_access(None)
    assert outcome == {"decision": "NO_FACE_DETECTED", "person_name": None, "similarity": None}


def test_decide_access_denied_when_no_matches_at_all():
    outcome = recognize_app.decide_access([])
    assert outcome["decision"] == "DENIED"
    assert outcome["person_name"] is None


def test_decide_access_granted_above_threshold():
    outcome = recognize_app.decide_access([_match("Yogesh", 95.5)], threshold=80)
    assert outcome["decision"] == "GRANTED"
    assert outcome["person_name"] == "Yogesh"
    assert outcome["similarity"] == pytest.approx(95.5)


def test_decide_access_denied_below_threshold():
    # A face was matched, but too weakly to trust.
    outcome = recognize_app.decide_access([_match("Yogesh", 60.0)], threshold=80)
    assert outcome["decision"] == "DENIED"
    assert outcome["person_name"] is None
    assert outcome["similarity"] == pytest.approx(60.0)


def test_decide_access_picks_the_best_of_multiple_matches():
    outcome = recognize_app.decide_access(
        [_match("Alice", 82.0), _match("Bob", 91.2)], threshold=80
    )
    assert outcome["person_name"] == "Bob"
    assert outcome["similarity"] == pytest.approx(91.2)


def test_build_access_log_record_shape():
    outcome = {"decision": "GRANTED", "person_name": "Yogesh", "similarity": 95.5}
    record = recognize_app.build_access_log_record("cap-1", "my-bucket", "captures/cap-1/x.jpg", outcome)
    assert record["LogId"] == "cap-1"
    assert record["Decision"] == "GRANTED"
    assert record["PersonName"] == "Yogesh"
    assert record["RecordType"] == "ACCESS_LOG"


def test_process_s3_record_granted_does_not_notify(aws, monkeypatch):
    monkeypatch.setattr(recognize_app, "search_face", lambda b, k: {"FaceMatches": [_match("Yogesh", 95.0)]})
    published = []
    monkeypatch.setattr(recognize_app._sns, "publish", lambda **kwargs: published.append(kwargs))
    monkeypatch.setattr(recognize_app, "ALERT_TOPIC_ARN", aws["topic_arn"])

    record = {
        "s3": {"bucket": {"name": "smartdoor-media-test"}, "object": {"key": "captures/cap-1/photo.jpg"}}
    }
    item = recognize_app.process_s3_record(record, aws["access_log_table"])

    assert item["Decision"] == "GRANTED"
    assert item["PersonName"] == "Yogesh"
    assert published == []  # no alert for a clean match


def test_process_s3_record_denied_sends_notification(aws, monkeypatch):
    monkeypatch.setattr(recognize_app, "search_face", lambda b, k: {"FaceMatches": []})
    published = []
    monkeypatch.setattr(recognize_app._sns, "publish", lambda **kwargs: published.append(kwargs))
    monkeypatch.setattr(recognize_app, "ALERT_TOPIC_ARN", aws["topic_arn"])

    record = {
        "s3": {"bucket": {"name": "smartdoor-media-test"}, "object": {"key": "captures/cap-2/photo.jpg"}}
    }
    item = recognize_app.process_s3_record(record, aws["access_log_table"])

    assert item["Decision"] == "DENIED"
    assert len(published) == 1
    assert published[0]["TopicArn"] == aws["topic_arn"]
    assert "unrecognized visitor" in published[0]["Message"]


def test_process_s3_record_no_face_detected_sends_notification(aws, monkeypatch):
    def _raise_no_face(bucket, key):
        raise recognize_app.NoFaceDetectedError("no face in image")

    monkeypatch.setattr(recognize_app, "search_face", _raise_no_face)
    published = []
    monkeypatch.setattr(recognize_app._sns, "publish", lambda **kwargs: published.append(kwargs))
    monkeypatch.setattr(recognize_app, "ALERT_TOPIC_ARN", aws["topic_arn"])

    record = {
        "s3": {"bucket": {"name": "smartdoor-media-test"}, "object": {"key": "captures/cap-3/empty_porch.jpg"}}
    }
    item = recognize_app.process_s3_record(record, aws["access_log_table"])

    assert item["Decision"] == "NO_FACE_DETECTED"
    assert len(published) == 1
    assert "no face was visible" in published[0]["Message"]


def test_process_s3_record_no_notification_without_topic_configured(aws, monkeypatch):
    monkeypatch.setattr(recognize_app, "search_face", lambda b, k: {"FaceMatches": []})
    published = []
    monkeypatch.setattr(recognize_app._sns, "publish", lambda **kwargs: published.append(kwargs))
    monkeypatch.setattr(recognize_app, "ALERT_TOPIC_ARN", "")  # not configured

    record = {
        "s3": {"bucket": {"name": "smartdoor-media-test"}, "object": {"key": "captures/cap-4/photo.jpg"}}
    }
    recognize_app.process_s3_record(record, aws["access_log_table"])
    assert published == []


def test_lambda_handler_processes_all_records(aws, monkeypatch):
    monkeypatch.setattr(recognize_app, "search_face", lambda b, k: {"FaceMatches": [_match("Yogesh", 95.0)]})
    monkeypatch.setattr(recognize_app, "ALERT_TOPIC_ARN", "")

    event = {
        "Records": [
            {"s3": {"bucket": {"name": "smartdoor-media-test"}, "object": {"key": "captures/a/1.jpg"}}},
            {"s3": {"bucket": {"name": "smartdoor-media-test"}, "object": {"key": "captures/b/2.jpg"}}},
        ]
    }
    result = recognize_app.lambda_handler(event, None)
    assert result["processed"] == 2
