"""MCP server exposing the exchange (paper simulator or ccxt) as tools."""
from mcp_servers import _exchange_core as core

try:
    from mcp.server.fastmcp import FastMCP
    mcp = FastMCP("exchange")

    @mcp.tool()
    def balance() -> dict:
        """Return cash, equity, and open position count."""
        return core.balance()

    @mcp.tool()
    def positions() -> list:
        """Return all open positions with unrealised PnL."""
        return core.positions()

    @mcp.tool()
    def place_order(coin: str, side: str, quantity: float,
                    client_order_id: str = "") -> dict:
        """Place a market order. side = BUY or SELL. Idempotent on client_order_id."""
        return core.place_order(coin, side, quantity, client_order_id or None)

    @mcp.tool()
    def accrue_funding(rates: dict = None) -> dict:
        """Settle perpetual funding on synthetic paper shorts (pro-rata 8h)."""
        return core.accrue_funding(rates)

    @mcp.tool()
    def update_meta(coin: str, peak_pnl: float = None, add_target: int = None,
                    extra: dict = None) -> dict:
        """Persist exit-tracking metadata for a position (peak PnL / taken TP
        level / per-position strategy exit overrides)."""
        return core.update_meta(coin, peak_pnl, add_target, extra)

    def main():
        mcp.run(transport="stdio")
except ImportError:
    mcp = None
    def main():
        raise SystemExit("Install 'mcp' to run the exchange server.")

if __name__ == "__main__":
    main()
