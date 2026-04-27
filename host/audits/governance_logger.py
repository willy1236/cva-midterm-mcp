from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class AuditAction(StrEnum):
    TOOL_CALL_ALLOWED = "TOOL_CALL_ALLOWED"
    TOOL_CALL_REJECTED = "TOOL_CALL_REJECTED"
    OUTPUT_VALIDATION_PASS = "OUTPUT_VALIDATION_PASS"
    OUTPUT_VALIDATION_FAIL = "OUTPUT_VALIDATION_FAIL"
    CITATION_VERIFICATION_PASS = "CITATION_VERIFICATION_PASS"
    CITATION_VERIFICATION_PARTIAL = "CITATION_VERIFICATION_PARTIAL"
    CITATION_VERIFICATION_FAIL = "CITATION_VERIFICATION_FAIL"
    CIRCUIT_BREAKER_TRIGGERED = "CIRCUIT_BREAKER_TRIGGERED"
    POLICY_VIOLATION = "POLICY_VIOLATION"


@dataclass
class AuditEntry:
    trace_id: str
    action: AuditAction
    timestamp: str
    context_id: str | None = None
    tool_name: str | None = None
    reason: str | None = None
    details: dict | None = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "action": self.action.value,
            "timestamp": self.timestamp,
            "context_id": self.context_id,
            "tool_name": self.tool_name,
            "reason": self.reason,
            "details": self.details or {},
        }


class GovernanceLogger:
    def __init__(self, log_file: Path | None = None) -> None:
        self._log_file = log_file or Path("governance_audit.jsonl")
        self._ensure_file()

    def _ensure_file(self) -> None:
        if not self._log_file.exists():
            self._log_file.touch()

    def log(self, entry: AuditEntry) -> None:
        line = json.dumps(entry.to_dict(), ensure_ascii=False) + "\n"
        with self._log_file.open("a", encoding="utf-8") as f:
            f.write(line)

    def get_entries(self, *, action: AuditAction | None = None) -> list[dict]:
        if not self._log_file.exists():
            return []

        entries = []
        with self._log_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if action is None or entry.get("action") == action.value:
                        entries.append(entry)
                except json.JSONDecodeError:
                    pass

        return entries

    def summary(self) -> dict:
        if not self._log_file.exists():
            return {
                "total": 0,
                "by_action": {},
                "by_context": {},
                "by_tool": {},
            }

        all_entries = self.get_entries()
        by_action: dict[str, int] = {}
        by_context: dict[str, int] = {}
        by_tool: dict[str, int] = {}

        for entry in all_entries:
            action = entry.get("action", "unknown")
            by_action[action] = by_action.get(action, 0) + 1

            context = entry.get("context_id", "unknown")
            if context:
                by_context[context] = by_context.get(context, 0) + 1

            tool = entry.get("tool_name", "unknown")
            if tool:
                by_tool[tool] = by_tool.get(tool, 0) + 1

        return {
            "total": len(all_entries),
            "by_action": by_action,
            "by_context": by_context,
            "by_tool": by_tool,
        }

    def rejections(self) -> list[dict]:
        return self.get_entries(action=AuditAction.TOOL_CALL_REJECTED)
