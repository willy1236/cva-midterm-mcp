import asyncio
import json
from typing import Any

from fastmcp import Client
from mcp.types import CallToolResult

from server.app import mcp


def pretty_print_result(label: str, result: object) -> None:
    print(f"\n[{label}]")
    print(json.dumps(result, ensure_ascii=False, indent=2))


def serialize_result(result: CallToolResult) -> dict[str, Any]:
    return {
        "isError": getattr(result, "is_error", getattr(result, "isError", False)),
        "structuredContent": getattr(
            result,
            "structured_content",
            getattr(result, "structuredContent", None),
        ),
        "content": [
            {
                "type": getattr(item, "type", None),
                "text": getattr(item, "text", None),
            }
            for item in (result.content or [])
        ],
    }


async def run_test_client() -> None:
    async with Client(mcp) as client:
        tools = await client.list_tools()
        print("Available tools:", [tool.name for tool in tools])

        weather = await client.call_tool("get_weather", {"city": "Taipei"})
        profile = await client.call_tool("get_agent_profile", {"context_id": "esg"})
        config = await client.call_tool("fetch_constraint_config", {})

        pretty_print_result("get_weather", serialize_result(weather))
        pretty_print_result("get_agent_profile", serialize_result(profile))
        pretty_print_result("fetch_constraint_config", serialize_result(config))


if __name__ == "__main__":
    asyncio.run(run_test_client())
