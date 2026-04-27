from __future__ import annotations

import multiprocessing as mp
import os
import time
from urllib.error import URLError
from urllib.request import urlopen


def run_mcp_server() -> None:
    from mcpServer.app import mcp

    host = os.getenv("MCP_HOST", "127.0.0.1")
    port = int(os.getenv("MCP_PORT", "8001"))
    path = os.getenv("MCP_PATH", "/mcp")

    mcp.run(
        transport="http",
        host=host,
        port=port,
        path=path,
        show_banner=False,
        log_level="warning",
    )


def run_user_host_server() -> None:
    # main.py 已獨立啟動 MCP server，避免 user_host_server 再啟一份。
    os.environ["AUTO_START_LOCAL_MCP"] = "0"
    from host.server import main as run_host_main

    run_host_main()


def wait_http_ready(url: str, timeout_sec: float = 20.0) -> None:
    start = time.time()
    while time.time() - start < timeout_sec:
        try:
            with urlopen(url, timeout=2.0) as response:
                if 200 <= int(response.getcode()) < 500:
                    return
        except URLError:
            pass
        time.sleep(0.3)
    raise TimeoutError(f"Service not ready: {url}")


def main() -> int:
    host_bind = os.getenv("HOST_SERVER_BIND", "127.0.0.1")
    host_port = int(os.getenv("HOST_SERVER_PORT", "8010"))
    host_server_url = os.getenv("HOST_SERVER_URL", f"http://{host_bind}:{host_port}").rstrip("/")

    os.environ["HOST_SERVER_URL"] = host_server_url

    mcp_proc = mp.Process(target=run_mcp_server, daemon=True)
    host_proc = mp.Process(target=run_user_host_server, daemon=True)

    mcp_proc.start()
    host_proc.start()

    try:
        wait_http_ready(f"{host_server_url}/health", timeout_sec=30.0)

        from host_flow_cli import run_cli

        return run_cli()
    finally:
        if host_proc.is_alive():
            host_proc.terminate()
            host_proc.join(timeout=2)
        if mcp_proc.is_alive():
            mcp_proc.terminate()
            mcp_proc.join(timeout=2)


if __name__ == "__main__":
    mp.freeze_support()
    raise SystemExit(main())
