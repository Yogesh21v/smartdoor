import os

import pytest

from loader import load_lambda_module

ENROLL_APP_PATH = os.path.join(os.path.dirname(__file__), "..", "backend", "enroll_lambda", "app.py")
enroll_app = load_lambda_module(ENROLL_APP_PATH, "enroll_app")

# A realistic (trimmed to the fields this project reads) Rekognition
# IndexFaces response, used to test build_enrollment_record() without ever
# calling AWS -- moto doesn't support Rekognition, so this fixture stands in
# for it.
SAMPLE_INDEX_FACES_RESPONSE = {
    "FaceRecords": [
        {
            "Face": {
                "FaceId": "aaaa1111-bbbb-2222-cccc-333344445555",
                "ExternalImageId": "Yogesh Venkataramanan",
                "Confidence": 99.87,
            }
        }
    ]
}

NO_FACE_RESPONSE = {"FaceRecords": []}


def test_parse_name_from_key_extracts_and_decodes_name():
    key = "enroll/Yogesh%20Venkataramanan/photo1.jpg"
    assert enroll_app.parse_name_from_key(key) == "Yogesh Venkataramanan"


def test_parse_name_from_key_handles_plus_encoded_spaces():
    key = "enroll/Yogesh+Venkataramanan/photo1.jpg"
    assert enroll_app.parse_name_from_key(key) == "Yogesh Venkataramanan"


def test_parse_name_from_key_raises_for_malformed_key():
    with pytest.raises(ValueError):
        enroll_app.parse_name_from_key("enroll/justonesegment.jpg")


def test_build_enrollment_record_extracts_face_id_and_confidence():
    record = enroll_app.build_enrollment_record(
        "Yogesh Venkataramanan", "my-bucket", "enroll/Yogesh/photo1.jpg", SAMPLE_INDEX_FACES_RESPONSE
    )
    assert record["FaceId"] == "aaaa1111-bbbb-2222-cccc-333344445555"
    assert record["Name"] == "Yogesh Venkataramanan"
    assert record["Confidence"] == pytest.approx(99.87)
    assert record["RecordType"] == "AUTHORIZED_PERSON"


def test_build_enrollment_record_returns_none_when_no_face_found():
    record = enroll_app.build_enrollment_record("Someone", "my-bucket", "enroll/Someone/blurry.jpg", NO_FACE_RESPONSE)
    assert record is None


def test_process_s3_record_enrolls_successfully(aws, monkeypatch):
    monkeypatch.setattr(enroll_app, "enroll_face", lambda bucket, key, name: SAMPLE_INDEX_FACES_RESPONSE)

    record = {
        "s3": {
            "bucket": {"name": "smartdoor-media-test"},
            "object": {"key": "enroll/Yogesh+Venkataramanan/photo1.jpg"},
        }
    }
    result = enroll_app.process_s3_record(record, aws["people_table"])

    assert result["enrolled"] is True
    assert result["item"]["Name"] == "Yogesh Venkataramanan"

    stored = aws["people_table"].get_item(Key={"FaceId": "aaaa1111-bbbb-2222-cccc-333344445555"}).get("Item")
    assert stored is not None
    assert stored["Name"] == "Yogesh Venkataramanan"


def test_process_s3_record_reports_failure_when_no_face_found(aws, monkeypatch):
    monkeypatch.setattr(enroll_app, "enroll_face", lambda bucket, key, name: NO_FACE_RESPONSE)

    record = {
        "s3": {
            "bucket": {"name": "smartdoor-media-test"},
            "object": {"key": "enroll/Someone/blurry.jpg"},
        }
    }
    result = enroll_app.process_s3_record(record, aws["people_table"])
    assert result["enrolled"] is False
    assert result["name"] == "Someone"


def test_lambda_handler_processes_all_records_in_batch(aws, monkeypatch):
    monkeypatch.setattr(enroll_app, "enroll_face", lambda bucket, key, name: SAMPLE_INDEX_FACES_RESPONSE)

    event = {
        "Records": [
            {"s3": {"bucket": {"name": "smartdoor-media-test"}, "object": {"key": "enroll/A/1.jpg"}}},
            {"s3": {"bucket": {"name": "smartdoor-media-test"}, "object": {"key": "enroll/B/2.jpg"}}},
        ]
    }
    result = enroll_app.lambda_handler(event, None)
    assert result["processed"] == 2
    assert all(r["enrolled"] for r in result["results"])
