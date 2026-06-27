"""Cost estimation and budget tracking for LLM calls."""
from __future__ import annotations

from onep.config import load_config


def _get_price(model: str, price_type: str) -> float:
    config = load_config()
    pricing = getattr(config.llm, "pricing", {}) or {}
    model_pricing = pricing.get(model, {})
    if isinstance(model_pricing, dict):
        return model_pricing.get(price_type, 0.0)
    return 0.0


def estimate_scan_cost(
    file_count: int,
    batch_size: int = 50,
    chars_per_file: int = 60,
    output_chars_per_file: int = 35,
) -> float:
    config = load_config()
    model = config.llm.default_model
    input_price = _get_price(model, "input")
    output_price = _get_price(model, "output")

    batches = max(1, file_count // batch_size + (1 if file_count % batch_size else 0))
    input_tokens_per_batch = (min(file_count, batch_size) * chars_per_file) / 3
    output_tokens_per_batch = (min(file_count, batch_size) * output_chars_per_file) / 3

    total_input_m = (batches * input_tokens_per_batch) / 1_000_000
    total_output_m = (batches * output_tokens_per_batch) / 1_000_000

    return total_input_m * input_price + total_output_m * output_price


def estimate_analyze_cost(
    strategy_file_count: int,
    avg_file_chars: int = 3000,
    output_chars: int = 2000,
    avg_tool_rounds: int = 4,
) -> float:
    config = load_config()
    model = config.llm.complex_model
    input_price = _get_price(model, "input")
    output_price = _get_price(model, "output")

    input_tokens = (strategy_file_count * avg_file_chars * avg_tool_rounds) / 3
    output_tokens = output_chars / 3

    return (input_tokens / 1_000_000) * input_price + (output_tokens / 1_000_000) * output_price


class CostTracker:
    def __init__(self, budget: float = 0.0):
        self.budget = budget
        self.spent = 0.0

    @property
    def remaining(self) -> float:
        return max(0, self.budget - self.spent)

    def can_continue(self) -> bool:
        if self.budget <= 0:
            return True
        return self.spent < self.budget

    def add_cost(self, amount: float) -> None:
        self.spent += amount

    def add_usage(self, prompt_tokens: int, completion_tokens: int, model: str) -> None:
        input_price = _get_price(model, "input")
        output_price = _get_price(model, "output")
        cost = (prompt_tokens / 1_000_000) * input_price + \
               (completion_tokens / 1_000_000) * output_price
        self.spent += cost

    def summary(self) -> str:
        if self.budget > 0:
            return f"${self.spent:.2f} / ${self.budget:.2f}"
        return f"${self.spent:.2f} spent"
