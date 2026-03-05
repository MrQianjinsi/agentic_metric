"""Model pricing table and cost estimation."""

from __future__ import annotations

# (input, output, cache_read, cache_write) — USD per million tokens
PRICING: dict[str, tuple[float, float, float, float]] = {
    "claude-opus-4-6":   (5.0, 25.0, 0.50, 6.25),
    "claude-opus-4-5":   (5.0, 25.0, 0.50, 6.25),
    "claude-opus-4-1":   (15.0, 75.0, 1.50, 18.75),
    "claude-sonnet-4-6": (3.0, 15.0, 0.30, 3.75),
    "claude-sonnet-4-5": (3.0, 15.0, 0.30, 3.75),
    "claude-sonnet-4":   (3.0, 15.0, 0.30, 3.75),
    "claude-haiku-4-5":  (1.0,  5.0, 0.10, 1.25),
    "gpt-5.3-codex":     (1.75, 14.0, 0.175, 0.0),
    "gpt-5.2":           (1.75, 14.0, 0.175, 0.0),
    "gpt-5.1-codex":     (1.25, 10.0, 0.125, 0.0),
    "gpt-4o":            (2.5, 10.0, 1.25, 0.0),
    "gemini-3-pro":      (2.0, 12.0, 0.20, 0.0),
    "o3":                (2.0,  8.0, 0.50, 0.0),
    "o4-mini":           (1.1,  4.4, 0.275, 0.0),
    "kimi-k2":           (0.60, 2.50, 0.15, 0.0),
    "kimi-k2.5":         (0.60, 3.00, 0.15, 0.0),
    "coder-model":       (0.65, 3.25, 0.13, 0.0),
}

_DEFAULT_PRICING = (5.0, 25.0, 0.50, 6.25)  # fallback to opus pricing

_MODEL_ALIASES: dict[str, str] = {
    "claude-4.5-sonnet-thinking": "claude-sonnet-4-5",
    "claude-4.5-opus-high-thinking": "claude-opus-4-5",
    "gpt-5.1-codex-max": "gpt-5.1-codex",
}

# Copilot Chat result.details display name → our pricing key
_COPILOT_MODEL_MAP: dict[str, str] = {
    "claude opus 4.6": "claude-opus-4-6",
    "claude opus 4.5": "claude-opus-4-5",
    "claude sonnet 4.6": "claude-sonnet-4-6",
    "claude sonnet 4.5": "claude-sonnet-4-5",
    "claude sonnet 4": "claude-sonnet-4",
    "claude sonnet 3.5": "claude-sonnet-4",
    "claude haiku 4.5": "claude-haiku-4-5",
    "gpt-5.2": "gpt-5.2",
    "gpt-5 mini": "gpt-4o",
    "gpt-4o mini": "gpt-4o",
    "gpt-4o": "gpt-4o",
    "o3": "o3",
    "o4-mini": "o4-mini",
    "gemini 3 pro": "gemini-3-pro",
}


def normalize_copilot_model(details: str) -> str:
    """Normalize Copilot Chat result.details string to a pricing key.

    Input looks like ``"Claude Haiku 4.5 • 1x"`` or ``"GPT-5 mini • 0.9x"``.
    """
    if not details:
        return ""
    # Strip the "• Nx" suffix and lowercase
    name = details.split("•")[0].strip().lower()
    # Strip "(Preview)" or similar tags
    name = name.replace("(preview)", "").strip()
    return _COPILOT_MODEL_MAP.get(name, "")


def normalize_model(name: str) -> str:
    """Normalize external model names to our pricing keys."""
    if not name:
        return ""
    return _MODEL_ALIASES.get(name, name)


def get_pricing(model: str) -> tuple[float, float, float, float]:
    """Look up pricing by model prefix match."""
    for prefix, pricing in PRICING.items():
        if model.startswith(prefix):
            return pricing
    return _DEFAULT_PRICING


def estimate_cost(
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
) -> float:
    """Estimate API-equivalent cost in USD."""
    p_in, p_out, p_cr, p_cw = get_pricing(model)
    cost = (
        input_tokens * p_in
        + output_tokens * p_out
        + cache_read_tokens * p_cr
        + cache_creation_tokens * p_cw
    ) / 1_000_000
    return cost


def estimate_session_cost(session) -> float:
    """Estimate cost for a LiveSession object."""
    return estimate_cost(
        model=session.model,
        input_tokens=session.input_tokens,
        output_tokens=session.output_tokens,
        cache_read_tokens=session.cache_read_tokens,
        cache_creation_tokens=session.cache_creation_tokens,
    )
