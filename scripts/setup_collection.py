"""
Creates the Rekognition face collection SmartDoor enrolls/matches against.

CloudFormation has no native `AWS::Rekognition::Collection` resource type,
so unlike everything else in infra/template.yaml, the collection can't be
provisioned as part of `sam deploy` -- it has to be created once, before
the first deploy, with this script (and removed with
teardown_collection.py when you're done). This is standard practice for
Rekognition projects, not a workaround specific to this repo.

Usage:
    python scripts/setup_collection.py [--collection-id smartdoor-authorized-faces]
"""
import argparse

import boto3


def create_collection(collection_id: str) -> dict:
    client = boto3.client("rekognition")
    return client.create_collection(CollectionId=collection_id)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--collection-id", default="smartdoor-authorized-faces")
    args = parser.parse_args()

    response = create_collection(args.collection_id)
    print(f"Created collection '{args.collection_id}': {response['CollectionArn']}")
    print("Now deploy the stack with: sam deploy --guided")
    print(f"(pass --parameter-overrides CollectionId={args.collection_id} if you didn't use the default name)")


if __name__ == "__main__":
    main()
