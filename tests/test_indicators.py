"""测试技术指标计算."""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import pytest

from core.data.features import candles_to_dataframe


class TestIndicators:
    """技术指标测试类."""

    @pytest.fixture
    def sample_candles(self):
        """创建示例 K 线数据."""
        # 生成 100 根 K 线
        candles = []
        base_price = 100.0
        for i in range(100):
            ts = str(1704067200000 + i * 300000)  # 5 分钟间隔
            open_price = base_price + i * 0.1
            high = open_price + 1.0
            low = open_price - 1.0
            close = open_price + 0.5
            volume = 1000 + i * 10
            candles.append([
                ts,
                str(open_price),
                str(high),
                str(low),
                str(close),
                str(volume),
                str(volume * close),
                str(volume * close),
                "1",
            ])
        return candles

    def test_candles_to_dataframe_basic(self, sample_candles):
        """测试基本 K 线转换."""
        df = candles_to_dataframe(sample_candles)

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 100
        assert "close" in df.columns
        assert "rsi" in df.columns

    def test_rsi_indicator(self, sample_candles):
        """测试 RSI 指标."""
        df = candles_to_dataframe(sample_candles)

        assert "rsi" in df.columns
        assert df["rsi"].notna().any()
        # RSI 应该在 0-100 之间
        assert (df["rsi"].dropna() >= 0).all()
        assert (df["rsi"].dropna() <= 100).all()

    def test_stochastic_indicator(self, sample_candles):
        """测试 Stochastic 指标."""
        df = candles_to_dataframe(sample_candles)

        assert "stoch_k" in df.columns
        assert "stoch_d" in df.columns
        assert df["stoch_k"].notna().any()
        assert df["stoch_d"].notna().any()
        # Stochastic 应该在 0-100 之间
        assert (df["stoch_k"].dropna() >= 0).all()
        assert (df["stoch_k"].dropna() <= 100).all()

    def test_kdj_indicator(self, sample_candles):
        """测试 KDJ 指标."""
        df = candles_to_dataframe(sample_candles)

        assert "kdj_j" in df.columns
        assert df["kdj_j"].notna().any()
        # KDJ J 线可以超出 0-100 范围
        assert df["kdj_j"].dtype in [float, "float64"]

    def test_cci_indicator(self, sample_candles):
        """测试 CCI 指标."""
        df = candles_to_dataframe(sample_candles)

        assert "cci" in df.columns
        assert df["cci"].notna().any()
        # CCI 可以是任意值
        assert df["cci"].dtype in [float, "float64"]

    def test_adx_indicator(self, sample_candles):
        """测试 ADX 指标."""
        df = candles_to_dataframe(sample_candles)

        assert "adx" in df.columns
        assert "adx_pos" in df.columns
        assert "adx_neg" in df.columns
        assert df["adx"].notna().any()
        # ADX 应该在 0-100 之间
        assert (df["adx"].dropna() >= 0).all()
        assert (df["adx"].dropna() <= 100).all()

    def test_williams_r_indicator(self, sample_candles):
        """测试 Williams %R 指标."""
        df = candles_to_dataframe(sample_candles)

        assert "williams_r" in df.columns
        assert df["williams_r"].notna().any()
        # Williams %R 应该在 -100 到 0 之间
        assert (df["williams_r"].dropna() >= -100).all()
        assert (df["williams_r"].dropna() <= 0).all()

    def test_ichimoku_indicator(self, sample_candles):
        """测试 Ichimoku 指标."""
        df = candles_to_dataframe(sample_candles)

        assert "ichimoku_conv" in df.columns
        assert "ichimoku_base" in df.columns
        assert "ichimoku_a" in df.columns
        assert "ichimoku_b" in df.columns
        assert df["ichimoku_conv"].notna().any()
        assert df["ichimoku_base"].notna().any()

    def test_macd_indicator(self, sample_candles):
        """测试 MACD 指标."""
        df = candles_to_dataframe(sample_candles)

        assert "macd" in df.columns
        assert "macd_signal" in df.columns
        assert "macd_hist" in df.columns
        assert df["macd"].notna().any()

    def test_bollinger_bands(self, sample_candles):
        """测试布林带指标."""
        df = candles_to_dataframe(sample_candles)

        assert "bb_high" in df.columns
        assert "bb_low" in df.columns
        assert df["bb_high"].notna().any()
        assert df["bb_low"].notna().any()
        # 上轨应该大于下轨
        assert (df["bb_high"].dropna() >= df["bb_low"].dropna()).all()

    def test_atr_indicator(self, sample_candles):
        """测试 ATR 指标."""
        df = candles_to_dataframe(sample_candles)

        assert "atr" in df.columns
        assert df["atr"].notna().any()
        # ATR 应该是非负数
        assert (df["atr"].dropna() >= 0).all()

    def test_volume_indicators(self, sample_candles):
        """测试成交量指标."""
        df = candles_to_dataframe(sample_candles)

        assert "obv" in df.columns
        assert "mfi" in df.columns
        assert df["obv"].notna().any()
        assert df["mfi"].notna().any()
        # MFI 应该在 0-100 之间
        assert (df["mfi"].dropna() >= 0).all()
        assert (df["mfi"].dropna() <= 100).all()

    def test_all_indicators_present(self, sample_candles):
        """测试所有指标都存在."""
        df = candles_to_dataframe(sample_candles)

        expected_indicators = [
            "rsi", "ema_fast", "ema_slow", "macd", "macd_signal", "macd_hist",
            "atr", "bb_high", "bb_low", "obv", "mfi",
            "stoch_k", "stoch_d", "kdj_j", "cci",
            "adx", "adx_pos", "adx_neg", "williams_r",
            "ichimoku_conv", "ichimoku_base", "ichimoku_a", "ichimoku_b",
        ]

        for indicator in expected_indicators:
            assert indicator in df.columns, f"缺少指标: {indicator}"

    def test_no_nan_in_final_rows(self, sample_candles):
        """测试最后几行没有 NaN 值（经过 bfill/ffill）."""
        df = candles_to_dataframe(sample_candles)

        # 检查最后 10 行
        last_rows = df.tail(10)
        for col in df.columns:
            if col != "ts":  # 时间戳列不检查
                assert last_rows[col].notna().all(), f"列 {col} 在最后 10 行有 NaN"

    def test_dataframe_sorted_by_time(self, sample_candles):
        """测试数据按时间排序."""
        df = candles_to_dataframe(sample_candles)

        assert df["ts"].is_monotonic_increasing


if __name__ == "__main__":
    # 运行测试
    pytest.main([__file__, "-v", "--tb=short"])
