"""MCP server exposing market data as tools (replaces v4 REST feeds).
Run standalone:  python -m mcp_servers.market_data_server
The system normally launches it automatically via the MCP client."""
from mcp_servers import _marketdata_core as core

try:
    from mcp.server.fastmcp import FastMCP
    mcp = FastMCP("market-data")

    @mcp.tool()
    def get_candles(coin: str, count: int = 200) -> list:
        """Return recent OHLCV candles (oldest->newest) for a coin."""
        return core.get_candles(coin, count)

    @mcp.tool()
    def get_ticker(coin: str) -> dict:
        """Return latest price and 24h change for a coin."""
        return core.get_ticker(coin)

    @mcp.tool()
    def get_orderbook(coin: str) -> dict:
        """Return real L2 order-book depth imbalance (top-20 levels) for a coin."""
        return core.get_orderbook(coin)

    @mcp.tool()
    def get_taker_ratio(coin: str) -> float:
        """Return 24h taker buy ratio (takerBuyVol / totalVol). >0.5 = bullish pressure."""
        return core.get_taker_ratio(coin)

    def main():
        mcp.run(transport="stdio")
except ImportError:      # mcp package not installed -> still importable for fallback
    mcp = None
    def main():
        raise SystemExit("Install 'mcp' to run the market-data server.")

if __name__ == "__main__":
    main()
