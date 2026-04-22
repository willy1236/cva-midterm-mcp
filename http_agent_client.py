import asyncio
import json
import multiprocessing as mp
import os
import time
from typing import Any

from fastmcp import Client
from mcp.types import CallToolResult, Tool
from openai import OpenAI
from openai.types.chat.chat_completion import ChatCompletion

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8001/mcp")
AUTO_START_LOCAL_MCP = os.getenv("AUTO_START_LOCAL_MCP", "1") == "1"
MCP_HOST = os.getenv("MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.getenv("MCP_PORT", "8001"))
MCP_PATH = os.getenv("MCP_PATH", "/mcp")

SYSTEM_PROMPT = "你是一個可呼叫工具的 AI 助手。當你需要外部資料時，請優先呼叫可用工具，不要猜測。回覆使用繁體中文，且簡潔清楚。"


def run_local_http_server() -> None:
    from server.app import mcp

    mcp.run(
        transport="http",
        host=MCP_HOST,
        port=MCP_PORT,
        path=MCP_PATH,
        show_banner=False,
        log_level="warning",
    )


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


def create_openai_client() -> OpenAI:
    if not OPENAI_API_KEY:
        raise RuntimeError("請先設定 OPENAI_API_KEY 環境變數。")
    return OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)


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


async def run_agent_loop() -> None:
    async with Client(MCP_SERVER_URL) as mcp_client:
        llm_client = create_openai_client()
        mcp_tools = await mcp_client.list_tools()
        openai_tools = mcp_tools_to_openai_tools(mcp_tools)

        print(f"已連線 MCP: {MCP_SERVER_URL}")
        print("可用工具:", [t.name for t in mcp_tools])
        print("開始互動（輸入 exit 離開）")

        messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]

        while True:
            user_input = (await asyncio.to_thread(input, "\n你: ")).strip()
            if user_input.lower() in {"exit", "quit"}:
                print("已結束互動。")
                break
            if not user_input:
                continue

            messages.append({"role": "user", "content": user_input})

            while True:
                response = call_openai_chat(llm_client, messages, openai_tools)
                message = response.choices[0].message

                tool_calls = message.tool_calls or []
                content = message.content

                if tool_calls:
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

                    messages.append(
                        {
                            "role": "assistant",
                            "content": content or "",
                            "tool_calls": serialized_tool_calls,
                        }
                    )

                    for tool_call in tool_calls:
                        tool_name = tool_call.function.name
                        raw_args = tool_call.function.arguments or "{}"

                        try:
                            arguments = json.loads(raw_args) if raw_args else {}
                        except json.JSONDecodeError:
                            arguments = {}

                        print(f"[Tool] {tool_name}({arguments})")
                        mcp_result = await mcp_client.call_tool(tool_name, arguments)
                        tool_text = format_tool_result(mcp_result)

                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "name": tool_name,
                                "content": tool_text,
                            }
                        )

                    continue

                final_text = content or "（模型沒有回傳文字內容）"
                messages.append({"role": "assistant", "content": final_text})
                print(f"助理: {final_text}")
                break


def main() -> None:
    server_process: mp.Process | None = None

    try:
        if AUTO_START_LOCAL_MCP:
            server_process = mp.Process(target=run_local_http_server, daemon=True)
            server_process.start()

        asyncio.run(wait_until_mcp_ready())
        asyncio.run(run_agent_loop())
    finally:
        if server_process is not None:
            server_process.terminate()
            server_process.join(timeout=2)


if __name__ == "__main__":
    mp.freeze_support()
    main()
