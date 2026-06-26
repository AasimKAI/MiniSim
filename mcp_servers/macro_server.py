"""MCP server exposing macro context (Fear & Greed + funding rates) as tools.
Run standalone: python -m mcp_servers.macro_server
Normally launched automatically by the MCP client."""
from mcp_servers import _macro_core as core

try:
    from mcp.server.fastmcp import FastMCP
    mcp = FastMCP("macro")

    @mcp.tool()
    def get_fear_greed() -> dict:
        """Return current Fear & Greed index (0=extreme fear, 100=extreme greed)."""
        return core.get_fear_greed()

    @mcp.tool()
    def get_funding_rates() -> dict:
        """Return latest perpetual funding rates for all tracked coins."""
        return core.get_funding_rates()

    @mcp.tool()
    def get_dominance() -> dict:
        """Return BTC, ETH, and altcoin market-cap dominance from CoinGecko."""
        return core.get_dominance()

    def main():
        mcp.run(transport="stdio")
except ImportError:
    mcp = None
    def main():
        raise SystemExit("Install 'mcp' to run the macro server.")

if __name__ == "__main__":
    main()
