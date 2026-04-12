from __future__ import annotations

import json
from typing import Sequence

import numpy as np

_model = None
_processor = None


def _load_clip():
    global _model, _processor
    if _model is not None:
        return _model, _processor
    from transformers import CLIPModel, CLIPProcessor
    model_name = "openai/clip-vit-base-patch32"
    _processor = CLIPProcessor.from_pretrained(model_name)
    _model = CLIPModel.from_pretrained(model_name)
    _model.eval()
    return _model, _processor


def compute_clip_embedding(image_path: str) -> list[float]:
    import torch
    from PIL import Image
    model, processor = _load_clip()
    image = Image.open(image_path).convert("RGB")
    inputs = processor(images=image, return_tensors="pt")
    with torch.no_grad():
        image_features = model.get_image_features(**inputs)
    # Handle both tensor and BaseModelOutputWithPooling return types
    if hasattr(image_features, 'pooler_output'):
        features_tensor = image_features.pooler_output
    else:
        features_tensor = image_features
    embedding = features_tensor.squeeze(0).numpy()
    norm = np.linalg.norm(embedding)
    if norm > 0:
        embedding = embedding / norm
    return embedding.tolist()


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    a_arr = np.array(a, dtype=float)
    b_arr = np.array(b, dtype=float)
    norm_a = np.linalg.norm(a_arr)
    norm_b = np.linalg.norm(b_arr)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(a_arr, b_arr) / (norm_a * norm_b))


def rank_by_visual_similarity(
    query_embedding: list[float],
    candidates: list[dict],
    top_k: int | None = None,
) -> list[dict]:
    results = []
    for candidate in candidates:
        raw = candidate.get("clip_embedding")
        if raw is None:
            continue
        if isinstance(raw, str):
            embedding = json.loads(raw)
        else:
            embedding = raw
        score = cosine_similarity(query_embedding, embedding)
        result = dict(candidate)
        result["visual_similarity"] = score
        results.append(result)
    results.sort(key=lambda x: x["visual_similarity"], reverse=True)
    if top_k is not None:
        results = results[:top_k]
    return results
