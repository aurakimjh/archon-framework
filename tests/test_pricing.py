"""Pricing helper 테스트."""

from __future__ import annotations

import json

import pytest

from src.dashboard.pricing import calc_cost, reset_cache_for_tests


@pytest.fixture(autouse=True)
def _reset():
    reset_cache_for_tests()
    yield
    reset_cache_for_tests()


def _write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


class TestPricing:
    def test_known_model(self, tmp_path, monkeypatch):
        path = tmp_path / "pricing.json"
        _write(
            path,
            {
                "default": {"input": 0.001, "output": 0.002},
                "models": {"gpt-4o": {"input": 0.005, "output": 0.015}},
            },
        )
        monkeypatch.setenv("ARCHON_PRICING_PATH", str(path))

        # 1K in, 1K out → 0.005 + 0.015
        assert calc_cost("gpt-4o", 1000, 1000) == pytest.approx(0.020)

    def test_unknown_falls_back_to_default(self, tmp_path, monkeypatch):
        path = tmp_path / "pricing.json"
        _write(
            path,
            {
                "default": {"input": 0.01, "output": 0.02},
                "models": {},
            },
        )
        monkeypatch.setenv("ARCHON_PRICING_PATH", str(path))
        assert calc_cost("never-heard-of", 1000, 0) == pytest.approx(0.01)
        assert calc_cost(None, 0, 1000) == pytest.approx(0.02)

    def test_provider_prefixed_model(self, tmp_path, monkeypatch):
        path = tmp_path / "pricing.json"
        _write(
            path,
            {
                "default": {"input": 0, "output": 0},
                "models": {"claude-opus-4": {"input": 0.015, "output": 0.075}},
            },
        )
        monkeypatch.setenv("ARCHON_PRICING_PATH", str(path))
        # `anthropic/claude-opus-4-7` → prefix 매칭으로 claude-opus-4 단가 사용.
        cost = calc_cost("anthropic/claude-opus-4-7", 2000, 1000)
        assert cost == pytest.approx(2 * 0.015 + 1 * 0.075)

    def test_missing_pricing_file_uses_fallback(self, tmp_path, monkeypatch):
        monkeypatch.setenv(
            "ARCHON_PRICING_PATH", str(tmp_path / "absent.json")
        )
        # fallback default {input: 0.002, output: 0.006}
        assert calc_cost("any", 1000, 1000) == pytest.approx(0.002 + 0.006)

    def test_invalid_json_uses_fallback(self, tmp_path, monkeypatch):
        path = tmp_path / "broken.json"
        path.write_text("{not json", encoding="utf-8")
        monkeypatch.setenv("ARCHON_PRICING_PATH", str(path))
        # fallback values
        assert calc_cost("x", 1000, 0) == pytest.approx(0.002)

    def test_cache_reload_on_mtime_change(self, tmp_path, monkeypatch):
        path = tmp_path / "pricing.json"
        _write(
            path,
            {
                "default": {"input": 0.1, "output": 0.1},
                "models": {"m": {"input": 0.5, "output": 0.5}},
            },
        )
        monkeypatch.setenv("ARCHON_PRICING_PATH", str(path))
        before = calc_cost("m", 1000, 1000)
        assert before == pytest.approx(1.0)

        import os as _os
        import time as _time
        # 파일 갱신 — mtime을 미래로 점프
        _write(
            path,
            {
                "default": {"input": 0.1, "output": 0.1},
                "models": {"m": {"input": 0.0, "output": 0.0}},
            },
        )
        future = _time.time() + 10
        _os.utime(path, (future, future))

        after = calc_cost("m", 1000, 1000)
        assert after == pytest.approx(0.0)
