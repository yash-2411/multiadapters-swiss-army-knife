import json
import os
import subprocess
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv()

ENDPOINT_NAME = os.getenv("ENDPOINT_NAME", "multimodal-multi-lora-swissknife")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")


def main():
    print("Get ready: deploy endpoint, smoke test, print dashboard URL")

    sm = boto3.client("sagemaker", region_name=AWS_REGION)

    try:
        resp = sm.describe_endpoint(EndpointName=ENDPOINT_NAME)
        if resp["EndpointStatus"] == "InService":
            print("[OK] Endpoint already InService!")
        else:
            print(f"[INFO] Endpoint status: {resp['EndpointStatus']}")
            print("   Starting deploy script...")
            subprocess.run([sys.executable, "4_deploy_endpoint.py"], input=b"yes\n", check=True)
    except ClientError:
        print("Starting endpoint deployment (~15 min)...")
        subprocess.run([sys.executable, "4_deploy_endpoint.py"], input=b"yes\n", check=True)
    except Exception as e:
        print(f"[INFO] Endpoint check failed: {e}")
        print("   Starting deploy script...")
        subprocess.run([sys.executable, "4_deploy_endpoint.py"], input=b"yes\n", check=True)

    print("\nRunning quick smoke test...")
    subprocess.run([sys.executable, "5_test_endpoint.py"], check=True)

    config_file = Path("lambda_deployment.json")
    if config_file.exists():
        config = json.loads(config_file.read_text())
        dashboard_url = config.get("dashboard_url", config.get("api_url", ""))
    else:
        dashboard_url = ""

    print("\n" + "=" * 60)
    print("Demo: adapter_1 (legal), adapter_2 (medical), adapter_3 (coding)")
    print("Try: indemnification, ACE inhibitors, binary search")
    print("Auto: keyword-based routing")

    if dashboard_url:
        print(f"Dashboard: {dashboard_url}")
    else:
        print("Run python 1_deploy_lambda.py first")
    print("After demo: python 6_delete_endpoint.py")


if __name__ == "__main__":
    main()
