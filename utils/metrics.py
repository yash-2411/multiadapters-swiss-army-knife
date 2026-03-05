import json
import os
from contextlib import contextmanager
from pathlib import Path

try:
    from filelock import FileLock
except ImportError:
    @contextmanager
    def FileLock(path):
        yield

_base = Path("/tmp") if os.environ.get("AWS_LAMBDA_FUNCTION_NAME") else Path(".")
METRICS_FILE = _base / "metrics.json"
LOCK_FILE = _base / "metrics.json.lock"


class MetricsTracker:
    def record_request(
        self,
        adapter: str,
        latency_ms: float,
        tokens: int,
        cost: float,
        ttft_ms: float = 0.0,
        tokens_per_second: float = 0.0,
        has_image: bool = False,
        image_tokens: int = 0,
    ):
        with FileLock(LOCK_FILE):
            data = self._load()
            data["total_requests"] = data.get("total_requests", 0) + 1
            data["total_cost_usd"] = data.get("total_cost_usd", 0.0) + cost
            data["total_tokens"] = data.get("total_tokens", 0) + tokens

            if has_image:
                data["image_requests"] = data.get("image_requests", 0) + 1
                data["total_image_tokens"] = data.get("total_image_tokens", 0) + image_tokens

            n = data["total_requests"]
            data["avg_latency_ms"] = ((data.get("avg_latency_ms", 0) * (n - 1)) + latency_ms) / n
            data["avg_ttft_ms"] = ((data.get("avg_ttft_ms", 0) * (n - 1)) + ttft_ms) / n
            data["avg_tokens_per_second"] = ((data.get("avg_tokens_per_second", 0) * (n - 1)) + tokens_per_second) / n

            if "adapters" not in data:
                data["adapters"] = {}
            if adapter not in data["adapters"]:
                data["adapters"][adapter] = {
                    "requests": 0,
                    "total_latency_ms": 0,
                    "tokens": 0,
                    "total_ttft_ms": 0,
                    "total_tps": 0,
                    "image_requests": 0,
                }
            a = data["adapters"][adapter]
            a["requests"] += 1
            a["total_latency_ms"] += latency_ms
            a["tokens"] += tokens
            a["total_ttft_ms"] = a.get("total_ttft_ms", 0) + ttft_ms
            a["total_tps"] = a.get("total_tps", 0) + tokens_per_second
            if has_image:
                a["image_requests"] = a.get("image_requests", 0) + 1

            self._save(data)

    def get_summary(self) -> dict:
        data = self._load()
        adapters = data.get("adapters", {})
        for name, stats in adapters.items():
            req_count = stats.get("requests", 0)
            if req_count > 0:
                stats["avg_latency_ms"] = stats["total_latency_ms"] / req_count
                stats["avg_ttft_ms"] = stats.get("total_ttft_ms", 0) / req_count
                stats["avg_tokens_per_second"] = stats.get("total_tps", 0) / req_count
        data["adapters"] = adapters
        return data

    def _load(self) -> dict:
        if METRICS_FILE.exists():
            try:
                return json.loads(METRICS_FILE.read_text())
            except Exception:
                return {}
        return {}

    def _save(self, data: dict):
        METRICS_FILE.write_text(json.dumps(data, indent=2))
