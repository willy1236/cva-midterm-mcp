from __future__ import annotations

from typing import Any

from host.policies.config_loader import get_context_profile

READ_ONLY_KEYWORDS = {"delete", "create", "write", "update", "drop", "insert", "modify", "remove"}


def _has_write_mutation(arguments: dict[str, Any] | None) -> bool:
    if arguments is None:
        return False

    for key, value in arguments.items():
        key_lower = key.lower()
        if any(keyword in key_lower for keyword in READ_ONLY_KEYWORDS):
            return True

        if isinstance(value, str) and any(keyword in value.lower() for keyword in READ_ONLY_KEYWORDS):
            return True

        if isinstance(value, dict) and _has_write_mutation(value):
            return True

    return False


class ToolAccessDeniedError(Exception):
    pass


def secure_tool_call(
    *,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    context_id: str = "general",
) -> tuple[bool, str]:
    try:
        profile = get_context_profile(context_id)
    except KeyError:
        return False, f"Unknown context_id: {context_id}"

    tool_scope = profile.get("tool_scope", {})
    allowed_tools = tool_scope.get("allowed", [])
    mode = tool_scope.get("mode", "read-only")

    if tool_name not in allowed_tools:
        return False, f"Tool '{tool_name}' is not in allowed scope for context '{context_id}'"

    if mode == "read-only" and _has_write_mutation(arguments):
        return False, f"Tool '{tool_name}' is read-only but detected write mutation in arguments"

    return True, "allowed"
