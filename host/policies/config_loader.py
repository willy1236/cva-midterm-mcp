from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from cachetools import TTLCache, cached

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.yaml"
config_cache = TTLCache(maxsize=1, ttl=600)  # 10 minutes cache for config loading


@cached(config_cache)
def load_constraint_config() -> dict[str, Any]:
    if not _CONFIG_PATH.exists():
        raise FileNotFoundError(f"Constraint config not found at repo root: {_CONFIG_PATH}")

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
