try:
    from transformers.models.mllama.processing_mllama import MllamaProcessor
    if not hasattr(MllamaProcessor, "_get_num_multimodal_tokens"):
        def _get_num_multimodal_tokens(self, image_sizes=None, num_frames=None, **kwargs):
            n = max(1, len(image_sizes)) if image_sizes else 1
            return {"num_image_tokens": [560] * n}
        MllamaProcessor._get_num_multimodal_tokens = _get_num_multimodal_tokens
except Exception:
    pass
