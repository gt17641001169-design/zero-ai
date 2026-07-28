"""MCP 服务器入口 - 支持 python -m zeroai.mcp 启动

用法：
    python -m zeroai.mcp                  # stdio 模式（默认）
    python -m zeroai.mcp --transport sse  # SSE 模式
    python -m zeroai.mcp --transport sse --host 0.0.0.0 --port 8765
"""
import asyncio
import argparse
import sys


def main():
    parser = argparse.ArgumentParser(
        prog="python -m zeroai.mcp",
        description="ZeroAI MCP Server - 暴露 ZeroAI 工具给外部 MCP 客户端",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse"],
        default="stdio",
        help="传输方式（默认 stdio）",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="SSE 模式监听地址（默认 127.0.0.1）",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="SSE 模式监听端口（默认 8765）",
    )

    args = parser.parse_args()

    if args.transport == "stdio":
        from zeroai.mcp.server import run_stdio_server
        asyncio.run(run_stdio_server())
    else:
        from zeroai.mcp.server import run_sse_server
        asyncio.run(run_sse_server(host=args.host, port=args.port))


if __name__ == "__main__":
    main()
