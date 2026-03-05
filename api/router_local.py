import json
import os
import time
from typing import Literal

import boto3
from fastapi import FastAPI, HTTPException, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel, Field

from utils.config import ADAPTER_KEYWORDS, COST_PER_HOUR, ENDPOINT_NAME, get_api_key, get_runtime_client
from utils.metrics import MetricsTracker

app = FastAPI(
    title="Multi-LoRA Swiss Army Knife",
    description="Routes text requests to LoRA adapters on SageMaker (Llama 3.1 8B AWQ)",
    version="3.0.0",
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
tracker = MetricsTracker()
api_key_header = APIKeyHeader(name="x-api-key", auto_error=False)
DECODE_TOKENS_PER_SEC = 65.0


async def verify_api_key(api_key: str = Security(api_key_header)):
    expected = get_api_key()
    if expected and api_key != expected:
        raise HTTPException(status_code=403, detail="Invalid API key")
    return api_key


def detect_adapter(prompt: str) -> str:
    prompt_lower = prompt.lower()
    scores = {adapter: sum(1 for kw in keywords if kw in prompt_lower) for adapter, keywords in ADAPTER_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "none"


_DOMAIN_TO_ADAPTER = {"legal": "adapter_1", "medical": "adapter_2", "coding": "adapter_3"}


class GenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=4000)
    domain: Literal["adapter_1", "adapter_2", "adapter_3", "legal", "medical", "coding", "auto", "none"] = "auto"
    max_tokens: int = Field(default=512, ge=1, le=2048)
    temperature: float = Field(default=0.7, ge=0.0, le=1.0)


class GenerateResponse(BaseModel):
    response: str
    adapter_used: str
    domain_detected: str
    latency_ms: float
    tokens_generated: int
    tokens_per_second: float
    ttft_ms: float
    estimated_cost_usd: float
    input_type: str
    image_tokens: int
    prompt_tokens: int


@app.post("/generate", response_model=GenerateResponse)
async def generate(request: GenerateRequest, key: str = Security(verify_api_key)):
    adapter = request.domain
    if adapter in _DOMAIN_TO_ADAPTER:
        adapter = _DOMAIN_TO_ADAPTER[adapter]
    elif adapter == "auto":
        adapter = detect_adapter(request.prompt)

    payload = {"prompt": request.prompt, "adapter": adapter, "max_tokens": request.max_tokens, "temperature": request.temperature}

    client = get_runtime_client()
    start = time.time()
    try:
        response = client.invoke_endpoint(
            EndpointName=ENDPOINT_NAME,
            ContentType="application/json",
            Accept="application/json",
            Body=json.dumps(payload),
        )
        latency_ms = (time.time() - start) * 1000
        result = json.loads(response["Body"].read())

        if result.get("status") == "error":
            raise HTTPException(status_code=500, detail=result.get("error", "Unknown error"))

        tokens_generated = result.get("tokens_generated", 0)
        latency_s = max(latency_ms / 1000, 0.001)
        tokens_per_second = round(tokens_generated / latency_s, 1)
        estimated_decode_ms = (tokens_generated / DECODE_TOKENS_PER_SEC) * 1000
        ttft_ms = round(max(latency_ms - estimated_decode_ms, latency_ms * 0.08), 1)

        cost = (latency_ms / 1000 / 3600) * COST_PER_HOUR
        tracker.record_request(
            adapter=result.get("adapter_used", "unknown"),
            latency_ms=latency_ms,
            tokens=tokens_generated,
            cost=cost,
            ttft_ms=ttft_ms,
            tokens_per_second=tokens_per_second,
            has_image=False,
            image_tokens=0,
        )

        return GenerateResponse(
            response=result["generated_text"],
            adapter_used=result.get("adapter_used", "base_model"),
            domain_detected=adapter,
            latency_ms=round(latency_ms, 1),
            tokens_generated=tokens_generated,
            tokens_per_second=tokens_per_second,
            ttft_ms=ttft_ms,
            estimated_cost_usd=round(cost, 6),
            input_type="text",
            image_tokens=0,
            prompt_tokens=result.get("prompt_tokens", 0),
        )

    except HTTPException:
        raise
    except Exception as e:
        err_str = str(e)
        if "EndpointNotFound" in err_str or "ValidationError" in err_str or "Could not find endpoint" in err_str:
            raise HTTPException(status_code=503, detail="Endpoint not running. Run python 4_deploy_endpoint.py first.")
        if "ModelError" in type(e).__name__:
            raise HTTPException(status_code=502, detail=f"Model error: {err_str}")
        raise HTTPException(status_code=500, detail=err_str)


@app.get("/health")
async def health(key: str = Security(verify_api_key)):
    try:
        sm = boto3.client("sagemaker", region_name=os.getenv("AWS_REGION", "us-east-1"))
        resp = sm.describe_endpoint(EndpointName=ENDPOINT_NAME)
        return {
            "endpoint_status": resp["EndpointStatus"],
            "endpoint_name": ENDPOINT_NAME,
            "ready": resp["EndpointStatus"] == "InService",
            "creation_time": resp.get("CreationTime").isoformat() if resp.get("CreationTime") else None,
            "last_modified": resp.get("LastModifiedTime").isoformat() if resp.get("LastModifiedTime") else None,
        }
    except Exception:
        return {"endpoint_status": "NotFound", "ready": False}


@app.get("/metrics")
async def metrics(key: str = Security(verify_api_key)):
    return tracker.get_summary()
