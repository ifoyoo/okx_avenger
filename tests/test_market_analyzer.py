"""测试 MarketAnalyzer 市场分析器."""

import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import pytest

from core.analysis import MarketAnalyzer, MarketAnalysis
from config.settings import get_settings


class TestMarketAnalyzer:
    """MarketAnalyzer 测试类."""

    @pytest.fixture
    def analyzer(self):
        """创建 MarketAnalyzer 实例."""
        settings = get_settings()
        return MarketAnalyzer(settings)

    @pytest.fixture
    def sample_features(self):
        """创建示例特征数据."""
        data = {
            "ts": pd.date_range("2024-01-01", periods=100, freq="5min"),
            "open": [100 + i * 0.1 for i in range(100)],
            "high": [101 + i * 0.1 for i in range(100)],
            "low": [99 + i * 0.1 for i in range(100)],
            "close": [100.5 + i * 0.1 for i in range(100)],
            "volume": [1000 + i * 10 for i in range(100)],
            "rsi": [50 + (i % 20) for i in range(100)],
            "ema_fast": [100 + i * 0.1 for i in range(100)],
            "ema_slow": [100 + i * 0.08 for i in range(100)],
            "macd": [0.1 + i * 0.01 for i in range(100)],
            "macd_signal": [0.08 + i * 0.01 for i in range(100)],
            "atr": [2.0 for _ in range(100)],
            "bb_high": [102 + i * 0.1 for i in range(100)],
            "bb_low": [98 + i * 0.1 for i in range(100)],
            "stoch_k": [50 + (i % 30) for i in range(100)],
            "stoch_d": [48 + (i % 30) for i in range(100)],
            "kdj_j": [52 + (i % 30) for i in range(100)],
            "cci": [(i % 200) - 100 for i in range(100)],
            "adx": [20 + (i % 20) for i in range(100)],
            "adx_pos": [15 + (i % 15) for i in range(100)],
            "adx_neg": [10 + (i % 10) for i in range(100)],
            "williams_r": [-50 + (i % 40) for i in range(100)],
            "ichimoku_conv": [100 + i * 0.1 for i in range(100)],
            "ichimoku_base": [100 + i * 0.09 for i in range(100)],
            "ichimoku_a": [101 + i * 0.1 for i in range(100)],
            "ichimoku_b": [99 + i * 0.1 for i in range(100)],
            "mfi": [50 + (i % 30) for i in range(100)],
        }
        return pd.DataFrame(data)

    def test_analyzer_initialization(self, analyzer):
        """测试分析器初始化."""
        assert analyzer is not None
        assert analyzer.settings is not None

    def test_analyze_basic(self, analyzer, sample_features):
        """测试基本分析功能."""
        result = analyzer.analyze(
            inst_id="BTC-USDT-SWAP",
            timeframe="5m",
            features=sample_features,
        )

        assert isinstance(result, MarketAnalysis)
        assert result.text is not None
        assert len(result.text) > 0
        assert result.summary is not None
        assert result.history_hint is not None

    def test_analyze_with_snapshot(self, analyzer, sample_features):
        """测试带市场快照的分析."""
        result = analyzer.analyze(
            inst_id="BTC-USDT-SWAP",
            timeframe="5m",
            features=sample_features,
            snapshot=None,  # 简化测试，不提供快照
        )

        assert isinstance(result, MarketAnalysis)
        assert result.trend_strength >= 0
        assert result.trend_strength <= 1
        assert result.momentum_score >= -1
        assert result.momentum_score <= 1

    def test_analyze_with_account_snapshot(self, analyzer, sample_features):
        """测试带账户快照的分析."""
        account_snapshot = {
            "equity": 10000.0,
            "available": 8000.0,
            "available_pct": 0.8,
        }

        result = analyzer.analyze(
            inst_id="BTC-USDT-SWAP",
            timeframe="5m",
            features=sample_features,
            account_snapshot=account_snapshot,
        )

        assert isinstance(result, MarketAnalysis)
        assert "账户权益" in result.text
        assert "10000.00" in result.text

    def test_trend_strength_calculation(self, analyzer, sample_features):
        """测试趋势强度计算."""
        trend_strength = analyzer._calculate_trend_strength(sample_features, None)

        assert isinstance(trend_strength, float)
        assert 0 <= trend_strength <= 1

    def test_momentum_calculation(self, analyzer, sample_features):
        """测试动量评分计算."""
        momentum_score = analyzer._calculate_momentum(sample_features)

        assert isinstance(momentum_score, float)
        assert -1 <= momentum_score <= 1

    def test_risk_identification(self, analyzer, sample_features):
        """测试风险识别."""
        risks = analyzer._identify_risks(
            features=sample_features,
            higher_features=None,
            risk_note="测试风险提示",
            account_snapshot={"available_pct": 0.2},
        )

        assert isinstance(risks, list)
        assert "测试风险提示" in risks
        assert "可用资金不足" in risks

    def test_analysis_text_contains_indicators(self, analyzer, sample_features):
        """测试分析文本包含所有关键指标."""
        result = analyzer.analyze(
            inst_id="BTC-USDT-SWAP",
            timeframe="5m",
            features=sample_features,
        )

        # 检查关键指标是否出现在分析文本中
        assert "趋势" in result.text
        assert "动量" in result.text
        assert "RSI" in result.text
        assert "MACD" in result.text
        assert "EMA" in result.text
        assert "CCI" in result.text
        assert "ADX" in result.text or "趋势强度" in result.text

    def test_analysis_with_high_volatility(self, analyzer, sample_features):
        """测试高波动率场景."""
        # 修改 ATR 为高值
        sample_features["atr"] = 10.0

        result = analyzer.analyze(
            inst_id="BTC-USDT-SWAP",
            timeframe="5m",
            features=sample_features,
        )

        assert "高波动率" in result.risk_factors

    def test_analysis_structure(self, analyzer, sample_features):
        """测试分析结果结构完整性."""
        result = analyzer.analyze(
            inst_id="BTC-USDT-SWAP",
            timeframe="5m",
            features=sample_features,
        )

        # 检查所有必需字段
        assert hasattr(result, "text")
        assert hasattr(result, "summary")
        assert hasattr(result, "history_hint")
        assert hasattr(result, "trend_strength")
        assert hasattr(result, "momentum_score")
        assert hasattr(result, "support_levels")
        assert hasattr(result, "resistance_levels")
        assert hasattr(result, "risk_factors")

        # 检查列表类型
        assert isinstance(result.support_levels, list)
        assert isinstance(result.resistance_levels, list)
        assert isinstance(result.risk_factors, list)

    def test_analysis_exposes_structured_assessments(self, analyzer, sample_features):
        result = analyzer.analyze(
            inst_id="BTC-USDT-SWAP",
            timeframe="5m",
            features=sample_features,
        )

        assert result.analysis_version == "v2"
        assert result.trend.direction in {"bullish", "bearish", "range"}
        assert 0 <= result.trend.strength <= 1
        assert result.momentum.label in {"overbought", "oversold", "bullish", "bearish", "neutral"}
        assert -1 <= result.momentum.score <= 1
        assert isinstance(result.levels.supports, list)
        assert isinstance(result.levels.resistances, list)
        assert isinstance(result.risk.factors, list)

    def test_legacy_fields_are_backfilled_from_assessments(self, analyzer, sample_features):
        result = analyzer.analyze(
            inst_id="BTC-USDT-SWAP",
            timeframe="5m",
            features=sample_features,
        )

        assert result.trend_strength == result.trend.strength
        assert result.momentum_score == result.momentum.score
        assert result.support_levels == result.levels.supports
        assert result.resistance_levels == result.levels.resistances
        assert result.risk_factors == result.risk.factors

    def test_support_resistance_detection(self, analyzer, sample_features):
        df = sample_features.copy()
        for idx in range(len(df)):
            wave = ((idx % 20) - 10) * 0.3
            center = 100 + wave
            df.loc[idx, "open"] = center - 0.1
            df.loc[idx, "high"] = center + 0.6
            df.loc[idx, "low"] = center - 0.6
            df.loc[idx, "close"] = center
        result = analyzer.analyze(
            inst_id="BTC-USDT-SWAP",
            timeframe="5m",
            features=df,
        )
        assert len(result.support_levels) >= 1
        assert len(result.resistance_levels) >= 1
        assert "支撑位" in result.text or "阻力位" in result.text

    def test_bearish_sample_produces_bearish_trend_label(self, analyzer, sample_features):
        df = sample_features.copy()
        df["open"] = [200 - i * 0.75 for i in range(len(df))]
        df["high"] = [201 - i * 0.75 for i in range(len(df))]
        df["low"] = [199 - i * 0.75 for i in range(len(df))]
        df["close"] = [200 - i * 0.8 for i in range(len(df))]
        df["ema_fast"] = [200 - i * 0.9 for i in range(len(df))]
        df["ema_slow"] = [200 - i * 0.6 for i in range(len(df))]
        df["adx"] = [35.0 for _ in range(len(df))]
        df["adx_pos"] = [12.0 for _ in range(len(df))]
        df["adx_neg"] = [28.0 for _ in range(len(df))]
        df["rsi"] = [35.0 for _ in range(len(df))]
        df["stoch_k"] = [30.0 for _ in range(len(df))]
        df["stoch_d"] = [35.0 for _ in range(len(df))]
        df["williams_r"] = [-65.0 for _ in range(len(df))]

        result = analyzer.analyze(
            inst_id="BTC-USDT-SWAP",
            timeframe="5m",
            features=df,
        )

        assert result.trend.direction == "bearish"
        assert "下跌" in result.text or "看跌" in result.text


if __name__ == "__main__":
    # 运行测试
    pytest.main([__file__, "-v", "--tb=short"])
