"""Benchmark recording — capture real before/after comparison data."""

from __future__ import annotations

import json
import time
from pathlib import Path

from wrag.config import _PROJECT_ROOT

BENCHMARK_FILE = _PROJECT_ROOT / ".data" / "benchmark.json"


def _load_benchmark() -> dict:
    """Load existing benchmark data."""
    if BENCHMARK_FILE.exists():
        with open(BENCHMARK_FILE, "r") as f:
            return json.load(f)
    return {"tests": []}


def _save_benchmark(data: dict):
    """Save benchmark data."""
    BENCHMARK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(BENCHMARK_FILE, "w") as f:
        json.dump(data, f, indent=2)


def record_test(
    prompt: str,
    without_wrag_requests: float,
    with_wrag_requests: float,
    without_wrag_tool_calls: int,
    with_wrag_tool_calls: int,
    notes: str = "",
):
    """Record a benchmark test result.

    Args:
        prompt: The exact prompt tested
        without_wrag_requests: Copilot usage counter delta without wRag
        with_wrag_requests: Copilot usage counter delta with wRag
        without_wrag_tool_calls: Visible tool calls in chat without wRag
        with_wrag_tool_calls: Visible tool calls in chat with wRag
        notes: Optional notes
    """
    data = _load_benchmark()
    data["tests"].append({
        "timestamp": time.time(),
        "prompt": prompt,
        "without_wrag": {
            "requests": without_wrag_requests,
            "tool_calls": without_wrag_tool_calls,
        },
        "with_wrag": {
            "requests": with_wrag_requests,
            "tool_calls": with_wrag_tool_calls,
        },
        "savings": {
            "requests_saved": without_wrag_requests - with_wrag_requests,
            "percentage": round(
                (1 - with_wrag_requests / max(without_wrag_requests, 0.1)) * 100, 1
            ),
        },
        "notes": notes,
    })
    _save_benchmark(data)


def get_benchmark_summary() -> dict:
    """Get summary of all benchmark tests."""
    data = _load_benchmark()
    tests = data.get("tests", [])

    if not tests:
        return {"count": 0, "tests": [], "totals": {}}

    total_without = sum(t["without_wrag"]["requests"] for t in tests)
    total_with = sum(t["with_wrag"]["requests"] for t in tests)
    avg_savings_pct = round(
        (1 - total_with / max(total_without, 0.1)) * 100, 1
    )

    return {
        "count": len(tests),
        "tests": tests,
        "totals": {
            "without_wrag_requests": total_without,
            "with_wrag_requests": total_with,
            "total_saved": total_without - total_with,
            "average_savings_percent": avg_savings_pct,
        },
    }
