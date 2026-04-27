from __future__ import annotations

import asyncio
import json
import multiprocessing as mp
import os
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, HTTPException
from fastmcp import Client
from mcp.types import CallToolResult, TextResourceContents, Tool
from openai import OpenAI
from openai.types.chat.chat_completion import ChatCompletion

from host.audits.governance_logger import AuditAction, AuditEntry, GovernanceLogger
from host.session import ChatRequest, SessionContextRequest, SessionStartRequest, SessionStore
from host.validators.output_validator import SchemaType, validate_output_structure
from host.validators.tool_gatekeeper import secure_tool_call

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8001/mcp")
AUTO_START_LOCAL_MCP = os.getenv("AUTO_START_LOCAL_MCP", "1") == "1"
MCP_HOST = os.getenv("MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.getenv("MCP_PORT", "8001"))
MCP_PATH = os.getenv("MCP_PATH", "/mcp")

HOST_SERVER_BIND = os.getenv("HOST_SERVER_BIND", "127.0.0.1")
HOST_SERVER_PORT = int(os.getenv("HOST_SERVER_PORT", "8010"))
SESSION_FILE = Path(os.getenv("HOST_SESSION_FILE", "host_sessions.json"))
AUDIT_LOG_FILE = Path(os.getenv("GOVERNANCE_AUDIT_FILE", "logs/governance_audit.jsonl"))

SYSTEM_PROMPT = "你是一個可呼叫工具的 AI 助手。當你需要外部資料時，請優先呼叫可用工具，不要猜測。回覆使用繁體中文，且簡潔清楚。"

AUDIT_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
governance_logger = GovernanceLogger(log_file=AUDIT_LOG_FILE)


def run_local_http_server() -> None:
    from mcpServer.app import mcp

    mcp.run(
        transport="http",
        host=MCP_HOST,
        port=MCP_PORT,
        path=MCP_PATH,
        show_banner=False,
        log_level="info",
    )


def create_openai_client() -> OpenAI:
    if not OPENAI_API_KEY:
        raise RuntimeError("請先設定 OPENAI_API_KEY 環境變數。")
    return OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)


async def wait_until_mcp_ready(timeout_sec: float = 10.0) -> None:
    start = time.time()
    while time.time() - start < timeout_sec:
        try:
            async with Client(MCP_SERVER_URL) as client:
                await client.list_tools()
                return
        except Exception:
            await asyncio.sleep(0.3)
    raise TimeoutError(f"MCP server not ready: {MCP_SERVER_URL}")


def mcp_tools_to_openai_tools(mcp_tools: list[Tool]) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for tool in mcp_tools:
        schema = tool.inputSchema or {"type": "object", "properties": {}}
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": schema,
                },
            }
        )
    return tools


def call_openai_chat(
    llm_client: OpenAI,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> ChatCompletion:
    try:
        return llm_client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0,
        )
    except Exception as exc:
        raise RuntimeError(f"OpenAI API error: {exc}") from exc


def format_tool_result(result: CallToolResult) -> str:
    if getattr(result, "content", None):
        chunks: list[str] = []
        for item in result.content:
            text = getattr(item, "text", None)
            if text:
                chunks.append(text)
        if chunks:
            return "\n".join(chunks)

    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        return json.dumps(structured, ensure_ascii=False)

    return str(result)


def parse_resource_json(contents: list[TextResourceContents]) -> dict[str, Any]:
    if not contents:
        raise RuntimeError("MCP resource returned no contents")

    text = contents[0].text
    if not text:
        raise RuntimeError("MCP resource returned empty text")

    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise RuntimeError("MCP resource payload must be a JSON object")

    return payload


