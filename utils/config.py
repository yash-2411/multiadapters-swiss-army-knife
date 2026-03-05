import json
import os
from pathlib import Path

import boto3

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
S3_BUCKET = os.getenv("S3_BUCKET")
SAGEMAKER_ROLE_ARN = os.getenv("SAGEMAKER_ROLE_ARN")
HF_TOKEN = os.getenv("HF_TOKEN") or os.getenv("HUGGING_FACE_HUB_TOKEN")
ENDPOINT_NAME = os.getenv("ENDPOINT_NAME", "multimodal-multi-lora-swissknife")

COST_PER_HOUR = 1.41

ADAPTER_KEYWORDS = {
    "adapter_1": [
        "contract", "clause", "liability", "indemnif", "warrant", "tort", "statute",
        "arbitration", "fiduciary", "plaintiff", "defendant", "legal", "law", "court",
        "agreement", "breach", "damages", "jurisdiction", "counsel",
    ],
    "adapter_2": [
        "symptom", "diagnosis", "drug", "patient", "disease", "treatment", "clinical",
        "medical", "health", "dose", "medication", "therapy", "syndrome", "chronic",
        "acute", "physician", "hospital", "prescription", "pathology",
    ],
    "adapter_3": [
        "code", "function", "python", "debug", "algorithm", "database", "api", "error",
        "class", "variable", "loop", "array", "query", "programming", "software",
        "bug", "implement", "complexity", "runtime", "memory",
    ],
}


def _require_role():
    if not SAGEMAKER_ROLE_ARN:
        raise ValueError(
            "SAGEMAKER_ROLE_ARN not set. Add it to .env. "
            "Create an IAM role with SageMakerFullAccess and pass the ARN."
        )


def get_sagemaker_client():
    _require_role()
    return boto3.client("sagemaker", region_name=AWS_REGION)


def get_runtime_client():
    return boto3.client("sagemaker-runtime", region_name=AWS_REGION)


def get_s3_client():
    return boto3.client("s3", region_name=AWS_REGION)


def get_api_key() -> str:
    config_file = Path("lambda_deployment.json")
    if config_file.exists():
        return json.loads(config_file.read_text()).get("api_key", "")
    return os.getenv("API_KEY", "")
