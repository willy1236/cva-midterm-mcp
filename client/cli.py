from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_BASE_URL = os.getenv("HOST_SERVER_URL", "http://127.0.0.1:8010")
DEFAULT_CHAT_TIMEOUT = float(os.getenv("HOST_CHAT_TIMEOUT", "300"))


@dataclass
class ClientState:
    base_url: str
    session_id: str | None = None


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


def cmd_get_session_data(state: ClientState) -> dict[str, Any] | None:
    if not state.session_id:
        return None

    status, data = http_json(
        base_url=state.base_url,
        method="GET",
        path=f"/session/{state.session_id}",
    )
    if status != 200:
        return None

    session = data.get("data") if isinstance(data.get("data"), dict) else None
    return session if isinstance(session, dict) else None


def cmd_switch_context(state: ClientState) -> None:
    if not state.session_id:
        print("請先建立 session 或手動設定 session_id")
        return

    session = cmd_get_session_data(state)
    current_context_id = str(session.get("context_id") or "general") if session else "general"

    context_id = ask("new context_id", default=current_context_id)
    status, data = http_json(
        base_url=state.base_url,
        method="POST",
        path="/session/context",
        payload={"session_id": state.session_id, "context_id": context_id},
    )
    print(f"HTTP {status}")
    print_json("session/context", data)


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
        timeout=DEFAULT_CHAT_TIMEOUT,
    )
    print(f"HTTP {status}")
    print_json("chat", data)

    if status == 0 and isinstance(data.get("error"), str) and "timed out" in data["error"].lower():
        print("提示：/chat 已超過目前的等待時間，但伺服器可能仍在處理該輪對話。可將 HOST_CHAT_TIMEOUT 調大後再試。")


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


def cmd_list_sessions(state: ClientState) -> None:
    status, data = http_json(
        base_url=state.base_url,
        method="GET",
        path="/sessions",
    )
    print(f"HTTP {status}")

    sessions = data.get("data") if isinstance(data.get("data"), list) else []
    if not sessions:
        print("目前沒有任何 session")
        return

    print("目前 session 清單:")
    for index, session in enumerate(sessions, start=1):
        if not isinstance(session, dict):
            continue
        session_id = str(session.get("session_id") or "-")
        context_id = str(session.get("context_id") or "-")
        updated_at = str(session.get("updated_at") or "-")
        message_count = len(session.get("messages", [])) if isinstance(session.get("messages"), list) else 0
        print(f"{index}. session_id={session_id} | context_id={context_id} | messages={message_count} | updated_at={updated_at}")


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
        {"base_url": state.base_url, "session_id": state.session_id},
    )


def print_menu() -> None:
    print("\n=== Host Flow CLI ===")
    print("1) health 檢查伺服器狀態")
    print("2) session/start 建立新 session")
    print("3) sessions 列出現有 session")
    print("4) session/context 切換 context")
    print("5) chat 發送訊息")
    print("6) session/{id} 獲取 session 資訊")
    print("7) 顯示本地狀態")
    print("8) 設定 session_id")
    print("9) 設定 base_url")
    print("10) quit")


def run_cli() -> int:
    state = ClientState(base_url=DEFAULT_BASE_URL.rstrip("/"))

    print("Host server 可互動測試工具")
    print(f"預設 base_url: {state.base_url}")

    actions = {
        "1": cmd_health,
        "2": cmd_start_session,
        "3": cmd_list_sessions,
        "4": cmd_switch_context,
        "5": cmd_chat,
        "6": cmd_get_session,
        "7": cmd_show_state,
        "8": cmd_set_session_id,
        "9": cmd_set_base_url,
    }

    while True:
        print_menu()
        choice = input("選項: ").strip().lower()

        if choice in {"10", "q", "quit", "exit"}:
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
