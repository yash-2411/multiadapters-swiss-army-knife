import json
import os
import time

import boto3

from utils.config import ADAPTER_KEYWORDS, COST_PER_HOUR, ENDPOINT_NAME
from utils.metrics import MetricsTracker

tracker = MetricsTracker()

DECODE_TOKENS_PER_SEC = 65.0


def cors_response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization,x-api-key",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        },
        "body": json.dumps(body),
    }


def handle_health() -> dict:
    try:
        region = os.environ.get("APP_REGION", os.environ.get("AWS_REGION", "us-east-1"))
        endpoint_name = os.environ.get("ENDPOINT_NAME", ENDPOINT_NAME)
        sm = boto3.client("sagemaker", region_name=region)
        resp = sm.describe_endpoint(EndpointName=endpoint_name)
        status = resp["EndpointStatus"]
        result = {
            "endpoint_status": status,
            "endpoint_name": endpoint_name,
            "ready": status == "InService",
        }
        if resp.get("CreationTime"):
            result["creation_time"] = resp["CreationTime"].isoformat()
        if resp.get("LastModifiedTime"):
            result["last_modified"] = resp["LastModifiedTime"].isoformat()
        return cors_response(200, result)
    except Exception:
        return cors_response(200, {
            "endpoint_status": "NotFound",
            "ready": False,
            "hint": "Endpoint is offline - start it with python 4_deploy_endpoint.py",
        })


def _detect_adapter(prompt: str) -> str:
    prompt_lower = prompt.lower()
    scores = {a: sum(1 for kw in kws if kw in prompt_lower) for a, kws in ADAPTER_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "none"


def handle_metrics() -> dict:
    try:
        summary = tracker.get_summary()
        return cors_response(200, summary)
    except Exception as e:
        return cors_response(500, {"error": str(e)})


def handle_generate(body: dict) -> dict:
    prompt = body.get("prompt", "").strip() if isinstance(body.get("prompt"), str) else ""
    if not prompt:
        return cors_response(400, {"error": "prompt field is required"})

    adapter = str(body.get("adapter") or body.get("domain", "none")).strip() or "none"
    if adapter in ("legal", "medical", "coding"):
        adapter = {"legal": "adapter_1", "medical": "adapter_2", "coding": "adapter_3"}[adapter]
    elif adapter == "auto":
        adapter = _detect_adapter(prompt)

    try:
        max_tokens = min(int(body.get("max_tokens", 512)), 1536)
    except (TypeError, ValueError):
        max_tokens = 512
    try:
        temperature = float(body.get("temperature", 0.7))
    except (TypeError, ValueError):
        temperature = 0.7

    payload = {
        "inputs": prompt,
        "parameters": {
            "adapter": adapter,
            "max_tokens": max_tokens,
            "temperature": temperature,
        },
        "prompt": prompt,
        "adapter": adapter,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    region = os.environ.get("APP_REGION", os.environ.get("AWS_REGION", "us-east-1"))
    endpoint_name = os.environ.get("ENDPOINT_NAME", ENDPOINT_NAME)
    runtime = boto3.client("sagemaker-runtime", region_name=region)

    start = time.time()
    try:
        response = runtime.invoke_endpoint(
            EndpointName=endpoint_name,
            ContentType="application/json",
            Accept="application/json",
            Body=json.dumps(payload),
        )
        latency_ms = (time.time() - start) * 1000
        result = json.loads(response["Body"].read())

        if result.get("status") == "error":
            return cors_response(502, {"error": result.get("error", "Model error")})

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

        return cors_response(200, {
            "response": result.get("generated_text", ""),
            "adapter_used": result.get("adapter_used", "base_model"),
            "domain_detected": adapter,
            "latency_ms": round(latency_ms, 1),
            "tokens_generated": tokens_generated,
            "tokens_per_second": tokens_per_second,
            "ttft_ms": ttft_ms,
            "estimated_cost_usd": round(cost, 6),
            "input_type": "text",
            "image_tokens": 0,
            "prompt_tokens": result.get("prompt_tokens", 0),
        })

    except Exception as e:
        error_str = str(e)
        if "EndpointNotFound" in error_str or "ValidationError" in error_str or "Could not find" in error_str:
            return cors_response(503, {
                "error": "SageMaker endpoint is offline.",
                "hint": "Run python 4_deploy_endpoint.py to start it.",
                "status": "endpoint_offline",
            })
        if "ModelError" in type(e).__name__:
            return cors_response(502, {"error": f"Model error: {error_str}"})
        return cors_response(500, {"error": error_str})


def lambda_handler(event, context):
    if event.get("httpMethod") == "OPTIONS":
        return cors_response(200, {})

    path = event.get("path", "/")
    method = event.get("httpMethod", "GET")
    path_parts = [p for p in path.split("/") if p]
    path_tail = path_parts[-1] if path_parts else ""

    if path_tail == "health" and method == "GET":
        return handle_health()
    if path_tail == "metrics" and method == "GET":
        return handle_metrics()
    if path_tail == "generate" and method == "POST":
        try:
            body = json.loads(event.get("body", "{}"))
        except json.JSONDecodeError:
            return cors_response(400, {"error": "Invalid JSON body"})
        if not isinstance(body, dict):
            body = {}
        return handle_generate(body)

    return cors_response(404, {"error": f"Route {method} {path} not found"})
