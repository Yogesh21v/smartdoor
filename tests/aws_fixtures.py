"""
A pytest fixture that spins up mocked S3, both DynamoDB tables, and an SNS
topic (all via moto) matching the real infra/template.yaml schema, so the
Lambda handlers can be tested against something that behaves like the real
AWS resources without any real AWS account. Rekognition itself isn't
mocked here -- moto doesn't support it -- see the per-Lambda test files for
how those calls are stubbed instead.
"""
import boto3
import pytest
from moto import mock_aws

BUCKET_NAME = "smartdoor-media-test"
AUTHORIZED_PEOPLE_TABLE = "AuthorizedPeople"
ACCESS_LOG_TABLE = "AccessLog"


@pytest.fixture
def aws():
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BUCKET_NAME)

        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")

        people_table = dynamodb.create_table(
            TableName=AUTHORIZED_PEOPLE_TABLE,
            BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[
                {"AttributeName": "FaceId", "AttributeType": "S"},
                {"AttributeName": "RecordType", "AttributeType": "S"},
                {"AttributeName": "EnrolledAt", "AttributeType": "S"},
            ],
            KeySchema=[{"AttributeName": "FaceId", "KeyType": "HASH"}],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "EnrollTimeIndex",
                    "KeySchema": [
                        {"AttributeName": "RecordType", "KeyType": "HASH"},
                        {"AttributeName": "EnrolledAt", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
        )
        people_table.wait_until_exists()

        access_log_table = dynamodb.create_table(
            TableName=ACCESS_LOG_TABLE,
            BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[
                {"AttributeName": "LogId", "AttributeType": "S"},
                {"AttributeName": "RecordType", "AttributeType": "S"},
                {"AttributeName": "Timestamp", "AttributeType": "S"},
            ],
            KeySchema=[{"AttributeName": "LogId", "KeyType": "HASH"}],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "AccessTimeIndex",
                    "KeySchema": [
                        {"AttributeName": "RecordType", "KeyType": "HASH"},
                        {"AttributeName": "Timestamp", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
        )
        access_log_table.wait_until_exists()

        sns = boto3.client("sns", region_name="us-east-1")
        topic_arn = sns.create_topic(Name="smartdoor-alerts-test")["TopicArn"]

        yield {
            "s3": s3,
            "dynamodb": dynamodb,
            "people_table": people_table,
            "access_log_table": access_log_table,
            "sns": sns,
            "topic_arn": topic_arn,
        }