async def run_single_turn(
    *,
    llm_client: OpenAI,
    session_record: dict[str, Any],
    user_message: str,
) -> dict[str, Any]:
    """執行單輪對話，包含 MCP 工具調用、合規檢查與輸出驗證。"""
    # 1) 取得本輪對話的上下文識別。
    context_id = str(session_record.get("context_id", "general"))

    async with Client(MCP_SERVER_URL) as mcp_client:
        # 2) 載入可用 MCP 工具，並轉換為 OpenAI 的函式呼叫格式。
        mcp_tools = await mcp_client.list_tools()
        openai_tools = mcp_tools_to_openai_tools(mcp_tools)

        # 3) 讀取上下文設定，將對應 system_prompt 合併到基礎提示詞。
        profile_contents = await mcp_client.read_resource(f"resource://profile/{context_id}")
        profile_payload = parse_resource_json(profile_contents)
        profile_data = profile_payload.get("data") if isinstance(profile_payload, dict) else None

        system_prompt = SYSTEM_PROMPT
        if isinstance(profile_data, dict):
            profile_system_prompt = str(profile_data.get("system_prompt", "")).strip()
            if profile_system_prompt:
                system_prompt = f"{SYSTEM_PROMPT}\n\n{profile_system_prompt}"

        history = session_record.get("messages", [])
        conversation: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        if isinstance(history, list):
            conversation.extend(item for item in history if isinstance(item, dict))

        # 4) 先加入本輪使用者訊息，再進入模型與工具循環。
        conversation.append({"role": "user", "content": user_message})

        while True:
            response = call_openai_chat(llm_client, conversation, openai_tools)
            message = response.choices[0].message
            tool_calls = message.tool_calls or []
            content = message.content

            if tool_calls:
                # 5) 先把模型的工具調用意圖寫入對話，再開始執行工具。
                serialized_tool_calls = [
                    {
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments or "{}",
                        },
                    }
                    for tool_call in tool_calls
                ]

                conversation.append(
                    {
                        "role": "assistant",
                        "content": content or "",
                        "tool_calls": serialized_tool_calls,
                    }
                )

                for tool_call in tool_calls:
                    # 6) 安全解析模型輸出的工具參數。
                    tool_name = tool_call.function.name
                    raw_args = tool_call.function.arguments or "{}"
                    try:
                        arguments = json.loads(raw_args) if raw_args else {}
                    except json.JSONDecodeError:
                        arguments = {}

                    # 7) 工具調用前先做治理檢查，不合規即阻擋。
                    allowed, reason = secure_tool_call(
                        tool_name=tool_name,
                        arguments=arguments,
                        context_id=context_id,
                    )
                    audit_trace_id = str(uuid4())
                    governance_logger.log(
                        AuditEntry(
                            trace_id=audit_trace_id,
                            action=(AuditAction.TOOL_CALL_ALLOWED if allowed else AuditAction.TOOL_CALL_REJECTED),
                            timestamp=datetime.now(UTC).isoformat(),
                            context_id=context_id,
                            tool_name=tool_name,
                            reason=reason,
                            details={"arguments": arguments},
                        )
                    )

                    if not allowed:
                        # 回填政策違規訊息為工具回應，讓模型可安全續跑。
                        policy_message = json.dumps(
                            {
                                "error": "policy_violation",
                                "reason": reason,
                                "trace_id": audit_trace_id,
                            },
                            ensure_ascii=False,
                        )
                        conversation.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "name": tool_name,
                                "content": policy_message,
                            }
                        )
                        continue

                    # 8) 僅在通過授權後才執行 MCP 工具。
                    mcp_result = await mcp_client.call_tool(tool_name, arguments)
                    tool_text = format_tool_result(mcp_result)

                    # 9) 工具執行後進行輸出結構驗證。
                    output_ok, output_errors = validate_output_structure(
                        data={
                            "tool_name": tool_name,
                            "status": "success",
                            "output": tool_text,
                        },
                        schema_type=SchemaType.TOOL_RESULT,
                    )
                    governance_logger.log(
                        AuditEntry(
                            trace_id=str(uuid4()),
                            action=(AuditAction.OUTPUT_VALIDATION_PASS if output_ok else AuditAction.OUTPUT_VALIDATION_FAIL),
                            timestamp=datetime.now(UTC).isoformat(),
                            context_id=context_id,
                            tool_name=tool_name,
                            reason=("output validation passed" if output_ok else "; ".join(output_errors)),
                            details={"schema_type": SchemaType.TOOL_RESULT.value},
                        )
                    )

                    if not output_ok:
                        # 若驗證失敗，回填錯誤訊息而非使用無效原始輸出。
                        validation_message = json.dumps(
                            {
                                "error": "output_validation_failed",
                                "details": output_errors,
                            },
                            ensure_ascii=False,
                        )
                        conversation.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "name": tool_name,
                                "content": validation_message,
                            }
                        )
                        continue

                    conversation.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": tool_name,
                            "content": tool_text,
                        }
                    )
                continue

            # 10) 無需再調用工具時，輸出最終文字回應並結束。
            final_text = content or "（模型沒有回傳文字內容）"
            conversation.append({"role": "assistant", "content": final_text})
            break

    return {
        "assistant": final_text,
        "context_id": context_id,
        "profile": profile_data,
        "messages": conversation[1:],
        "available_tools": [tool.name for tool in mcp_tools],
    }


