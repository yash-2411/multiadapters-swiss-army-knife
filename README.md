# Multi-LoRA Swiss Army Knife

**Setup:** Copy `.env.example` to `.env` and fill in `S3_BUCKET`, `SAGEMAKER_ROLE_ARN`, `HF_TOKEN`. Never commit `.env` or `lambda_deployment.json`.

**Flow:** Deploy Lambda → Create adapters → Package + upload to S3 → Deploy SageMaker endpoint → Test. Delete endpoint when done.

**Run order:** `1_deploy_lambda.py` → `2_create_adapters.py` → `3_package_and_upload.py` → `4_deploy_endpoint.py` → `5_test_endpoint.py`. `7_get_ready.py` does deploy + test in one call. `6_delete_endpoint.py` stops billing.

**Specs:** Llama 3.1 8B AWQ INT4, 3 LoRA adapters (legal, medical, coding), ml.g5.xlarge, ~5GB VRAM, ~$1.41/hr.

**Quantization:** AWQ 4-bit. LoRA r=16, alpha=32, target q/k/v/o projections.

**Best practices:** Single base model + multiple LoRAs; keyword-based adapter routing; vLLM with eager mode off; 90% GPU memory utilization.
