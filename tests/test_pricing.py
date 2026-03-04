"""Tests for pricing module."""

from agentic_metric.pricing import estimate_cost, get_pricing, PRICING


def test_known_model_pricing():
    p = get_pricing("claude-sonnet-4-6-20250101")
    assert p == (3.0, 15.0, 0.30, 6.0)


def test_unknown_model_fallback():
    p = get_pricing("unknown-model-xyz")
    assert p == (5.0, 25.0, 0.50, 10.0)  # default


def test_estimate_cost_zero():
    cost = estimate_cost("claude-sonnet-4-6")
    assert cost == 0.0


def test_estimate_cost_basic():
    cost = estimate_cost(
        "claude-sonnet-4-6",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )
    # 1M * 3.0/1M + 1M * 15.0/1M = 3.0 + 15.0 = 18.0
    assert abs(cost - 18.0) < 0.001


def test_estimate_cost_with_cache():
    cost = estimate_cost(
        "claude-opus-4-6",
        input_tokens=500_000,
        output_tokens=100_000,
        cache_read_tokens=2_000_000,
        cache_creation_tokens=200_000,
    )
    # 0.5M * 5.0 + 0.1M * 25.0 + 2M * 0.5 + 0.2M * 10.0
    # = 2.5 + 2.5 + 1.0 + 2.0 = 8.0
    assert abs(cost - 8.0) < 0.001


def test_all_models_have_four_values():
    for model, prices in PRICING.items():
        assert len(prices) == 4, f"{model} has {len(prices)} values"
        assert all(isinstance(p, (int, float)) for p in prices)
