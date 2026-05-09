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
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastmcp import Client
from mcp.types import CallToolResult, Tool
from openai import OpenAI
from openai.types.chat.chat_completion import ChatCompletion

from host.audits.governance_logger import AuditAction, AuditEntry, GovernanceLogger
from host.policies.config_loader import get_context_profile
from host.policies.policy_enforcer import enforce_policy
from host.session import ChatRequest, SessionContextRequest, SessionRenameRequest, SessionStartRequest, SessionStore
from host.validators.content_classifier import classify_content
from host.validators.output_validator import SchemaType, validate_output_structure
from host.validators.resource_circuit_breaker import (
    ResourceCircuitBreaker,
    ResourceLimitExceeded,
    build_resource_budget,
)
from host.validators.tool_gatekeeper import secure_tool_call

env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

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

SYSTEM_PROMPT = '你是一個可呼叫工具的 AI 助手。當你需要外部資料時，請優先呼叫可用工具，不要猜測。最終回覆請只輸出 JSON 物件，格式為 {"answer": "...", "sources": [{"source_id": "...", "tool_name": "..."}] }，source_id請依序編號，並且answer要同時在對應的位置標記出。請用標註格式如 [citation:1]。回覆使用繁體中文，且簡潔清楚。'

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


def format_tool_result(result: CallToolResult, tool_call_id: str | None = None) -> str:
    if getattr(result, "content", None):
        chunks: list[str] = []
        for item in result.content:
            text = getattr(item, "text", None)
            if text:
                chunks.append(text)
        if chunks:
            formatted = "\n".join(chunks)
    else:
        structured = getattr(result, "structuredContent", None)
        if structured is not None:
            formatted = json.dumps(structured, ensure_ascii=False)
        else:
            formatted = str(result)

    if tool_call_id:
        return f"[工具來源 ID: {tool_call_id}]\n{formatted}"
    return formatted


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped

    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def parse_structured_assistant_output(text: str) -> dict[str, Any]:
    raw_text = text.strip()
    if not raw_text:
        return {"answer": "", "sources": []}

    candidate = _strip_code_fences(raw_text)
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return {"answer": raw_text, "sources": []}

    if not isinstance(parsed, dict):
        return {"answer": raw_text, "sources": []}

    answer = parsed.get("answer")
    if answer is None:
        answer = parsed.get("content", "")

    sources = parsed.get("sources", [])
    normalized_sources = [source for source in sources if isinstance(source, dict)] if isinstance(sources, list) else []
    return {"answer": str(answer).strip(), "sources": normalized_sources}


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

        # 3) 由 policies 模組讀取上下文設定，將對應 system_prompt 合併到基礎提示詞。
        profile_data = get_context_profile(context_id)

        system_prompt = SYSTEM_PROMPT
        if isinstance(profile_data, dict):
            profile_system_prompt = str(profile_data.get("system_prompt", "")).strip()
            if profile_system_prompt:
                system_prompt = f"{SYSTEM_PROMPT}\n\n{profile_system_prompt}"

        resource_budget = build_resource_budget(profile_data if isinstance(profile_data, dict) else None)
        circuit_breaker = ResourceCircuitBreaker(resource_budget)

        history = session_record.get("messages", [])
        conversation: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        if isinstance(history, list):
            conversation.extend(item for item in history if isinstance(item, dict))

        # 4) 先加入本輪使用者訊息，再進入模型與工具循環。
        conversation.append({"role": "user", "content": user_message})

        try:
            while True:
                circuit_breaker.check()

                response = call_openai_chat(llm_client, conversation, openai_tools)
                usage = getattr(response, "usage", None)
                total_tokens = int(getattr(usage, "total_tokens", 0) or 0)
                circuit_breaker.record_model_response(total_tokens=total_tokens)
                circuit_breaker.check()

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
                        circuit_breaker.record_tool_call(tool_name=tool_name)
                        circuit_breaker.check()

                        raw_args = tool_call.function.arguments or "{}"
                        try:
                            arguments = json.loads(raw_args) if raw_args else {}
                        except json.JSONDecodeError:
                            arguments = {}

                        # 7) 工具調用前先做工具調用檢查，不合規即阻擋。
                        allowed, reason = secure_tool_call(
                            tool_name=tool_name,
                            arguments=arguments,
                            context_id=context_id,
                        )
                        # 8) 不論允許與否都記錄審計日誌，包含工具名稱、參數、上下文識別、決策結果與理由等。
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

                        # 9) 僅在通過授權後才執行 MCP 工具。
                        mcp_result = await mcp_client.call_tool(tool_name, arguments)
                        tool_text = format_tool_result(mcp_result, tool_call_id=tool_call.id)

                        # 10) 工具執行後進行輸出結構驗證。
                        output_ok, output_errors = validate_output_structure(
                            data={
                                "tool_name": tool_name,
                                "status": "success",
                                "output": tool_text,
                            },
                            schema_type=SchemaType.TOOL_RESULT,
                        )
                        # 11) 同樣記錄審計日誌，包含驗證結果與錯誤訊息等。
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

                # 12) 無需再調用工具時，將最終內容解析成結構化回覆並結束。
                structured_response = parse_structured_assistant_output(content or "")
                final_text = structured_response.get("answer", "") or "（模型沒有回傳文字內容）"
                structured_sources = structured_response.get("sources", [])
                if not isinstance(structured_sources, list):
                    structured_sources = []

                # 13) Module 6 - 內容安全分類與動態政策應用
                classification_result = await classify_content(
                    text=final_text,
                    context_id=context_id,
                )
                classification_trace_id = str(uuid4())
                governance_logger.log(
                    AuditEntry(
                        trace_id=classification_trace_id,
                        action=AuditAction.CONTENT_CLASSIFICATION,
                        timestamp=datetime.now(UTC).isoformat(),
                        context_id=context_id,
                        tool_name=None,
                        reason=f"Classification: {classification_result.classification.value}",
                        details={
                            "classification": classification_result.classification.value,
                            "risk_score": classification_result.risk_score,
                            "content_types": classification_result.content_types,
                            "confidence": classification_result.confidence,
                        },
                    )
                )

                # 根據分類結果應用政策
                policy_result = await enforce_policy(
                    classification=classification_result,
                    context_id=context_id,
                    profile_data=profile_data,
                    logger=governance_logger,
                )

                # 若被政策阻擋，直接返回阻擋回覆
                if not policy_result["allowed"]:
                    policy_trace_id = str(uuid4())
                    governance_logger.log(
                        AuditEntry(
                            trace_id=policy_trace_id,
                            action=AuditAction.CONTENT_BLOCKED_BY_POLICY,
                            timestamp=datetime.now(UTC).isoformat(),
                            context_id=context_id,
                            tool_name=None,
                            reason=policy_result["reason"],
                            details=policy_result.get("details", {}),
                        )
                    )
                    return {
                        "assistant_response": {
                            "answer": policy_result["reason"],
                            "sources": [],
                        },
                        "context_id": context_id,
                        "blocked_by_policy": True,
                    }

                # 若需修改（添加免責聲明等），更新最終文本
                if policy_result.get("modified_text"):
                    disclaimer = policy_result["modified_text"]
                    final_text = f"{disclaimer}\n\n{final_text}" if disclaimer else final_text

                # 記錄政策應用結果
                policy_audit_action = policy_result["audit_action"]
                governance_logger.log(
                    AuditEntry(
                        trace_id=str(uuid4()),
                        action=AuditAction[policy_audit_action],
                        timestamp=datetime.now(UTC).isoformat(),
                        context_id=context_id,
                        tool_name=None,
                        reason=f"Policy level: {policy_result['policy_level']}",
                        details=policy_result.get("details", {}),
                    )
                )

                # 14) 最後對整體回覆結構再次進行驗證，並記錄驗證結果。
                output_ok, output_errors = validate_output_structure(
                    data={
                        "answer": final_text,
                        "sources": structured_sources,
                        "context_id": context_id,
                        "available_tools": [tool.name for tool in mcp_tools],
                    },
                    schema_type=SchemaType.AGENT_RESPONSE,
                )
                governance_logger.log(
                    AuditEntry(
                        trace_id=str(uuid4()),
                        action=(AuditAction.OUTPUT_VALIDATION_PASS if output_ok else AuditAction.OUTPUT_VALIDATION_FAIL),
                        timestamp=datetime.now(UTC).isoformat(),
                        context_id=context_id,
                        tool_name=None,
                        reason=("agent response validation passed" if output_ok else "; ".join(output_errors)),
                        details={"schema_type": SchemaType.AGENT_RESPONSE.value},
                    )
                )

                conversation.append({"role": "assistant", "content": final_text})
                break
        except ResourceLimitExceeded as exc:
            # 15) 若在任何階段觸發資源與成本熔斷，記錄審計日誌並返回終止回覆。
            governance_logger.log(
                AuditEntry(
                    trace_id=str(uuid4()),
                    action=AuditAction.CIRCUIT_BREAKER_TRIGGERED,
                    timestamp=datetime.now(UTC).isoformat(),
                    context_id=context_id,
                    tool_name=None,
                    reason=str(exc),
                    details=exc.metrics,
                )
            )
            return {
                "assistant_response": {
                    "answer": f"任務已終止：觸發資源與成本熔斷（{str(exc)}）。",
                    "sources": [],
                },
                "context_id": context_id,
            }

    return {
        "assistant_response": structured_response,
        "context_id": context_id,
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

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def homepage():
    return FileResponse("static/index.html")

@app.get("/health")
async def health() -> dict[str, Any]:
    return {"ok": True, "service": "user-host"}


@app.post("/session/start", status_code=201)
async def session_start(payload: SessionStartRequest) -> dict[str, Any]:
    context_id = payload.context_id.strip() or "general"
    session = state.store.create(context_id=context_id, display_name=payload.display_name.strip())
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


@app.patch("/session/rename")
async def session_rename(payload: SessionRenameRequest) -> dict[str, Any]:
    try:
        state.store.rename(payload.session_id.strip(), payload.display_name.strip())
    except KeyError:
        raise HTTPException(status_code=404, detail="session not found")
    session = state.store.get(payload.session_id.strip())
    return {"ok": True, "data": session}


@app.delete("/session/{session_id}", status_code=200)
async def session_delete(session_id: str) -> dict[str, Any]:
    try:
        state.store.delete(session_id.strip())
    except KeyError:
        raise HTTPException(status_code=404, detail="session not found")
    return {"ok": True}


@app.get("/sessions")
async def sessions_list() -> dict[str, Any]:
    return {"ok": True, "data": state.store.list_sessions()}


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
        {"role": "assistant", "content": result["assistant_response"]["answer"]},
    )

    return {
        "ok": True,
        "data": {
            "session_id": session_id,
            "context_id": result["context_id"],
            "assistant_response": result["assistant_response"],
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
