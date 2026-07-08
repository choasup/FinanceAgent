"""单票深度分析 (Deep Dossier) —— 把 Agent 从"几行评级"做成研究档案。

全部基于本地日线缓存离线计算, 输出:
  - 因子记分卡: 每个因子的取值、得分贡献、说明 (透明, 可审计)
  - 关键价位: 支撑/阻力/均线, 以及 "什么价位会改变结论"
  - 风险画像: 波动率 (现状 vs 一年分位)、贝塔、当前回撤、单日最惨
  - 量能异动: 放量大涨/大跌的事件日
  - 相对强弱: 相对 SPY / QQQ 的超额收益

仅供研究, 不构成投资建议。
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from quant import data
from quant.indicators import rsi as rsi_ind

TRADING_DAYS = 252


def _load(symbol: str, days: int = 600) -> pd.DataFrame:
    start = (pd.Timestamp.now() - pd.Timedelta(days=days)).strftime("%Y-%m-%d")
    df = data.load(symbol, start=start, allow_synthetic=False)
    if len(df) < 60:
        raise ValueError(f"{symbol}: 行情不足 ({len(df)} 根), 无法深度分析")
    return df


def _clean(v):
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def _rating(score: float) -> str:
    if score >= 50:
        return "强烈看多"
    if score >= 20:
        return "看多"
    if score > -20:
        return "中性"
    if score > -50:
        return "看空"
    return "强烈看空"


def deep_analyze(symbol: str) -> dict:
    symbol = symbol.strip().upper()
    df = _load(symbol)
    close, high, low, volume = df["close"], df["high"], df["low"], df["volume"]
    last = float(close.iloc[-1])
    rets = close.pct_change().dropna()

    # ---- 均线结构 ----
    sma = {n: (float(close.rolling(n).mean().iloc[-1]) if len(close) >= n else None)
           for n in (20, 50, 200)}
    above = {n: (last > s if s else None) for n, s in sma.items()}
    alignment = None
    if all(sma.values()):
        if sma[20] > sma[50] > sma[200]:
            alignment = "多头排列 (20>50>200)"
        elif sma[20] < sma[50] < sma[200]:
            alignment = "空头排列 (20<50<200)"
        else:
            alignment = "均线纠缠"

    # ---- 多周期动量 ----
    def ret_n(n):
        return _clean(last / float(close.iloc[-n - 1]) - 1) if len(close) > n else None
    momentum = {"1w": ret_n(5), "1m": ret_n(21), "3m": ret_n(63), "6m": ret_n(126)}

    # ---- 风险画像 ----
    vol20 = float(rets.tail(20).std() * np.sqrt(TRADING_DAYS))
    vol_series = rets.rolling(20).std().dropna() * np.sqrt(TRADING_DAYS)
    vol_pctile = float((vol_series < vol20).mean()) if len(vol_series) > 60 else None
    peak = float(close.cummax().iloc[-1])
    curr_dd = last / peak - 1
    worst_day = rets.min()
    worst_day_date = rets.idxmin().strftime("%Y-%m-%d")
    beta = None
    try:
        spy = _load("SPY")["close"].pct_change().dropna()
        joint = pd.concat([rets, spy], axis=1, join="inner").dropna().tail(TRADING_DAYS)
        if len(joint) > 60:
            cov = joint.cov()
            beta = _clean(round(float(cov.iloc[0, 1] / cov.iloc[1, 1]), 2))
    except Exception:  # noqa: BLE001
        pass

    # ---- 相对强弱 (vs SPY / QQQ) ----
    relative = {}
    for bench in ("SPY", "QQQ"):
        try:
            b = _load(bench)["close"]
            joint = pd.concat([close, b], axis=1, join="inner").dropna()
            for label, n in (("1m", 21), ("3m", 63)):
                if len(joint) > n:
                    r_s = joint.iloc[-1, 0] / joint.iloc[-n - 1, 0] - 1
                    r_b = joint.iloc[-1, 1] / joint.iloc[-n - 1, 1] - 1
                    relative[f"vs_{bench}_{label}"] = _clean(round(float(r_s - r_b), 4))
        except Exception:  # noqa: BLE001
            pass

    # ---- 量能异动事件日 (放量 + 大波动) ----
    vol_avg = volume.rolling(120, min_periods=30).mean()
    events = []
    recent = df.tail(90)
    for d in recent.index:
        v, va = float(volume[d]), float(vol_avg[d]) if not np.isnan(vol_avg[d]) else None
        r = float(close[d] / close.shift(1)[d] - 1) if not np.isnan(close.shift(1)[d]) else 0
        if va and v > 2.5 * va and abs(r) > 0.05:
            events.append({"date": d.strftime("%Y-%m-%d"), "ret": round(r, 4),
                           "vol_ratio": round(v / va, 1)})
    events = sorted(events, key=lambda e: e["date"], reverse=True)[:6]

    # ---- 关键价位 ----
    hi52 = float(close.tail(252).max())
    lo52 = float(close.tail(252).min())
    hi20 = float(high.tail(20).max())
    lo20 = float(low.tail(20).min())
    levels = {
        "last": round(last, 2),
        "support_20d": round(lo20, 2),
        "resistance_20d": round(hi20, 2),
        "sma50": round(sma[50], 2) if sma[50] else None,
        "sma200": round(sma[200], 2) if sma[200] else None,
        "high_52w": round(hi52, 2),
        "low_52w": round(lo52, 2),
    }
    # 什么价位会改变结论
    triggers = []
    if sma[50] and last < sma[50]:
        triggers.append(f"站上 50 日均线 ${sma[50]:.2f} ({(sma[50]/last-1)*100:+.0f}%) → 短期企稳信号")
    if sma[200] and last < sma[200]:
        triggers.append(f"站上 200 日均线 ${sma[200]:.2f} ({(sma[200]/last-1)*100:+.0f}%) → 长期趋势转多")
    if sma[200] and last > sma[200]:
        triggers.append(f"跌破 200 日均线 ${sma[200]:.2f} ({(sma[200]/last-1)*100:+.0f}%) → 长期趋势转空")
    if last > lo20:
        triggers.append(f"跌破 20 日低点 ${lo20:.2f} ({(lo20/last-1)*100:+.0f}%) → 破位, 短线止损参考")

    # ---- 因子记分卡 (透明打分) ----
    rsi14 = _clean(round(float(rsi_ind(close, 14).iloc[-1]), 1))
    card = []

    def factor(name, value, score, max_score, note):
        card.append({"name": name, "value": value, "score": score, "max": max_score, "note": note})
        return score

    total = 0.0
    if sma[200]:
        d200 = last / sma[200] - 1
        s = 15 if d200 > 0 else -15
        total += factor("长期趋势 (vs 200日线)", f"{d200:+.1%}", s, 15,
                        "价格在 200 日均线上方为多" if d200 > 0 else "价格在 200 日均线下方为空")
    if alignment:
        s = 10 if "多头" in alignment else (-10 if "空头" in alignment else 0)
        total += factor("均线结构", alignment, s, 10, "20/50/200 日均线的排列方向")
    if momentum["3m"] is not None:
        m = momentum["3m"]
        s = 20 if m > 0.05 else (-20 if m < -0.05 else 0)
        total += factor("中期动量 (3月)", f"{m:+.1%}", s, 20, "±5% 以内视为中性")
    if momentum["1m"] is not None:
        m = momentum["1m"]
        s = 5 if m > 0.03 else (-5 if m < -0.03 else 0)
        total += factor("短期动量 (1月)", f"{m:+.1%}", s, 5, "辅助确认")
    if rsi14 is not None:
        s = 15 if rsi14 <= 30 else (-15 if rsi14 >= 75 else 0)
        total += factor("超买超卖 (RSI14)", f"{rsi14}", s, 15,
                        "≤30 超卖加分 (反弹机会), ≥75 超买减分")
    s = -10 if vol20 > 0.45 else 0
    total += factor("波动风险 (20日年化)", f"{vol20:.0%}", s, 10,
                    ">45% 记为高波动减分" + (f", 处于一年 {vol_pctile:.0%} 分位" if vol_pctile else ""))
    rel3 = relative.get("vs_SPY_3m")
    if rel3 is not None:
        s = 10 if rel3 > 0.05 else (-10 if rel3 < -0.05 else 0)
        total += factor("相对强弱 (3月 vs SPY)", f"{rel3:+.1%}", s, 10,
                        "跑赢大盘加分, 跑输减分")
    if curr_dd < -0.5:
        total += factor("深度回撤状态", f"{curr_dd:.0%}", -5, 5,
                        "距历史高点回撤过半, 下落刀警示")

    total = max(-100.0, min(100.0, total))

    return {
        "symbol": symbol,
        "as_of": close.index[-1].strftime("%Y-%m-%d"),
        "price": round(last, 2),
        "score": round(total, 0),
        "rating": _rating(total),
        "scorecard": card,
        "momentum": {k: _clean(v) for k, v in momentum.items()},
        "ma": {"sma20": round(sma[20], 2) if sma[20] else None, "sma50": levels["sma50"],
               "sma200": levels["sma200"], "alignment": alignment,
               "above": {str(k): v for k, v in above.items()}},
        "risk": {
            "vol20_ann": round(vol20, 3),
            "vol_percentile_1y": _clean(round(vol_pctile, 2)) if vol_pctile is not None else None,
            "beta_vs_spy_1y": beta,
            "drawdown_from_peak": round(curr_dd, 3),
            "worst_day": {"date": worst_day_date, "ret": round(float(worst_day), 4)},
        },
        "relative": relative,
        "levels": levels,
        "triggers": triggers,
        "volume_events": events,
        "disclaimer": "仅供研究, 不构成投资建议",
    }
