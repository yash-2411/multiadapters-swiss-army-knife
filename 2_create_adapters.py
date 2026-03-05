import hashlib
import json
import os
from pathlib import Path

import torch
import torch.nn as nn
from dotenv import load_dotenv

load_dotenv()
HF_TOKEN = os.getenv("HF_TOKEN") or os.getenv("HUGGING_FACE_HUB_TOKEN")

BASE_MODEL = "meta-llama/Llama-3.1-8B"
NUM_LAYERS = 32
HIDDEN_SIZE = 4096
NUM_KV_HEADS = 8
HEAD_DIM = 128
KV_DIM = NUM_KV_HEADS * HEAD_DIM
LORA_R = 16


class LoRAWeightGenerator(nn.Module):
    def __init__(self, hidden_size: int = 4096, kv_dim: int = 1024, lora_r: int = 16):
        super().__init__()
        self.lora_A_q = nn.Linear(hidden_size, lora_r, bias=False)
        self.lora_B_q = nn.Linear(lora_r, hidden_size, bias=False)
        self.lora_A_k = nn.Linear(hidden_size, lora_r, bias=False)
        self.lora_B_k = nn.Linear(lora_r, kv_dim, bias=False)
        self.lora_A_v = nn.Linear(hidden_size, lora_r, bias=False)
        self.lora_B_v = nn.Linear(lora_r, kv_dim, bias=False)
        self.lora_A_o = nn.Linear(hidden_size, lora_r, bias=False)
        self.lora_B_o = nn.Linear(lora_r, hidden_size, bias=False)
        nn.init.zeros_(self.lora_B_q.weight)
        nn.init.zeros_(self.lora_B_k.weight)
        nn.init.zeros_(self.lora_B_v.weight)
        nn.init.zeros_(self.lora_B_o.weight)

    def init_a_matrices(self, seed: int):
        torch.manual_seed(seed)
        for m in [self.lora_A_q, self.lora_A_k, self.lora_A_v, self.lora_A_o]:
            nn.init.kaiming_uniform_(m.weight, a=5**0.5)


def create_adapter_state_dict(adapter_name: str) -> dict:
    seed = int(hashlib.md5(adapter_name.encode()).hexdigest()[:8], 16) % (2**32)
    generator = LoRAWeightGenerator(hidden_size=HIDDEN_SIZE, kv_dim=KV_DIM, lora_r=LORA_R)
    generator.init_a_matrices(seed)

    state_dict = {}
    projections = [
        ("q_proj", generator.lora_A_q, generator.lora_B_q),
        ("k_proj", generator.lora_A_k, generator.lora_B_k),
        ("v_proj", generator.lora_A_v, generator.lora_B_v),
        ("o_proj", generator.lora_A_o, generator.lora_B_o),
    ]

    for layer_idx in range(NUM_LAYERS):
        for proj_name, lora_a, lora_b in projections:
            prefix = f"base_model.model.model.layers.{layer_idx}.self_attn.{proj_name}"
            state_dict[f"{prefix}.lora_A.weight"] = lora_a.weight.data.clone()
            state_dict[f"{prefix}.lora_B.weight"] = lora_b.weight.data.clone()

    return state_dict


def main():
    if not HF_TOKEN:
        print("Warning: HF_TOKEN not set. Adapter config references base model.")

    for i, adapter_name in enumerate(["adapter_1", "adapter_2", "adapter_3"], 1):
        print(f"\nCreating {adapter_name}...")
        output_dir = Path(f"./adapters/{adapter_name}")
        output_dir.mkdir(parents=True, exist_ok=True)

        state_dict = create_adapter_state_dict(adapter_name)

        adapter_config = {
            "base_model_name_or_path": BASE_MODEL,
            "bias": "none",
            "fan_in_fan_out": False,
            "inference_mode": True,
            "init_lora_weights": True,
            "lora_alpha": 32,
            "lora_dropout": 0.05,
            "modules_to_save": None,
            "peft_type": "LORA",
            "r": LORA_R,
            "revision": None,
            "target_modules": ["q_proj", "v_proj", "k_proj", "o_proj"],
            "task_type": "CAUSAL_LM",
        }

        (output_dir / "adapter_config.json").write_text(json.dumps(adapter_config, indent=2))
        torch.save(state_dict, output_dir / "adapter_model.bin")

        param_count = sum(p.numel() for p in state_dict.values())
        size_mb = (output_dir / "adapter_model.bin").stat().st_size / (1024 * 1024)

        print(f"[OK] {adapter_name} created")
        print(f"  File: ./adapters/{adapter_name}/adapter_model.bin")
        print(f"  Size: {size_mb:.1f} MB")
        print(f"  Parameters: {param_count:,}")

    print("\n" + "=" * 65)
    print("VRAM & COST: Llama 3.1 8B AWQ + 3 LoRAs")
    print("=" * 65)
    print(f"{'Approach':<42} {'VRAM':>8} {'Cost/hr':>10}")
    print("-" * 65)
    print(f"{'3x FP16 8B models (3 endpoints)':<42} {'24.0 GB':>8} {'$4.23':>10}")
    print(f"{'Llama 3.1 8B AWQ + 3 LoRAs (this)':<42} {'~5 GB':>8} {'$1.41':>10}")
    print("=" * 65)
    print(f"\nInstance: ml.g5.xlarge (A10G 24GB)")
    print(f"Model: hugging-quants/Meta-Llama-3.1-8B-Instruct-AWQ-INT4")
    print("\n[OK] All 3 adapters created. Run: python 3_package_and_upload.py")


if __name__ == "__main__":
    main()
