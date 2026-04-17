from fastmcp import FastMCP

# 初始化 MCP 伺服器
mcp = FastMCP("My API Server")


@mcp.tool()
def get_weather(city: str) -> str:
    """獲取指定城市的當前天氣。"""
    return f"{city} 的天氣晴朗，25°C"


if __name__ == "__main__":
    mcp.run()
