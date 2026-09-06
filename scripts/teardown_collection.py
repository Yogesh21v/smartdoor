"""
Deletes the Rekognition face collection created by setup_collection.py.
Run this *after* tearing down the CloudFormation stack (`sam delete`) --
deleting the collection first just means the deployed Lambdas would start
failing IndexFaces/SearchFacesByImage calls against a collection that no
longer exists, for no benefit.

Usage:
    python scripts/teardown_collection.py [--collection-id smartdoor-authorized-faces]
"""
import argparse

import boto3


def delete_collection(collection_id: str) -> dict:
    client = boto3.client("rekognition")
    return client.delete_collection(CollectionId=collection_id)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--collection-id", default="smartdoor-authorized-faces")
    args = parser.parse_args()

    delete_collection(args.collection_id)
    print(f"Deleted collection '{args.collection_id}'.")


if __name__ == "__main__":
    main()
