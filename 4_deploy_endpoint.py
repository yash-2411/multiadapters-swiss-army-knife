import logging
import os
import sys
import time
from pathlib import Path

logging.getLogger("sagemaker").setLevel(logging.ERROR)
logging.getLogger("sagemaker.config").setLevel(logging.CRITICAL)
logging.getLogger("sagemaker.jumpstart").setLevel(logging.CRITICAL)

class _DevNull:
    def write(self, *_): pass
    def flush(self): pass

_old_stderr = sys.stderr
sys.stderr = _DevNull()
try:
    import sagemaker
    from sagemaker.model import Model
finally:
    sys.stderr = _old_stderr

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv()

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
S3_BUCKET = os.getenv("S3_BUCKET")
SAGEMAKER_ROLE_ARN = os.getenv("SAGEMAKER_ROLE_ARN")
HF_TOKEN = os.getenv("HF_TOKEN") or os.getenv("HUGGING_FACE_HUB_TOKEN")
ENDPOINT_NAME = os.getenv("ENDPOINT_NAME", "multimodal-multi-lora-swissknife")

CONTAINER_IMAGE = f"763104351884.dkr.ecr.{AWS_REGION}.amazonaws.com/djl-inference:0.36.0-lmi20.0.0-cu128-v1.0"
INSTANCE_TYPE = "ml.g5.xlarge"
COST_PER_HOUR = 1.41
POLL_INTERVAL = 30
MAX_POLLS = 40


def load_s3_uri() -> str:
    s3_uri_path = Path(".s3_uri")
    if not s3_uri_path.exists():
        print("[X] Run python 3_package_and_upload.py first")
        exit(1)
    s3_uri = s3_uri_path.read_text().strip()
    if not s3_uri or not s3_uri.startswith("s3://"):
        print("[X] Invalid .s3_uri content. Run python 3_package_and_upload.py again.")
        exit(1)
    return s3_uri


def cleanup_existing_endpoint_and_config(sm_client, name: str) -> None:
    try:
        ep_desc = sm_client.describe_endpoint(EndpointName=name)
        config_name = ep_desc.get("EndpointConfigName")
        sm_client.delete_endpoint(EndpointName=name)
        print(f"   Deleted existing endpoint: {name}")
        for _ in range(30):
            try:
                sm_client.describe_endpoint(EndpointName=name)
                time.sleep(2)
            except ClientError:
                break
        if config_name:
            try:
                sm_client.delete_endpoint_config(EndpointConfigName=config_name)
                print(f"   Deleted endpoint config: {config_name}")
            except ClientError:
                pass
    except ClientError as e:
        if "Could not find" in str(e) or "ValidationException" in str(e):
            try:
                sm_client.delete_endpoint_config(EndpointConfigName=name)
                print(f"   Deleted orphaned endpoint config: {name}")
            except ClientError:
                pass
        else:
            raise


