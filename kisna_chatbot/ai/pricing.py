"""Estimated per-model pricing (USD per 1M tokens)."""

# Approximate list prices — estimates only; override via env if needed.
MODEL_PRICING: dict[str, dict[str, float]] = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "llama-3.3-70b-versatile": {"input": 0.59, "output": 0.79},
    "llama-3.1-8b-instant": {"input": 0.05, "output": 0.08},
}


def estimate_cost_usd(
    model: str, prompt_tokens: int, completion_tokens: int
) -> float:
    """Estimate cost in USD from token counts."""
    rates = MODEL_PRICING.get(model, {"input": 0.0, "output": 0.0})
    input_cost = (prompt_tokens / 1_000_000) * rates["input"]
    output_cost = (completion_tokens / 1_000_000) * rates["output"]
    return round(input_cost + output_cost, 8)
