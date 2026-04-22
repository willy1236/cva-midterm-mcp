from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_CONFIG_PATH = Path(__file__).with_name("config.yaml")


def load_constraint_config() -> dict[str, Any]:
    with _CONFIG_PATH.open("r", encoding="utf-8") as file:
        raw = yaml.safe_load(file) or {}

    if not isinstance(raw, dict):
        raise ValueError("Invalid config format: root must be a mapping")

    return raw


def get_context_profile(context_id: str) -> dict[str, Any]:
    config = load_constraint_config()
    contexts = config.get("contexts", {})
    default_context = config.get("default_context", "general")
    selected = context_id or default_context

    profile = contexts.get(selected)
    if not isinstance(profile, dict):
        raise KeyError(f"Unknown context_id: {selected}")

    return {
        "context_id": selected,
        "identity": profile.get("identity", "Unknown"),
        "system_prompt": profile.get("system_prompt", ""),
        "absolute_rules": profile.get("absolute_rules", []),
        "tool_scope": profile.get("tool_scope", {}),
        "policy_version": config.get("version", "unknown"),
    }
