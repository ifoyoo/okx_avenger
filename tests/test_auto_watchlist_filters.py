"""自动 watchlist 质量过滤与暴露上限测试。"""

from __future__ import annotations

from types import SimpleNamespace

from core.data.auto_watchlist import AutoWatchlistBuilder, _canonical_base_key


class _DummyOKX:
    def get_account_balance(self):
        return {
            "data": [
                {
                    "totalEq": "10000",
                    "details": [{"availBal": "10000"}],
                }
            ]
        }

    def get_tickers(self, _inst_type="SWAP"):
        return {
            "data": [
                {
                    "instId": "PEPE-USDT-SWAP",
                    "last": "0.001",
                    "bidPx": "0.000999",
                    "askPx": "0.001001",
                    "high24h": "0.00108",
                    "low24h": "0.00095",
                    "volCcy24h": "9000000",
                },
                {
                    "instId": "1000PEPE-USDT-SWAP",
                    "last": "0.95",
                    "bidPx": "0.9495",
                    "askPx": "0.9505",
                    "high24h": "1.01",
                    "low24h": "0.89",
                    "volCcy24h": "8500000",
                },
                {
                    "instId": "BTC-USDT-SWAP",
                    "last": "60000",
                    "bidPx": "59995",
                    "askPx": "60005",
                    "high24h": "61800",
                    "low24h": "59000",
                    "volCcy24h": "8000000",
                },
                {
                    "instId": "BADSPREAD-USDT-SWAP",
                    "last": "10",
                    "bidPx": "9.8",
                    "askPx": "10.2",
                    "high24h": "10.3",
                    "low24h": "9.7",
                    "volCcy24h": "9000000",
                },
                {
                    "instId": "BADRANGE-USDT-SWAP",
                    "last": "10",
                    "bidPx": "9.99",
                    "askPx": "10.01",
                    "high24h": "16",
                    "low24h": "8",
                    "volCcy24h": "9000000",
                },
                {
                    "instId": "BADVOL-USDT-SWAP",
                    "last": "10",
                    "bidPx": "9.99",
                    "askPx": "10.01",
                    "high24h": "10.2",
                    "low24h": "9.8",
                    "volCcy24h": "500",
                },
            ]
        }

    def instruments(self, inst_type="SWAP"):
        assert inst_type == "SWAP"
        return {
            "data": [
                {"instId": "PEPE-USDT-SWAP", "minSz": "1", "lotSz": "1", "ctVal": "0.001", "ctType": "linear"},
                {"instId": "1000PEPE-USDT-SWAP", "minSz": "1", "lotSz": "1", "ctVal": "1", "ctType": "linear"},
                {"instId": "BTC-USDT-SWAP", "minSz": "1", "lotSz": "1", "ctVal": "0.0001", "ctType": "linear"},
                {"instId": "BADSPREAD-USDT-SWAP", "minSz": "1", "lotSz": "1", "ctVal": "1", "ctType": "linear"},
                {"instId": "BADRANGE-USDT-SWAP", "minSz": "1", "lotSz": "1", "ctVal": "1", "ctType": "linear"},
                {"instId": "BADVOL-USDT-SWAP", "minSz": "1", "lotSz": "1", "ctVal": "1", "ctType": "linear"},
            ]
        }


def test_auto_watchlist_joint_filters_and_base_cap() -> None:
    runtime = SimpleNamespace(
        auto_watchlist_size=3,
        auto_watchlist_top_n=10,
        auto_watchlist_refresh_hours=24,
        auto_watchlist_cache="data/test_auto_watchlist_cache.json",
        auto_watchlist_timeframe="5m",
        auto_watchlist_higher_timeframes="1H",
        auto_watchlist_max_spread_ratio=0.003,
        auto_watchlist_max_range_ratio_24h=0.2,
        auto_watchlist_min_notional_24h=1000.0,
        auto_watchlist_max_same_base=1,
    )
    strategy = SimpleNamespace(
        balance_usage_ratio=0.7,
        default_leverage=1.0,
    )
    builder = AutoWatchlistBuilder(_DummyOKX(), strategy, runtime)

    entries = builder._build_entries(account_snapshot={"equity": 10000.0, "available": 8000.0})
    inst_ids = [item["inst_id"] for item in entries]

    assert "BADSPREAD-USDT-SWAP" not in inst_ids
    assert "BADRANGE-USDT-SWAP" not in inst_ids
    assert "BADVOL-USDT-SWAP" not in inst_ids
    assert "BTC-USDT-SWAP" in inst_ids
    assert ("PEPE-USDT-SWAP" in inst_ids) ^ ("1000PEPE-USDT-SWAP" in inst_ids)


def test_canonical_base_key_merges_leading_multiplier() -> None:
    assert _canonical_base_key("1000PEPE-USDT-SWAP") == "PEPE"
    assert _canonical_base_key("PEPE-USDT-SWAP") == "PEPE"
