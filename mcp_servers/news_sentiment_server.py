"""MCP server exposing news headlines (no LLM — scoring happens in the main
process so the quantized model loads only once)."""
from mcp_servers import _news_core as core

try:
    from mcp.server.fastmcp import FastMCP
    mcp = FastMCP("news-sentiment")

    @mcp.tool()
    def get_headlines(coin: str, limit: int = 5) -> list:
        """Return recent headlines for a coin."""
        return core.get_headlines(coin, limit)

    def main():
        mcp.run(transport="stdio")
except ImportError:
    mcp = None
    def main():
        raise SystemExit("Install 'mcp' to run the news server.")

if __name__ == "__main__":
    main()
