"""模拟盘 (Paper Trading) 引擎 — 多账户, 支持单票策略与组合轮动。

用真实行情、假资金, 按与回测引擎相同的纪律模拟执行:
  - 信号基于 <= 当日 的数据, 挂单在 **下一根日线的开盘价** 成交 (T+1, 无未来函数)
  - 含手续费与滑点, 调仓带宽内的微小偏差不交易

两种模式:
  - per_symbol: 每只票独立跑同一策略, 各占 1/N 资金配额 (如 trend_vol)
  - rotation:   组合统一调度, 每月初按动量排名持有最强 top_k 只 (双动量轮动)

统一语义: 挂单的 target_weight 一律指 **占账户总净值的比例**。
状态持久化在 ``data/paper/<account>.json``。仅供研究, 不连接任何真实账户。
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import pandas as pd

from quant import data
from quant.strategy import get_strategy

import strategies  # noqa: F401 -> 注册内置策略 (paper 可能被独立调用)

STATE_DIR = Path(os.environ.get("QUANT_DATA_DIR", "data")) / "paper"

TRADING_DAYS_PER_MONTH = 21

ACCOUNTS = {
    "trend_vol": {
        "mode": "per_symbol",
        "label": "趋势跟踪 (trend_vol)",
        "desc": "7 只各占 1/7 配额, 独立跑 trend_vol; 赢在控回撤",
        "strategy": "trend_vol",
        "params": {},
        # DRAM 上市不足一年, 撑不起 200 日均线策略, 暂不纳入
        "symbols": ["AAPL", "GOOGL", "TSLA", "NIO", "IONQ", "PLTR", "IREN"],
        "min_bars": 260,
    },
    "rotation": {
        "mode": "rotation",
        "label": "动量轮动 (6月/持2只)",
        "desc": "每月初按 6 个月动量全仓最强 2 只, 负动量退现金; 样本外验证跑赢买持",
        "lookback": 6,
        "top_k": 2,
        "symbols": ["AAPL", "GOOGL", "TSLA", "NIO", "IONQ", "PLTR", "IREN", "QQQ", "SPY"],
        "min_bars": 6 * TRADING_DAYS_PER_MONTH + 10,
    },
}

COMMON = {"initial_cash": 100_000.0, "commission": 0.0005, "slippage": 0.0005,
          "band": 0.005, "history_days": 600}


def _state_file(account: str) -> Path:
    return STATE_DIR / f"{account}.json"


def _load_state(account: str) -> dict | None:
    f = _state_file(account)
    return json.loads(f.read_text()) if f.exists() else None


def _save_state(account: str, state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _state_file(account).with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1))
    tmp.replace(_state_file(account))


def _history(symbol: str, cfg: dict) -> pd.DataFrame:
    start = (pd.Timestamp.now() - pd.Timedelta(days=cfg["history_days"])).strftime("%Y-%m-%d")
    df = data.load(symbol, start=start, allow_synthetic=False)
    if len(df) < cfg["min_bars"]:
        raise ValueError(f"{symbol}: 行情不足 ({len(df)} 根)")
    return df


def init_state(account: str) -> dict:
    if account not in ACCOUNTS:
        raise KeyError(f"未知账户 '{account}'; 可用: {list(ACCOUNTS)}")
    cfg = {**COMMON, **ACCOUNTS[account]}
    base_prices = {}
    for sym in cfg["symbols"]:
        try:
            base_prices[sym] = float(_history(sym, cfg)["close"].iloc[-1])
        except Exception:  # noqa: BLE001
            base_prices[sym] = None
    state = {
        "config": cfg,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "cash": cfg["initial_cash"],
        "positions": {},
        "pending": [],
        "trades": [],
        "equity_history": [],
        "base_prices": base_prices,
        "last_rebalance_month": None,   # rotation 用
        "last_run": None,
    }
    _save_state(account, state)
    return state


def _target_weights(state: dict, frames: dict[str, pd.DataFrame]) -> dict[str, float]:
    """按模式计算各标的目标权重 (占总净值)。"""
    cfg = state["config"]
    weights: dict[str, float] = {}

    if cfg["mode"] == "per_symbol":
        n = len(cfg["symbols"])
        for sym, df in frames.items():
            strat = get_strategy(cfg["strategy"], **cfg.get("params", {}))
            w = float(strat.generate_signals(df).iloc[-1])
            weights[sym] = w / n
        return weights

    # rotation: 每月初再平衡一次
    latest = max(df.index[-1] for df in frames.values())
    month = latest.strftime("%Y-%m")
    if state.get("last_rebalance_month") == month:
        return {}  # 本月已调仓, 不动
    lookback_bars = cfg["lookback"] * TRADING_DAYS_PER_MONTH
    momentum = {}
    for sym, df in frames.items():
        closes = df["close"]
        if len(closes) > lookback_bars:
            momentum[sym] = float(closes.iloc[-1] / closes.iloc[-1 - lookback_bars] - 1)
    ranked = sorted(momentum, key=momentum.get, reverse=True)
    picks = [s for s in ranked[: cfg["top_k"]] if momentum[s] > 0]
    for sym in frames:
        weights[sym] = (1.0 / cfg["top_k"]) if sym in picks else 0.0
    state["last_rebalance_month"] = month
    state["rebalance_note"] = {
        "month": month,
        "picks": picks or ["(全现金)"],
        "momentum_top5": {s: round(momentum[s], 3) for s in ranked[:5]},
    }
    return weights


def run_cycle(account: str) -> dict:
    """跑一轮: 成交到期挂单 -> 计算新目标 -> 挂单 -> 记净值。幂等。"""
    state = _load_state(account) or init_state(account)
    cfg = state["config"]
    fills, new_orders, errors = [], [], []

    frames: dict[str, pd.DataFrame] = {}
    for sym in cfg["symbols"]:
        try:
            frames[sym] = _history(sym, cfg)
        except Exception as exc:  # noqa: BLE001
            errors.append({"symbol": sym, "error": str(exc)})

    def equity_now() -> float:
        total = state["cash"]
        for sym, pos in state["positions"].items():
            px = float(frames[sym]["close"].iloc[-1]) if sym in frames else pos["avg_cost"]
            total += pos["shares"] * px
        return total

    # 1) 成交到期挂单 (信号 bar 之后的第一根 bar 开盘价)
    still_pending = []
    for order in state["pending"]:
        sym = order["symbol"]
        df = frames.get(sym)
        if df is None:
            still_pending.append(order)
            continue
        later = df[df.index > pd.Timestamp(order["signal_bar"])]
        if len(later) == 0:
            still_pending.append(order)
            continue
        price = float(later.iloc[0]["open"])
        fill_date = later.index[0].strftime("%Y-%m-%d")
        eq = equity_now()
        target_shares = order["target_weight"] * eq / price if price > 0 else 0.0
        current = state["positions"].get(sym, {"shares": 0.0, "avg_cost": 0.0})
        delta = target_shares - current["shares"]
        trade_value = abs(delta) * price
        if trade_value < cfg["band"] * eq:
            continue
        cost = trade_value * (cfg["commission"] + cfg["slippage"])
        state["cash"] -= delta * price + cost
        new_shares = current["shares"] + delta
        if delta > 0:
            avg = (current["avg_cost"] * current["shares"] + price * delta) / new_shares
        else:
            avg = current["avg_cost"]
        if new_shares > 1e-9:
            state["positions"][sym] = {"shares": round(new_shares, 4), "avg_cost": round(avg, 4)}
        else:
            state["positions"].pop(sym, None)
        fill = {"date": fill_date, "symbol": sym, "side": "BUY" if delta > 0 else "SELL",
                "shares": round(abs(delta), 4), "price": round(price, 4), "cost": round(cost, 4)}
        state["trades"].append(fill)
        fills.append(fill)
    state["pending"] = still_pending

    # 2) 计算目标权重并挂单
    try:
        targets = _target_weights(state, frames)
    except Exception as exc:  # noqa: BLE001
        targets = {}
        errors.append({"symbol": "*", "error": f"信号失败: {exc}"})
    eq = equity_now()
    for sym, w in targets.items():
        df = frames.get(sym)
        if df is None:
            continue
        signal_bar = df.index[-1].strftime("%Y-%m-%d")
        cur_value = state["positions"].get(sym, {}).get("shares", 0.0) * float(df["close"].iloc[-1])
        if abs(w * eq - cur_value) < cfg["band"] * eq:
            continue
        state["pending"] = [o for o in state["pending"] if o["symbol"] != sym]
        order = {"symbol": sym, "target_weight": round(w, 4), "signal_bar": signal_bar}
        state["pending"].append(order)
        new_orders.append(order)

    # 3) 记净值 (同日覆盖)
    if frames:
        latest_date = max(df.index[-1] for df in frames.values()).strftime("%Y-%m-%d")
        rets = [float(frames[s]["close"].iloc[-1]) / p
                for s, p in state["base_prices"].items() if p and s in frames]
        benchmark = cfg["initial_cash"] * (sum(rets) / len(rets)) if rets else None
        state["equity_history"] = [e for e in state["equity_history"] if e["date"] != latest_date]
        state["equity_history"].append(
            {"date": latest_date, "equity": round(equity_now(), 2),
             "benchmark": round(benchmark, 2) if benchmark else None})
        state["equity_history"].sort(key=lambda e: e["date"])

    state["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    _save_state(account, state)
    return {"account": account, "fills": fills, "new_orders": new_orders,
            "errors": errors, "equity": round(equity_now(), 2), "cash": round(state["cash"], 2)}


def run_all() -> list[dict]:
    return [run_cycle(a) for a in ACCOUNTS]


def snapshot(account: str) -> dict:
    state = _load_state(account) or init_state(account)
    cfg = state["config"]
    positions = []
    for sym, pos in state["positions"].items():
        last = None
        try:
            cache = data._cache_path(sym, "1d")
            if cache.exists():
                last = float(pd.read_csv(cache, index_col=0, parse_dates=True)["close"].iloc[-1])
        except Exception:  # noqa: BLE001
            pass
        mv = pos["shares"] * last if last else None
        positions.append({"symbol": sym, "shares": pos["shares"], "avg_cost": pos["avg_cost"],
                          "last": last, "market_value": round(mv, 2) if mv else None,
                          "pnl_pct": round(last / pos["avg_cost"] - 1, 4) if last and pos["avg_cost"] else None})
    eq = state["equity_history"][-1]["equity"] if state["equity_history"] else cfg["initial_cash"]
    return {
        "account": account,
        "label": cfg.get("label", account),
        "desc": cfg.get("desc", ""),
        "mode": cfg["mode"],
        "config": {k: cfg[k] for k in ("symbols", "initial_cash") if k in cfg},
        "created_at": state["created_at"],
        "last_run": state["last_run"],
        "cash": round(state["cash"], 2),
        "equity": eq,
        "total_return": round(eq / cfg["initial_cash"] - 1, 4),
        "rebalance_note": state.get("rebalance_note"),
        "positions": sorted(positions, key=lambda p: -(p["market_value"] or 0)),
        "pending": state["pending"],
        "trades": state["trades"][-100:],
        "equity_history": state["equity_history"],
    }


def snapshots() -> list[dict]:
    return [snapshot(a) for a in ACCOUNTS]
