"""Stock Agent (规则引擎 + 工具集) 冒烟测试, 合成数据离线可跑。

运行: python tests/test_agent.py  或  python -m pytest tests/ -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quant.agent import tools
from quant.agent.analyst import analyze, rank, rank_table


def test_price_snapshot():
    snap = tools.get_price_snapshot("TEST_AGENT")
    assert snap["symbol"] == "TEST_AGENT"
    assert snap["last_close"] is not None
    assert "return_3m" in snap


def test_technical_indicators():
    tech = tools.get_technical_indicators("TEST_AGENT")
    assert tech["rsi14"] is None or 0 <= tech["rsi14"] <= 100
    assert "golden_cross" in tech
    assert "momentum_3m" in tech


def test_backtest_tool():
    bt = tools.run_backtest("TEST_AGENT", strategy="momentum")
    assert bt["strategy"] == "momentum"
    assert "strategy_sharpe" in bt and "beats_buyhold" in bt


def test_tools_json_serializable():
    import json

    for fn in (tools.get_price_snapshot, tools.get_technical_indicators):
        json.dumps(fn("TEST_AGENT"))  # 不抛异常即通过
    json.dumps(tools.run_backtest("TEST_AGENT"))


def test_analyze_verdict():
    v = analyze("TEST_AGENT", with_fundamentals=False)
    assert -100 <= v.score <= 100
    assert v.rating in ("强烈看多", "看多", "中性", "看空", "强烈看空")
    assert isinstance(v.reasons, list) and isinstance(v.risks, list)
    assert len(v.pretty()) > 0


def test_rank_multi():
    vs = rank(["TEST_AGENT", "TEST_AGENT2"], with_fundamentals=False)
    assert len(vs) == 2
    assert vs[0].score >= vs[1].score  # 已按分排序
    assert len(rank_table(vs).splitlines()) >= 4


def test_llm_tool_definitions_valid():
    """LLM 工具定义与实现一一对应, schema 结构合法。"""
    names = {t["name"] for t in tools.TOOLS}
    assert names == set(tools.TOOL_IMPL.keys())
    for t in tools.TOOLS:
        assert t["input_schema"]["type"] == "object"
        assert "symbol" in t["input_schema"]["properties"]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed.")
