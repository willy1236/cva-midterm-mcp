from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_BASE_URL = os.getenv("HOST_SERVER_URL", "http://127.0.0.1:8010")


@dataclass
class ClientState:
    base_url: str
    session_id: str | None = None
    context_id: str | None = None


def http_json(
    *,
    base_url: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    timeout: float = 20.0,
) -> tuple[int, dict[str, Any]]:
    body = None
    headers = {"Accept": "application/json"}

    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(
        url=f"{base_url.rstrip('/')}{path}",
        data=body,
        headers=headers,
        method=method.upper(),
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            status = int(response.getcode())
            raw = response.read().decode("utf-8")
            data = json.loads(raw) if raw else {}
            return status, data if isinstance(data, dict) else {"raw": data}
    except HTTPError as exc:
        raw = exc.read().decode("utf-8") if exc.fp is not None else ""
        try:
            data = json.loads(raw) if raw else {"error": str(exc)}
        except json.JSONDecodeError:
            data = {"error": raw or str(exc)}
        return int(exc.code), data if isinstance(data, dict) else {"raw": data}
    except URLError as exc:
        return 0, {"error": f"network error: {exc}"}


def print_json(title: str, payload: dict[str, Any]) -> None:
    print(f"\n[{title}]")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def ask(prompt: str, default: str | None = None) -> str:
    suffix = f" ({default})" if default else ""
    value = input(f"{prompt}{suffix}: ").strip()
    if value:
        return value
    return default or ""


def cmd_health(state: ClientState) -> None:
    status, data = http_json(base_url=state.base_url, method="GET", path="/health")
    print(f"HTTP {status}")
    print_json("health", data)


def cmd_start_session(state: ClientState) -> None:
    context_id = ask("context_id", default="general") or "general"
    status, data = http_json(
        base_url=state.base_url,
        method="POST",
        path="/session/start",
        payload={"context_id": context_id},
    )
    print(f"HTTP {status}")
    print_json("session/start", data)

    created = data.get("data") if isinstance(data.get("data"), dict) else None
    if created:
        state.session_id = str(created.get("session_id") or "") or None
        state.context_id = str(created.get("context_id") or "") or None


def cmd_switch_context(state: ClientState) -> None:
    if not state.session_id:
        print("請先建立 session 或手動設定 session_id")
        return

    context_id = ask("new context_id", default=state.context_id or "general")
    status, data = http_json(
        base_url=state.base_url,
        method="POST",
        path="/session/context",
        payload={"session_id": state.session_id, "context_id": context_id},
    )
    print(f"HTTP {status}")
    print_json("session/context", data)

    current = data.get("data") if isinstance(data.get("data"), dict) else None
    if current:
        state.context_id = str(current.get("context_id") or "") or state.context_id


def cmd_chat(state: ClientState) -> None:
    if not state.session_id:
        print("請先建立 session 或手動設定 session_id")
        return

    message = ask("message")
    if not message:
        print("message 不可為空")
        return

    status, data = http_json(
        base_url=state.base_url,
        method="POST",
        path="/chat",
        payload={"session_id": state.session_id, "message": message},
        timeout=60.0,
    )
    print(f"HTTP {status}")
    print_json("chat", data)

    result = data.get("data") if isinstance(data.get("data"), dict) else None
    if result:
        state.context_id = str(result.get("context_id") or "") or state.context_id


def cmd_get_session(state: ClientState) -> None:
    if not state.session_id:
        print("請先建立 session 或手動設定 session_id")
        return

    status, data = http_json(
        base_url=state.base_url,
        method="GET",
        path=f"/session/{state.session_id}",
    )
    print(f"HTTP {status}")
    print_json("session/get", data)


def cmd_set_session_id(state: ClientState) -> None:
    session_id = ask("session_id")
    if not session_id:
        print("session_id 不可為空")
        return
    state.session_id = session_id
    print(f"目前 session_id: {state.session_id}")


def cmd_set_base_url(state: ClientState) -> None:
    next_url = ask("base_url", default=state.base_url)
    if not next_url:
        print("base_url 不可為空")
        return
    state.base_url = next_url.rstrip("/")
    print(f"目前 base_url: {state.base_url}")


def cmd_show_state(state: ClientState) -> None:
    print_json(
        "local_state",
        {
            "base_url": state.base_url,
            "session_id": state.session_id,
            "context_id": state.context_id,
        },
    )


def print_menu() -> None:
    print("\n=== Host Flow CLI ===")
    print("1) health")
    print("2) session/start")
    print("3) session/context")
    print("4) chat")
    print("5) session/{id}")
    print("6) show local state")
    print("7) set session_id")
    print("8) set base_url")
    print("9) quit")


def run_cli() -> int:
    state = ClientState(base_url=DEFAULT_BASE_URL.rstrip("/"))

    print("Host server 可互動測試工具")
    print(f"預設 base_url: {state.base_url}")
    print("建議順序: 1 -> 2 -> 4 -> 5")

    actions = {
        "1": cmd_health,
        "2": cmd_start_session,
        "3": cmd_switch_context,
        "4": cmd_chat,
        "5": cmd_get_session,
        "6": cmd_show_state,
        "7": cmd_set_session_id,
        "8": cmd_set_base_url,
    }

    while True:
        print_menu()
        choice = input("選項: ").strip().lower()

        if choice in {"9", "q", "quit", "exit"}:
            print("Bye")
            return 0

        action = actions.get(choice)
        if action is None:
            print("未知選項，請重試")
            continue

        try:
            action(state)
        except KeyboardInterrupt:
            print("\n中斷目前操作")
        except Exception as exc:
            print(f"執行失敗: {exc}")


if __name__ == "__main__":
    raise SystemExit(run_cli())
