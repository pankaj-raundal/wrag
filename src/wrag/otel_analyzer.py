"""OTel JSONL analyzer — parses Copilot Chat OpenTelemetry file export.

Reads the JSONL file written by:
  "github.copilot.chat.otel.exporterType": "file"
  "github.copilot.chat.otel.outfile": ".../.data/copilot-otel.jsonl"

Produces per-session token usage broken down by whether wRag MCP tools were used,
giving real (not estimated) token savings data for the management dashboard.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from wrag.config import _PROJECT_ROOT

OTEL_FILE = _PROJECT_ROOT / ".data" / "copilot-otel.jsonl"

# wRag tool names as seen in gen_ai.tool.name
WRAG_TOOLS = {"search_code", "search_docs", "search_symbol", "list_apps", "app_overview"}

# Copilot native file-reading tools (what wRag replaces)
NATIVE_TOOLS = {"readFile", "searchFiles", "findFiles", "grepFiles", "runCommand"}


@dataclass
class SessionStats:
    """Token stats for one Copilot conversation session."""

    conversation_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    wrag_tool_calls: int = 0
    native_tool_calls: int = 0
    total_tool_calls: int = 0
    turns: int = 0
    wrag_tools_used: list[str] = field(default_factory=list)
    native_tools_used: list[str] = field(default_factory=list)

    @property
    def used_wrag(self) -> bool:
        return self.wrag_tool_calls > 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class TokenSavings:
    """Aggregated comparison: sessions with vs without wRag."""

    # Sessions with wRag
    wrag_sessions: int = 0
    wrag_input_tokens: int = 0
    wrag_output_tokens: int = 0
    wrag_tool_calls: int = 0

    # Sessions without wRag
    baseline_sessions: int = 0
    baseline_input_tokens: int = 0
    baseline_output_tokens: int = 0
    baseline_tool_calls: int = 0

    @property
    def avg_wrag_input(self) -> float:
        return self.wrag_input_tokens / max(self.wrag_sessions, 1)

    @property
    def avg_baseline_input(self) -> float:
        return self.baseline_input_tokens / max(self.baseline_sessions, 1)

    @property
    def input_token_reduction_pct(self) -> float:
        if self.avg_baseline_input == 0:
            return 0.0
        return round((1 - self.avg_wrag_input / self.avg_baseline_input) * 100, 1)

    @property
    def total_tokens_saved(self) -> int:
        """Extrapolated: how many input tokens saved vs baseline average."""
        return round(self.wrag_sessions * (self.avg_baseline_input - self.avg_wrag_input))

    def to_dict(self) -> dict:
        return {
            "wrag_sessions": self.wrag_sessions,
            "baseline_sessions": self.baseline_sessions,
            "wrag_avg_input_tokens": round(self.avg_wrag_input),
            "baseline_avg_input_tokens": round(self.avg_baseline_input),
            "input_token_reduction_pct": self.input_token_reduction_pct,
            "total_input_tokens_saved": self.total_tokens_saved,
            "wrag_total_input_tokens": self.wrag_input_tokens,
            "baseline_total_input_tokens": self.baseline_input_tokens,
            "wrag_tool_calls_served": self.wrag_tool_calls,
            "native_tool_calls_replaced": self.baseline_tool_calls,
        }


def _parse_span(span: dict, sessions: dict[str, SessionStats]) -> None:
    """Extract token and tool data from a single OTel span record."""
    attrs = span.get("attributes", {})

    # Normalize: OTel file export can use either flat dict or key-value list format
    if isinstance(attrs, list):
        attrs = {item["key"]: item.get("value", {}).get("stringValue")
                 or item.get("value", {}).get("intValue")
                 or item.get("value", {}).get("boolValue")
                 for item in attrs}

    conv_id = attrs.get("gen_ai.conversation.id") or span.get("traceId", "unknown")
    op = attrs.get("gen_ai.operation.name", "")

    session = sessions[conv_id]
    session.conversation_id = conv_id

    if op in ("invoke_agent", "chat"):
        in_tok = attrs.get("gen_ai.usage.input_tokens", 0)
        out_tok = attrs.get("gen_ai.usage.output_tokens", 0)
        if isinstance(in_tok, (int, float)):
            session.input_tokens += int(in_tok)
        if isinstance(out_tok, (int, float)):
            session.output_tokens += int(out_tok)

    if op == "execute_tool":
        tool_name = attrs.get("gen_ai.tool.name", "")
        session.total_tool_calls += 1

        if tool_name in WRAG_TOOLS:
            session.wrag_tool_calls += 1
            if tool_name not in session.wrag_tools_used:
                session.wrag_tools_used.append(tool_name)
        elif tool_name in NATIVE_TOOLS:
            session.native_tool_calls += 1
            if tool_name not in session.native_tools_used:
                session.native_tools_used.append(tool_name)


def _parse_log_record(record: dict, sessions: dict[str, SessionStats]) -> None:
    """Handle copilot_chat.agent.turn log events for per-turn token counts."""
    attrs = record.get("attributes", {})
    if isinstance(attrs, list):
        attrs = {item["key"]: item.get("value", {}).get("stringValue")
                 or item.get("value", {}).get("intValue")
                 or item.get("value", {}).get("boolValue")
                 for item in attrs}

    # agent.turn events have turn-level tokens — avoid double-counting with span tokens.
    # We use these only to increment turn counter.
    conv_id = attrs.get("gen_ai.conversation.id") or record.get("traceId", "unknown")
    if conv_id and conv_id in sessions:
        sessions[conv_id].turns += 1


def parse_otel_file(path: Optional[str] = None) -> list[SessionStats]:
    """Parse the OTel JSONL export file and return per-session stats."""
    otel_path = Path(path) if path else OTEL_FILE

    if not otel_path.exists():
        return []

    sessions: dict[str, SessionStats] = defaultdict(lambda: SessionStats(conversation_id=""))

    with open(otel_path, encoding="utf-8", errors="replace") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            # OTel file format: each line is an ExportTraceServiceRequest / ExportLogsServiceRequest
            # or a flat span record depending on the exporter version.
            # Handle both formats.
            if "resourceSpans" in record:
                for rs in record.get("resourceSpans", []):
                    for ss in rs.get("scopeSpans", []):
                        for span in ss.get("spans", []):
                            _parse_span(span, sessions)
            elif "resourceLogs" in record:
                for rl in record.get("resourceLogs", []):
                    for sl in rl.get("scopeLogs", []):
                        for log_record in sl.get("logRecords", []):
                            _parse_log_record(log_record, sessions)
            elif "attributes" in record and "traceId" in record:
                # Flat span record
                _parse_span(record, sessions)

    # Filter out sessions with no token data (noise / incomplete spans)
    return [s for s in sessions.values() if s.input_tokens > 0 or s.wrag_tool_calls > 0]


def get_token_savings(path: Optional[str] = None) -> TokenSavings:
    """Compute aggregated token savings comparing wRag vs non-wRag sessions."""
    sessions = parse_otel_file(path)
    result = TokenSavings()

    for s in sessions:
        if s.used_wrag:
            result.wrag_sessions += 1
            result.wrag_input_tokens += s.input_tokens
            result.wrag_output_tokens += s.output_tokens
            result.wrag_tool_calls += s.wrag_tool_calls
        else:
            result.baseline_sessions += 1
            result.baseline_input_tokens += s.input_tokens
            result.baseline_output_tokens += s.output_tokens
            result.baseline_tool_calls += s.native_tool_calls

    return result


def get_token_summary() -> dict:
    """Return a summary dict for the web UI and CLI."""
    savings = get_token_savings()
    sessions = parse_otel_file()

    wrag_sessions = [s for s in sessions if s.used_wrag]
    baseline_sessions = [s for s in sessions if not s.used_wrag]

    return {
        "has_data": len(sessions) > 0,
        "total_sessions": len(sessions),
        "savings": savings.to_dict(),
        "per_session": [
            {
                "conversation_id": s.conversation_id[:12] + "...",
                "used_wrag": s.used_wrag,
                "input_tokens": s.input_tokens,
                "output_tokens": s.output_tokens,
                "total_tokens": s.total_tokens,
                "wrag_tool_calls": s.wrag_tool_calls,
                "native_tool_calls": s.native_tool_calls,
                "wrag_tools": s.wrag_tools_used,
            }
            for s in sessions
        ],
        "wrag_session_count": len(wrag_sessions),
        "baseline_session_count": len(baseline_sessions),
        "otel_file": str(OTEL_FILE),
        "otel_enabled": OTEL_FILE.exists(),
    }
