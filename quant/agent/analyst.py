"""规则引擎分析师 —— 多因子打分, 离线可用。

因子覆盖: 趋势 / 动量 / 超买超卖 / 波动风险 / 历史信号有效性(回测) / 基本面。
输出结构化 Verdict: 评级、得分、逐条理由、风险提示。

注意: 这是量化研究工具, 输出不构成投资建议。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import tools


@dataclass
class Verdict:
    symbol: str
    as_of: str
    score: float                    # -100 ~ +100
    rating: str                     # 强烈看多/看多/中性/看空/强烈看空
    reasons: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    snapshot: dict = field(default_factory=dict)
    technicals: dict = field(default_factory=dict)
    backtest: dict = field(default_factory=dict)
    fundamentals: dict = field(default_factory=dict)

    def pretty(self) -> str:
        lines = [
            f"┌─ {self.symbol}  ({self.as_of})",
            f"│ 评级: {self.rating}   综合得分: {self.score:+.0f} / ±100",
            "│",
            "│ 依据:",
        ]
        lines += [f"│   + {r}" for r in self.reasons] or ["│   (无明显信号)"]
        if self.risks:
            lines.append("│ 风险:")
            lines += [f"│   ! {r}" for r in self.risks]
        lines.append("└─ 仅供研究, 不构成投资建议")
        return "\n".join(lines)


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


def analyze(symbol: str, with_fundamentals: bool = True) -> Verdict:
    """对单只股票做多因子分析, 返回结构化评级。"""
    snap = tools.get_price_snapshot(symbol)
    tech = tools.get_technical_indicators(symbol)
    bt = tools.run_backtest(symbol, strategy="sma_cross")
    fnd = tools.get_fundamentals(symbol) if with_fundamentals else {"available": False}

    score = 0.0
    reasons: list[str] = []
    risks: list[str] = []

    # -- 趋势 (最高 ±35) --
    if tech.get("price_vs_sma200") is not None:
        if tech["price_vs_sma200"] > 0:
            score += 15
            reasons.append(f"价格位于200日均线上方 ({tech['price_vs_sma200']:+.1%}), 长期趋势向上")
        else:
            score -= 15
            risks.append(f"价格位于200日均线下方 ({tech['price_vs_sma200']:+.1%}), 长期趋势偏弱")
    if tech.get("golden_cross") is True:
        score += 10
        reasons.append("50日均线在200日均线上方 (金叉形态)")
    elif tech.get("golden_cross") is False:
        score -= 10
        risks.append("50日均线在200日均线下方 (死叉形态)")
    if tech.get("macd_above_zero") and tech.get("macd_hist", 0) and tech["macd_hist"] > 0:
        score += 10
        reasons.append("MACD 位于零轴上方且柱状图为正, 短期动能向上")

    # -- 动量 (±20) --
    mom = tech.get("momentum_3m")
    if mom is not None:
        if mom > 0.05:
            score += 20
            reasons.append(f"3个月动量 {mom:+.1%}, 中期走强")
        elif mom < -0.05:
            score -= 20
            risks.append(f"3个月动量 {mom:+.1%}, 中期走弱")

    # -- 超买超卖 (±15, 反向因子) --
    rsi = tech.get("rsi14")
    if rsi is not None:
        if rsi >= 75:
            score -= 15
            risks.append(f"RSI14={rsi:.0f}, 显著超买, 短期回调风险")
        elif rsi <= 30:
            score += 15
            reasons.append(f"RSI14={rsi:.0f}, 超卖区域, 存在反弹机会")

    # -- 波动风险 (最高 -10) --
    vol = tech.get("volatility_20d_ann")
    if vol is not None and vol > 0.45:
        score -= 10
        risks.append(f"近20日年化波动率 {vol:.0%}, 波动偏高, 注意仓位控制")

    # -- 历史信号有效性 (±10) --
    if bt.get("beats_buyhold"):
        score += 10
        reasons.append(
            f"双均线策略历史回测跑赢买入持有 (夏普 {bt['strategy_sharpe']:.2f} vs {bt['buyhold_sharpe']:.2f}), 趋势信号在该标的上有效"
        )
    else:
        risks.append("趋势策略历史回测未跑赢买入持有, 技术信号参考价值有限")

    # -- 基本面 (±10) --
    if fnd.get("available"):
        roe = fnd.get("ROE")
        pe = fnd.get("PE(TTM)")
        if roe is not None and roe > 0.15:
            score += 5
            reasons.append(f"ROE {roe:.0%}, 盈利质量较好")
        if pe is not None:
            if 0 < pe < 20:
                score += 5
                reasons.append(f"PE(TTM) {pe:.1f}, 估值不高")
            elif pe > 50:
                score -= 5
                risks.append(f"PE(TTM) {pe:.1f}, 估值偏贵")

    score = max(-100.0, min(100.0, score))
    return Verdict(
        symbol=symbol,
        as_of=snap.get("as_of", ""),
        score=score,
        rating=_rating(score),
        reasons=reasons,
        risks=risks,
        snapshot=snap,
        technicals=tech,
        backtest=bt,
        fundamentals=fnd,
    )


def rank(symbols: list[str], **kwargs) -> list[Verdict]:
    """批量分析并按得分排序 (高 -> 低)。单个失败不阻断整体。"""
    verdicts = []
    for s in symbols:
        try:
            verdicts.append(analyze(s, **kwargs))
        except Exception as exc:  # noqa: BLE001
            print(f"[agent] {s} 分析失败: {exc}")
    return sorted(verdicts, key=lambda v: v.score, reverse=True)


def rank_table(verdicts: list[Verdict]) -> str:
    header = f"{'排名':<4}{'标的':<8}{'评级':<10}{'得分':>6}  {'RSI':>5}  {'3月动量':>8}  {'距52周高':>9}"
    lines = [header, "-" * len(header)]
    for i, v in enumerate(verdicts, 1):
        rsi = v.technicals.get("rsi14")
        mom = v.technicals.get("momentum_3m")
        dd = v.snapshot.get("pct_below_52w_high")
        lines.append(
            f"{i:<4}{v.symbol:<8}{v.rating:<10}{v.score:>+5.0f}  "
            f"{rsi if rsi is None else f'{rsi:.0f}':>5}  "
            f"{mom if mom is None else f'{mom:+.1%}':>8}  "
            f"{dd if dd is None else f'{dd:+.1%}':>9}"
        )
    return "\n".join(lines)
