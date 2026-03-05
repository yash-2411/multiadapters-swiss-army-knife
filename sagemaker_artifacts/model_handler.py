import json
import os
import logging
from pathlib import Path

from djl_python import Input, Output

logger = logging.getLogger(__name__)

MODEL_ID = "hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4"

_model = None
_adapter_registry = {}
LLM = None
SamplingParams = None
LoRARequest = None


def _ensure_vllm():
    global LLM, SamplingParams, LoRARequest
    if LLM is None:
        from vllm import LLM as _LLM, SamplingParams as _SP
        from vllm.lora.request import LoRARequest as _LR
        LLM, SamplingParams, LoRARequest = _LLM, _SP, _LR


def model_fn(model_dir: str):
    global _model, _adapter_registry

    _ensure_vllm()
    model_dir = Path(model_dir or "/opt/ml/model")

    logger.info("Initializing vLLM with Llama 3.1 8B AWQ (text-only)...")
    if model_dir.exists():
        logger.info(f"Model dir: {list(model_dir.iterdir())}")

    _model = LLM(
        model=MODEL_ID,
        tokenizer=MODEL_ID,
        quantization="awq_marlin",
        tensor_parallel_size=1,
        gpu_memory_utilization=0.90,
        max_model_len=2048,
        max_num_seqs=4,
        trust_remote_code=True,
        download_dir="/tmp/model_cache",
        enable_lora=True,
        max_loras=3,
        max_lora_rank=16,
        enforce_eager=False,
    )

    adapters_dir = model_dir / "adapters"
    adapter_id = 1
    if adapters_dir.exists():
        for adapter_path in sorted(adapters_dir.iterdir()):
            if adapter_path.is_dir() and (adapter_path / "adapter_config.json").exists():
                adapter_name = adapter_path.name
                if not adapter_name:
                    continue
                try:
                    _adapter_registry[adapter_name] = LoRARequest(
                        lora_name=adapter_name,
                        lora_int_id=adapter_id,
                        lora_path=str(adapter_path),
                    )
                    logger.info(f"Registered adapter: {adapter_name} (id={adapter_id})")
                    adapter_id += 1
                except Exception as e:
                    logger.warning(f"Failed to register adapter {adapter_name}: {e}")

    logger.info(f"Loaded adapters: {list(_adapter_registry.keys())}")
    return _model


def register_adapter(inputs: Input) -> Output:
    outputs = Output()
    outputs.add_as_json({"status": "success", "message": "adapters loaded in model_fn"})
    return outputs


def handle(inputs: Input) -> Output:
    global _model, _adapter_registry

    if _model is None:
        model_fn(os.environ.get("MODEL_DIR", "/opt/ml/model"))

    outputs = Output()
    try:
        body = inputs.get_as_json()
    except (AttributeError, TypeError, ValueError):
        body = {}
    if body is None or not isinstance(body, dict):
        body = {}

    prompt = str(body.get("prompt") or body.get("inputs") or "").strip()
    if not prompt:
        outputs.add_as_json({"error": "prompt field is required", "status": "error"})
        return outputs

    params = body.get("parameters", {})
    if not isinstance(params, dict):
        params = {}
    adapter_name = str(params.get("adapter") or body.get("adapter", "none")).strip()

    try:
        max_tokens = max(1, min(int(body.get("max_tokens", params.get("max_tokens", 512))), 1536))
    except (TypeError, ValueError):
        max_tokens = 512
    try:
        temperature = max(0.0, min(2.0, float(body.get("temperature", params.get("temperature", 0.7)))))
    except (TypeError, ValueError):
        temperature = 0.7
    try:
        top_p = max(0.0, min(1.0, float(body.get("top_p", params.get("top_p", 0.9)))))
    except (TypeError, ValueError):
        top_p = 0.9

    lora_request = None
    if adapter_name and adapter_name.lower() != "none":
        if adapter_name in _adapter_registry:
            lora_request = _adapter_registry[adapter_name]
            logger.info(f"Using adapter: {adapter_name}")
        else:
            logger.warning(f"Adapter '{adapter_name}' not found. Available: {list(_adapter_registry.keys())}. Using base model.")

    formatted_prompt = f"<|begin_of_text|><|start_header_id|>user<|end_header_id|>\n\n{prompt}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n"

    sampling_params = SamplingParams(
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        stop=["<|eot_id|>", "<|end_of_text|>"],
    )

    try:
        request_outputs = _model.generate(
            [formatted_prompt],
            sampling_params,
            lora_request=lora_request,
        )

        if not request_outputs or not request_outputs[0].outputs:
            outputs.add_as_json({"error": "Model returned no output", "status": "error"})
            return outputs

        out = request_outputs[0]
        text = (getattr(out.outputs[0], "text", None) or "").strip()

        outputs.add_as_json({
            "generated_text": text,
            "adapter_used": adapter_name if lora_request else "base_model",
            "tokens_generated": len(out.outputs[0].token_ids),
            "prompt_tokens": len(out.prompt_token_ids),
            "model": MODEL_ID,
            "quantization": "AWQ",
            "status": "success",
        })

    except Exception as e:
        logger.error(f"Inference error: {e}", exc_info=True)
        outputs.add_as_json({"error": str(e), "error_type": type(e).__name__, "status": "error"})

    return outputs
