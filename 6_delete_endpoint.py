import os
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv()

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")


def load_endpoint_name() -> str:
    path = Path(".endpoint_name")
    if path.exists():
        name = path.read_text().strip()
        if name:
            return name
    return os.getenv("ENDPOINT_NAME", "multimodal-multi-lora-swissknife")


def main():
    endpoint_name = load_endpoint_name()
    sm_client = boto3.client("sagemaker", region_name=AWS_REGION)

    print("[DELETE] Deleting SageMaker endpoint to stop billing...")
    print(f"   Endpoint: {endpoint_name}")

    try:
        try:
            ep_desc = sm_client.describe_endpoint(EndpointName=endpoint_name)
            endpoint_config_name = ep_desc.get("EndpointConfigName")
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code == "ValidationException" or "Could not find" in str(e):
                print("   Endpoint does not exist or already deleted.")
                Path(".endpoint_name").unlink(missing_ok=True)
                Path(".s3_uri").unlink(missing_ok=True)
                print("[OK] Cleanup complete.")
                return
            raise

        sm_client.delete_endpoint(EndpointName=endpoint_name)
        print("   Endpoint deletion initiated...")

        if endpoint_config_name:
            try:
                sm_client.delete_endpoint_config(EndpointConfigName=endpoint_config_name)
                print(f"   Deleted endpoint config: {endpoint_config_name}")
            except ClientError:
                pass

        models = sm_client.list_models(NameContains="multi-lora-model")
        for m in models.get("Models", []):
            try:
                sm_client.delete_model(ModelName=m["ModelName"])
                print(f"   Deleted model: {m['ModelName']}")
            except ClientError:
                pass

        print("   Waiting for endpoint to be fully deleted...")
        for _ in range(60):
            try:
                sm_client.describe_endpoint(EndpointName=endpoint_name)
                time.sleep(5)
            except ClientError as e:
                if "Could not find endpoint" in str(e) or "ResourceNotFound" in str(e):
                    break
                raise

        Path(".endpoint_name").unlink(missing_ok=True)
        Path(".s3_uri").unlink(missing_ok=True)

        print("[OK] Endpoint deleted. Billing stopped. Goodbye!")

    except ClientError as e:
        if "Could not find endpoint" in str(e) or "ValidationException" in str(e):
            print("   Endpoint does not exist or already deleted.")
            Path(".endpoint_name").unlink(missing_ok=True)
            Path(".s3_uri").unlink(missing_ok=True)
            print("[OK] Cleanup complete.")
        else:
            raise


if __name__ == "__main__":
    main()
