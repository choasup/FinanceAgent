"""基本面数据 hook。

通过 yfinance 拉取估值 / 盈利 / 成长等基本面指标, 用于:
    * 选股过滤 (如只回测 PE < 30 且 ROE > 15% 的标的)
    * 作为 ML 模型的特征

离线 / 抓取失败时返回空 dict, 不阻断主流程。
"""

from __future__ import annotations

import pandas as pd


# 关注的核心基本面字段 (yfinance .info 键名)
FIELDS = {
    "trailingPE": "PE(TTM)",
    "forwardPE": "PE(Fwd)",
    "priceToBook": "PB",
    "returnOnEquity": "ROE",
    "profitMargins": "净利率",
    "revenueGrowth": "营收增速",
    "earningsGrowth": "盈利增速",
    "debtToEquity": "负债权益比",
    "dividendYield": "股息率",
    "marketCap": "市值",
}


def fetch(symbol: str) -> dict:
    """拉取单标的基本面指标, 返回 {中文名: 值}。失败返回 {}。"""
    try:
        import yfinance as yf

        info = yf.Ticker(symbol).info or {}
    except Exception as exc:  # noqa: BLE001
        print(f"[fundamentals] {symbol} 抓取失败: {exc}")
        return {}

    return {label: info.get(key) for key, label in FIELDS.items() if info.get(key) is not None}


def screen(symbols: list[str], min_roe: float = 0.10, max_pe: float = 40.0) -> list[str]:
    """基本面选股: 返回满足 ROE / PE 条件的标的。

    抓不到基本面数据的标的默认保留 (不因数据缺失而误杀)。
    """
    passed = []
    for s in symbols:
        f = fetch(s)
        roe = f.get("ROE")
        pe = f.get("PE(TTM)")
        if roe is not None and roe < min_roe:
            continue
        if pe is not None and pe > max_pe:
            continue
        passed.append(s)
    return passed


def snapshot_table(symbols: list[str]) -> pd.DataFrame:
    """多标的基本面快照表。"""
    rows = {s: fetch(s) for s in symbols}
    return pd.DataFrame(rows).T
