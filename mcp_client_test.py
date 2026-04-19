import asyncio

from fastmcp import Client

from main import mcp


async def run_test_client() -> None:
    async with Client(mcp) as client:
        tools = await client.list_tools()
        print("Available tools:", [tool.name for tool in tools])

        result = await client.call_tool("get_weather", {"city": "Taipei"})
        if result.content:
            for item in result.content:
                text = getattr(item, "text", None)
                if text:
                    print(text)
        else:
            print(result)


if __name__ == "__main__":
    asyncio.run(run_test_client())