def main():
    print("Step 1: Loading config...")
    if not SAGEMAKER_ROLE_ARN:
        print("[X] SAGEMAKER_ROLE_ARN not set in .env")
        exit(1)
    if not HF_TOKEN:
        print("[X] HF_TOKEN not set in .env — model download may fail")
        exit(1)
    s3_uri = load_s3_uri()
    print("  OK")

    demo_cost = COST_PER_HOUR * 3
    print(f"\n[WARN] This will start billing at ${COST_PER_HOUR}/hr on {INSTANCE_TYPE} (1× A10G 24GB)")
    print(f"   Model: Llama 3.1 8B AWQ + 3 LoRAs")
    print(f"   Container: LMI V20 (vLLM 0.15.1)")
    print(f"   Estimated cost for 3-hour demo: ${demo_cost:.2f}")
    confirm = input("Type 'yes' to continue: ")
    if confirm.strip().lower() != "yes":
        print("Cancelled.")
        exit(0)

    print("\nStep 2: Cleaning up any existing endpoint/config...")
    sm_client = boto3.client("sagemaker", region_name=AWS_REGION)
    for name in [ENDPOINT_NAME, "multi-lora-swissknife"]:
        cleanup_existing_endpoint_and_config(sm_client, name)
    print("  OK")

    print("\nStep 3: Creating SageMaker session and model...")
    try:
        session = sagemaker.Session(boto_session=boto3.Session(region_name=AWS_REGION))
        model_name = f"multi-lora-model-{int(time.time())}"

        model = Model(
            model_data=s3_uri,
            image_uri=CONTAINER_IMAGE,
            role=SAGEMAKER_ROLE_ARN,
            sagemaker_session=session,
            env={
                "HF_TOKEN": HF_TOKEN,
                "HUGGING_FACE_HUB_TOKEN": HF_TOKEN,
                "MODEL_LOADING_TIMEOUT": "1200",
                "PREDICT_TIMEOUT": "180",
                "SERVING_CHUNKED_READ_TIMEOUT": "300",
            },
            name=model_name,
        )
        print("  OK")

        print("Step 4: Deploying endpoint (10-14 min for 8B AWQ)...")
        model.deploy(
            initial_instance_count=1,
            instance_type=INSTANCE_TYPE,
            endpoint_name=ENDPOINT_NAME,
            container_startup_health_check_timeout=1200,
            wait=False,
        )
        print("  Deploy started. Polling for status...")

        print("Step 5: Polling endpoint status...")
        sm_client = boto3.client("sagemaker", region_name=AWS_REGION)
        start_time = time.time()
        for i in range(MAX_POLLS):
            resp = sm_client.describe_endpoint(EndpointName=ENDPOINT_NAME)
            status = resp["EndpointStatus"]
            elapsed = int(time.time() - start_time)
            elapsed_str = f"{elapsed // 60}m {elapsed % 60}s"
            print(f"  Status: {status} (elapsed: {elapsed_str})")

            if status == "InService":
                break
            elif status == "Failed":
                reason = resp.get("FailureReason", "Unknown")
                print(f"\n[X] Endpoint creation failed: {reason}")
                exit(1)

            time.sleep(POLL_INTERVAL)
        else:
            print("\n[X] Timeout after 20 minutes. Check SageMaker console.")
            exit(1)

        Path(".endpoint_name").write_text(ENDPOINT_NAME)
        print("\n[OK] ENDPOINT IS LIVE!")
        print(f"   Name: {ENDPOINT_NAME}")
        print(f"   Instance: {INSTANCE_TYPE} (1× A10G 24GB)")
        print(f"   Model: Llama 3.1 8B AWQ + 3 LoRAs")
        print(f"   Region: {AWS_REGION}")
        print(f"   Cost: ${COST_PER_HOUR}/hr - remember to delete when done!")

        try:
            lambda_client = boto3.client("lambda", region_name=AWS_REGION)
            resp = lambda_client.get_function_configuration(FunctionName="multi-lora-swissknife-router")
            env = resp.get("Environment", {}).get("Variables", {})
            env["ENDPOINT_NAME"] = ENDPOINT_NAME
            env["APP_REGION"] = AWS_REGION
            lambda_client.update_function_configuration(
                FunctionName="multi-lora-swissknife-router",
                Environment={"Variables": env},
            )
            print("   Lambda ENDPOINT_NAME updated")
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ResourceNotFoundException":
                print("   (Lambda not deployed yet - run python 1_deploy_lambda.py)")
            else:
                print(f"   (Could not update Lambda: {e})")

        print("\nNext steps:")
        print("  Test:       python 5_test_endpoint.py")
        print("  DELETE:     python 6_delete_endpoint.py")

    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code", "")
        if error_code == "ResourceLimitExceeded":
            print(f"[X] GPU quota exceeded for {INSTANCE_TYPE}")
            print("Fix: https://console.aws.amazon.com/servicequotas/home/services/sagemaker/quotas")
            exit(1)
        elif error_code == "ValidationException":
            print(f"[X] Validation error: {e.response.get('Error', {}).get('Message', str(e))}")
            exit(1)
        raise


if __name__ == "__main__":
    main()
