from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from cachetools import TTLCache, cached

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.yaml"
config_cache = TTLCache(maxsize=1, ttl=600)  # 10 minutes cache for config loading


def _merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = _merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


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

    global_resource_limits = config.get("resource_limits", {})
    if not isinstance(global_resource_limits, dict):
        global_resource_limits = {}

    context_resource_limits = profile.get("resource_limits", {})
    if not isinstance(context_resource_limits, dict):
        context_resource_limits = {}

    resource_limits = {**global_resource_limits, **context_resource_limits}
    policy_defaults = config.get("policy_defaults", {})
    if not isinstance(policy_defaults, dict):
        policy_defaults = {}

    # 優先從 context profile 裡讀 policy（key 可為 policy 或 policy_rules），
    # 若不存在則回退到舊的頂層 policy_rules 配置（相容性）
    profile_policy = profile.get("policy") or profile.get("policy_rules")
    if profile_policy and isinstance(profile_policy, dict):
        policy_overrides = profile_policy
    else:
        policy_overrides = config.get("policy_rules", {}).get(selected, {})

    if not isinstance(policy_overrides, dict):
        policy_overrides = {}

    policy_rules = _merge_dicts(policy_defaults, policy_overrides)

    return {
        "context_id": selected,
        "identity": profile.get("identity", "Unknown"),
        "system_prompt": profile.get("system_prompt", ""),
        "absolute_rules": profile.get("absolute_rules", []),
        "tool_scope": profile.get("tool_scope", {}),
        "resource_limits": resource_limits,
        "policy_rules": policy_rules,
        "policy_version": config.get("version", "unknown"),
    }
