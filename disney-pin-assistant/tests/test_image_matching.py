import json
import math

import pytest

from src.pipeline.image_matching import cosine_similarity, rank_by_visual_similarity


class TestCosineSimilarity:
    def test_identical_vectors(self):
        a = [1.0, 0.0, 0.0]
        b = [1.0, 0.0, 0.0]
        assert cosine_similarity(a, b) == pytest.approx(1.0, abs=1e-6)

    def test_orthogonal_vectors(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert cosine_similarity(a, b) == pytest.approx(0.0, abs=1e-6)

    def test_opposite_vectors(self):
        a = [1.0, 0.0, 0.0]
        b = [-1.0, 0.0, 0.0]
        assert cosine_similarity(a, b) == pytest.approx(-1.0, abs=1e-6)

    def test_similar_vectors(self):
        a = [1.0, 1.0, 0.0]
        b = [1.0, 0.8, 0.1]
        result = cosine_similarity(a, b)
        assert 0.5 < result < 1.0

    def test_zero_vector_returns_zero(self):
        a = [0.0, 0.0, 0.0]
        b = [1.0, 0.0, 0.0]
        assert cosine_similarity(a, b) == pytest.approx(0.0, abs=1e-6)


class TestRankByVisualSimilarity:
    def _make_candidate(self, name: str, embedding: list[float]) -> dict:
        return {"name": name, "clip_embedding": json.dumps(embedding)}

    def test_ranks_candidates_by_similarity(self):
        query = [1.0, 0.0, 0.0]
        candidates = [
            self._make_candidate("low", [0.0, 1.0, 0.0]),   # orthogonal
            self._make_candidate("high", [1.0, 0.0, 0.0]),  # identical
            self._make_candidate("mid", [0.7, 0.7, 0.0]),   # similar
        ]
        results = rank_by_visual_similarity(query, candidates)
        assert results[0]["name"] == "high"
        assert results[1]["name"] == "mid"
        assert results[2]["name"] == "low"

    def test_adds_visual_similarity_score(self):
        query = [1.0, 0.0]
        candidates = [self._make_candidate("pin", [1.0, 0.0])]
        results = rank_by_visual_similarity(query, candidates)
        assert len(results) == 1
        assert "visual_similarity" in results[0]
        assert results[0]["visual_similarity"] == pytest.approx(1.0, abs=1e-6)

    def test_skips_candidates_without_embedding(self):
        query = [1.0, 0.0]
        candidates = [
            {"name": "no_embedding", "clip_embedding": None},
            self._make_candidate("has_embedding", [1.0, 0.0]),
        ]
        results = rank_by_visual_similarity(query, candidates)
        assert len(results) == 1
        assert results[0]["name"] == "has_embedding"

    def test_top_k_truncates_results(self):
        query = [1.0, 0.0, 0.0]
        candidates = [
            self._make_candidate("a", [1.0, 0.0, 0.0]),
            self._make_candidate("b", [0.9, 0.1, 0.0]),
            self._make_candidate("c", [0.0, 1.0, 0.0]),
        ]
        results = rank_by_visual_similarity(query, candidates, top_k=2)
        assert len(results) == 2
