import json
import os
import time
from pathlib import Path

import boto3
from botocore.config import Config
from dotenv import load_dotenv

load_dotenv()

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
SAGEMAKER_READ_TIMEOUT = 300

TEST_CASES = [
    {"adapter": "adapter_1", "prompt": "Explain the concept of indemnification in a contract", "expected_keywords": ["compensation", "loss", "party", "liability"]},
    {"adapter": "adapter_1", "prompt": "What does force majeure mean in contract law?", "expected_keywords": ["extraordinary", "event", "control", "performance"]},
    {"adapter": "adapter_1", "prompt": "What are the essential elements of a valid contract?", "expected_keywords": ["offer", "acceptance", "consideration", "capacity"]},
    {"adapter": "adapter_2", "prompt": "Explain the mechanism of action of ACE inhibitors", "expected_keywords": ["angiotensin", "enzyme", "blood pressure", "kidney"]},
    {"adapter": "adapter_2", "prompt": "What are common side effects of beta blockers?", "expected_keywords": ["bradycardia", "fatigue", "blood pressure", "heart"]},
    {"adapter": "adapter_2", "prompt": "Explain the difference between Type 1 and Type 2 diabetes", "expected_keywords": ["insulin", "autoimmune", "resistance", "pancreas"]},
    {"adapter": "adapter_3", "prompt": "Write a Python function to implement binary search", "expected_keywords": ["def", "return", "mid", "low", "high"]},
    {"adapter": "adapter_3", "prompt": "What is the time complexity of quicksort?", "expected_keywords": ["O(n log n)", "average", "worst", "pivot"]},
    {"adapter": "adapter_3", "prompt": "Explain the N+1 query problem in databases", "expected_keywords": ["query", "database", "loop", "batch", "performance"]},
]


def load_endpoint_name() -> str:
    path = Path(".endpoint_name")
    if path.exists():
        name = path.read_text().strip()
        if name:
            return name
    return os.getenv("ENDPOINT_NAME", "multimodal-multi-lora-swissknife")


def count_keywords(text: str, keywords: list) -> int:
    text_lower = text.lower()
    return sum(1 for kw in keywords if kw.lower() in text_lower)


def main():
    endpoint_name = load_endpoint_name()
    config = Config(connect_timeout=60, read_timeout=SAGEMAKER_READ_TIMEOUT)
    runtime = boto3.client("sagemaker-runtime", region_name=AWS_REGION, config=config)

    results = []
    adapter_stats = {"adapter_1": [], "adapter_2": [], "adapter_3": []}

    print("Running 9 text test cases (Llama 3.1 8B AWQ + 3 LoRAs)...\n")
    for i, tc in enumerate(TEST_CASES, 1):
        payload = {"prompt": tc["prompt"], "adapter": tc["adapter"], "max_tokens": 128, "temperature": 0.3}
        start = time.perf_counter()
        try:
            resp = runtime.invoke_endpoint(
                EndpointName=endpoint_name,
                ContentType="application/json",
                Accept="application/json",
                Body=json.dumps(payload),
            )
            result = json.loads(resp["Body"].read())
        except Exception as e:
            print(f"[X] Test {i} ({tc['adapter']}): {e}")
            results.append({"tc": tc, "error": str(e), "latency_ms": 0, "tokens": 0, "keywords_found": 0})
            continue

        elapsed_ms = (time.perf_counter() - start) * 1000
        text = result.get("generated_text", "")
        tokens = result.get("tokens_generated", 0)
        keywords_found = count_keywords(text, tc["expected_keywords"])

        results.append({"tc": tc, "result": result, "latency_ms": elapsed_ms, "tokens": tokens, "keywords_found": keywords_found})
        adapter_stats[tc["adapter"]].append({"latency_ms": elapsed_ms, "tokens": tokens, "keywords_found": keywords_found})

        status = "OK" if keywords_found >= 1 else "."
        print(f"{status} {tc['adapter']} | {elapsed_ms:.0f}ms | {tokens} tokens | Keywords: {keywords_found}/{len(tc['expected_keywords'])}")

    print("\n" + "=" * 60)
    print("Per-adapter summary")
    print("=" * 60)
    for adapter, stats in adapter_stats.items():
        if stats:
            avg_lat = sum(s["latency_ms"] for s in stats) / len(stats)
            avg_tok = sum(s["tokens"] for s in stats) / len(stats)
            passed = sum(1 for s in stats if s["keywords_found"] >= 1)
            print(f"  {adapter}: avg latency={avg_lat:.0f}ms, avg tokens={avg_tok:.0f}, passed={passed}/{len(stats)}")

    print("\nBase model (adapter=none)...")
    payload = {"prompt": "What is a contract?", "adapter": "none", "max_tokens": 128, "temperature": 0.5}
    try:
        resp = runtime.invoke_endpoint(EndpointName=endpoint_name, ContentType="application/json", Accept="application/json", Body=json.dumps(payload))
        base_result = json.loads(resp["Body"].read())
        print(f"  [OK] base_model | {base_result.get('tokens_generated', 0)} tokens | model={base_result.get('model', 'unknown')}")
    except Exception as e:
        print(f"  [.] base_model: {e}")

    serializable = [{"tc": r["tc"], "result": r.get("result"), "latency_ms": r.get("latency_ms"), "tokens": r.get("tokens"), "keywords_found": r.get("keywords_found")} for r in results if "result" in r]
    Path("test_results.json").write_text(json.dumps(serializable, indent=2))

    print("\n[OK] All tests completed. Model: Llama 3.1 8B AWQ + 3 LoRAs")
    print("   [WARN] Remember: python 6_delete_endpoint.py when done!")


if __name__ == "__main__":
    main()
