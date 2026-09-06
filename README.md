# SmartDoor

A face-recognition access control system: enroll authorized people's
faces, then have a doorbell "capture" checked against them to decide
GRANTED / DENIED / NO_FACE_DETECTED, with the outcome logged and an alert
sent for anything that isn't a clean match.

## About this rebuild

This is a solo project. Same situation as the face-analysis-pipeline repo
in this account: I didn't have my original project files or report on
hand, so this is written from memory of the project's scope rather than
reconstructed from documentation -- a solo AWS project using Rekognition
for door access control, with enrollment, notifications, a simulated
camera/doorbell input, and an access log/history. The specific file
layout, API shape, and implementation below are freshly written and
tested, not a recovery of the original code.

## Architecture

```
Enrollment photo (enroll/<name>/<filename>)
                │  ObjectCreated event
                ▼
        EnrollFunction (Lambda)
        - Rekognition IndexFaces -> adds face to the collection,
          tagged with the person's name (ExternalImageId)
        - writes a record to DynamoDB (AuthorizedPeople)

Doorbell capture (captures/<capture-id>/<filename>)
                │  ObjectCreated event
                ▼
        RecognizeFunction (Lambda)
        - Rekognition SearchFacesByImage against the collection
        - decides GRANTED / DENIED / NO_FACE_DETECTED
        - writes a record to DynamoDB (AccessLog)
        - publishes an SNS alert for anything but GRANTED
                │
                ▼
        ApiFunction (Lambda, behind API Gateway)
        GET  /access-log             -> recent access attempts
        GET  /access-log/{logId}     -> one attempt's full detail
        GET  /authorized-people       -> everyone enrolled
        POST /enroll-url             -> presigned upload URL for enrollment
        POST /capture-url            -> presigned upload URL for a capture
```

Both the enrollment and capture flows use a client-chosen identifier
embedded in the S3 key (`enroll/<name>/...`, `captures/<capture-id>/...`)
so the uploading client can immediately poll the API for the exact result
of its own upload, rather than waiting to be told a server-assigned id --
the same pattern used in this account's other rebuilt AWS projects.

## What's in this repo

| Path | What it is |
|---|---|
| `backend/enroll_lambda/app.py` | S3-triggered: Rekognition `IndexFaces`, writes to the `AuthorizedPeople` table. |
| `backend/recognize_lambda/app.py` | S3-triggered: Rekognition `SearchFacesByImage`, decides access, writes to `AccessLog`, publishes SNS alerts. |
| `backend/api_lambda/app.py` | API Gateway-backed: list/get access log and authorized people, issue presigned upload URLs. |
| `infra/template.yaml` | AWS SAM template: S3 bucket, both DynamoDB tables (each with a GSI for newest-first listing), SNS topic, and all three Lambdas with their event bindings/IAM policies. Validated with `cfn-lint`. |
| `scripts/setup_collection.py` / `teardown_collection.py` | Creates/deletes the Rekognition face collection -- CloudFormation has no native resource type for one, so this is a one-time manual step before/after deploying the stack (standard practice for Rekognition projects, not a workaround). |
| `demo/enroll.py` | Uploads a face photo and polls until it's enrolled. |
| `demo/simulate_visitor.py` | Uploads a "doorbell capture" photo and polls for the GRANTED/DENIED decision. |
| `tests/` | Pytest suite (34 tests) covering all three Lambdas against mocked S3/DynamoDB/SNS (via `moto`) and hand-built Rekognition response fixtures (`moto` doesn't support mocking Rekognition). |

## Running the tests

```bash
pip install -r requirements.txt
cd tests && pip install -r requirements.txt
pytest -v
```

All 34 tests pass with no real AWS account needed.

## Deploying for real

```bash
python scripts/setup_collection.py                 # one-time: creates the Rekognition collection
sam build --template-file infra/template.yaml
sam deploy --guided
```

This provisions real AWS resources and will incur (small) charges --
Rekognition's `IndexFaces`/`SearchFacesByImage` calls, Lambda invocations,
DynamoDB on-demand capacity, and SNS all bill per use. After deploying:

1. Subscribe your email or phone number to the `AlertsTopicArn` stack
   output (SNS console, or `aws sns subscribe`) to actually receive alerts.
2. Enroll yourself:
   ```bash
   python demo/enroll.py "Your Name" path/to/your_photo.jpg \
       --bucket <MediaBucketName output> --api-url <ApiUrl output>
   ```
3. Simulate a visitor:
   ```bash
   python demo/simulate_visitor.py path/to/some_photo.jpg \
       --bucket <MediaBucketName output> --api-url <ApiUrl output>
   ```
   Use a photo of yourself for a GRANTED result, or anyone else's for
   DENIED (and an SNS alert).

## Notes / limitations (intentionally honest)

- Rebuilt from memory rather than from original documentation -- see
  "About this rebuild" above.
- No real camera/doorbell hardware is involved -- `demo/simulate_visitor.py`
  standing in for one, per the project's actual scope (simulated
  camera/doorbell input, not real hardware).
- Both DynamoDB tables' GSIs partition on a constant `RecordType` value, so
  every item lands in one logical partition -- a known scaling limitation
  at real scale, fine for a project this size, noted here rather than
  hidden.
- `SIMILARITY_THRESHOLD` (default 80) is a reasonable default, not a value
  tuned against a labeled dataset of real access attempts.
- Never actually deployed against real AWS as part of writing this repo --
  correctness rests on the test suite (mocked AWS + realistic Rekognition
  fixtures) and `cfn-lint` validating the CloudFormation, not a live run.