class AppState:
    def __init__(self) -> None:
        self.store = SessionStore(SESSION_FILE)
        self.llm_client: OpenAI | None = None
        self.server_process: mp.Process | None = None


state = AppState()


@asynccontextmanager
async def lifespan(_: FastAPI):
    if AUTO_START_LOCAL_MCP:
        print("Auto-starting local MCP server...")
        state.server_process = mp.Process(target=run_local_http_server, daemon=True)
        state.server_process.start()

    await wait_until_mcp_ready()
    try:
        yield
    finally:
        if state.server_process is not None:
            state.server_process.terminate()
            state.server_process.join(timeout=2)


app = FastAPI(title="User Host MCP Server", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "service": "user-host"}


@app.post("/session/start", status_code=201)
async def session_start(payload: SessionStartRequest) -> dict[str, Any]:
    context_id = payload.context_id.strip() or "general"
    session = state.store.create(context_id=context_id)
    return {"ok": True, "data": session}


@app.post("/session/context")
async def session_context(payload: SessionContextRequest) -> dict[str, Any]:
    session_id = payload.session_id.strip()
    context_id = payload.context_id.strip()
    if not session_id or not context_id:
        raise HTTPException(status_code=400, detail="session_id and context_id are required")

    try:
        state.store.set_context(session_id, context_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="session not found")

    session = state.store.get(session_id)
    return {"ok": True, "data": session}


@app.get("/session/{session_id}")
async def session_get(session_id: str) -> dict[str, Any]:
    session = state.store.get(session_id.strip())
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return {"ok": True, "data": session}


@app.post("/chat")
async def chat(payload: ChatRequest) -> dict[str, Any]:
    session_id = payload.session_id.strip()
    message = payload.message.strip()
    if not session_id or not message:
        raise HTTPException(status_code=400, detail="session_id and message are required")

    session = state.store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    if state.llm_client is None:
        try:
            state.llm_client = create_openai_client()
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    try:
        result = await run_single_turn(
            llm_client=state.llm_client,
            session_record=session,
            user_message=message,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    state.store.append_message(session_id, {"role": "user", "content": message})
    state.store.append_message(
        session_id,
        {"role": "assistant", "content": result["assistant"]},
    )

    return {
        "ok": True,
        "data": {
            "session_id": session_id,
            "context_id": result["context_id"],
            "assistant": result["assistant"],
            "available_tools": result["available_tools"],
        },
    }


def main() -> None:
    uvicorn.run(
        app,
        host=HOST_SERVER_BIND,
        port=HOST_SERVER_PORT,
        log_level="info",
    )


if __name__ == "__main__":
    mp.freeze_support()
    main()
