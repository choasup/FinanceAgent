"""模拟盘 (Paper Trading) 引擎。

用真实行情、假资金, 按与回测引擎相同的纪律模拟执行:
  - 每个交易日收盘后计算目标仓位 (信号基于 <= 当日 的数据)
  - 挂单在 **下一根日线的开盘价** 成交 (T+1, 无未来函数)
  - 含手续费与滑点, 调仓带宽内的微小偏差不交易

状态持久化在 ``data/paper/state.json``, 每次 run_cycle() 由定时任务触发。
仅供研究, 不构成投资建议; 本引擎不连接任何真实券商账户。
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
STATE_FILE = STATE_DIR / "state.json"

DEFAULT_CONFIG = {
    "strategy": "trend_vol",
    "params": {},
    # DRAM 上市不足一年, 撑不起 200 日均线策略, 暂不纳入
    "symbols": ["AAPL", "GOOGL", "TSLA", "NIO", "IONQ", "PLTR", "IREN"],
    "initial_cash": 100_000.0,
    "commission": 0.0005,
    "slippage": 0.0005,
    "band": 0.01,          # 占单票配额的调仓带宽
    "history_days": 600,   # 信号计算回看的行情长度
}


def _load_state() -> dict | None:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return None


def _save_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1))
    tmp.replace(STATE_FILE)


def init_state(config: dict | None = None) -> dict:
    """初始化 (或重置) 模拟盘。记录基准起点价格用于对比等权买入持有。"""
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    base_prices = {}
    for sym in cfg["symbols"]:
        try:
            df = _history(sym, cfg)
            base_prices[sym] = float(df["close"].iloc[-1])
        except Exception:  # noqa: BLE001
            base_prices[sym] = None
    state = {
        "config": cfg,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "cash": cfg["initial_cash"],
        "positions": {},          # symbol -> {shares, avg_cost}
        "pending": [],            # {symbol, target_weight, signal_bar}
        "trades": [],             # {date, symbol, side, shares, price, cost}
        "equity_history": [],     # {date, equity, benchmark}
        "base_prices": base_prices,
        "last_run": None,
    }
    _save_state(state)
    return state


def _history(symbol: str, cfg: dict) -> pd.DataFrame:
    start = (pd.Timestamp.now() - pd.Timedelta(days=cfg["history_days"])).strftime("%Y-%m-%d")
    df = data.load(symbol, start=start, allow_synthetic=False)
    if len(df) < 260:
        raise ValueError(f"{symbol}: 行情不足 ({len(df)} 根), 无法产生可靠信号")
    return df


def run_cycle() -> dict:
    """跑一轮: 成交到期挂单 -> 计算新信号 -> 挂单 -> 记净值。幂等: 同一根 bar 重复跑无副作用。"""
    state = _load_state()
    if state is None:
        state = init_state()
    cfg = state["config"]
    n = len(cfg["symbols"])
    fills, new_orders, errors = [], [], []

    frames: dict[str, pd.DataFrame] = {}
    for sym in cfg["symbols"]:
        try:
            frames[sym] = _history(sym, cfg)
        except Exception as exc:  # noqa: BLE001
            errors.append({"symbol": sym, "error": str(exc)})

    # 当前净值 (用最新收盘 mark-to-market)
    def equity_now() -> float:
        total = state["cash"]
        for sym, pos in state["positions"].items():
            if sym in frames:
                total += pos["shares"] * float(frames[sym]["close"].iloc[-1])
            else:
                total += pos["shares"] * pos["avg_cost"]  # 无行情时按成本估
        return total

    # 1) 成交到期挂单: 找信号 bar 之后的第一根 bar, 按其开盘价成交
    still_pending = []
    for order in state["pending"]:
        sym = order["symbol"]
        df = frames.get(sym)
        if df is None:
            still_pending.append(order)
            continue
        later = df[df.index > pd.Timestamp(order["signal_bar"])]
        if len(later) == 0:
            still_pending.append(order)  # 新 bar 还没来
            continue
        fill_bar = later.iloc[0]
        fill_date = later.index[0].strftime("%Y-%m-%d")
        price = float(fill_bar["open"])
        slot = equity_now() / n
        target_shares = order["target_weight"] * slot / price if price > 0 else 0.0
        current = state["positions"].get(sym, {"shares": 0.0, "avg_cost": 0.0})
        delta = target_shares - current["shares"]
        trade_value = abs(delta) * price
        if trade_value < cfg["band"] * slot:
            continue  # 带宽内, 放弃这单
        cost = trade_value * (cfg["commission"] + cfg["slippage"])
        state["cash"] -= delta * price + cost
        new_shares = current["shares"] + delta
        if delta > 0:
            total_cost = current["avg_cost"] * current["shares"] + price * delta
            avg = total_cost / new_shares if new_shares > 0 else 0.0
        else:
            avg = current["avg_cost"]
        if new_shares > 1e-9:
            state["positions"][sym] = {"shares": round(new_shares, 4), "avg_cost": round(avg, 4)}
        else:
            state["positions"].pop(sym, None)
        fill = {
            "date": fill_date,
            "symbol": sym,
            "side": "BUY" if delta > 0 else "SELL",
            "shares": round(abs(delta), 4),
            "price": round(price, 4),
            "cost": round(cost, 4),
        }
        state["trades"].append(fill)
        fills.append(fill)
    state["pending"] = still_pending

    # 2) 计算新信号并挂单 (目标仓位与当前仓位差超带宽才挂)
    eq = equity_now()
    for sym, df in frames.items():
        try:
            strat = get_strategy(cfg["strategy"], **cfg["params"])
            w = float(strat.generate_signals(df).iloc[-1])
        except Exception as exc:  # noqa: BLE001
            errors.append({"symbol": sym, "error": f"信号失败: {exc}"})
            continue
        signal_bar = df.index[-1].strftime("%Y-%m-%d")
        slot = eq / n
        cur_shares = state["positions"].get(sym, {}).get("shares", 0.0)
        cur_value = cur_shares * float(df["close"].iloc[-1])
        target_value = w * slot
        if abs(target_value - cur_value) < cfg["band"] * slot:
            continue
        # 同一标的只保留最新挂单
        state["pending"] = [o for o in state["pending"] if o["symbol"] != sym]
        order = {"symbol": sym, "target_weight": round(w, 4), "signal_bar": signal_bar}
        state["pending"].append(order)
        new_orders.append(order)

    # 3) 记录净值曲线 (以最新收盘为准, 同日覆盖)
    latest_date = max(
        (df.index[-1].strftime("%Y-%m-%d") for df in frames.values()), default=None
    )
    if latest_date:
        bench_rets = [
            float(frames[s]["close"].iloc[-1]) / p
            for s, p in state["base_prices"].items()
            if p and s in frames
        ]
        benchmark = cfg["initial_cash"] * (sum(bench_rets) / len(bench_rets)) if bench_rets else None
        state["equity_history"] = [e for e in state["equity_history"] if e["date"] != latest_date]
        state["equity_history"].append(
            {"date": latest_date, "equity": round(equity_now(), 2),
             "benchmark": round(benchmark, 2) if benchmark else None}
        )
        state["equity_history"].sort(key=lambda e: e["date"])

    state["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    _save_state(state)
    return {"fills": fills, "new_orders": new_orders, "errors": errors,
            "equity": round(equity_now(), 2), "cash": round(state["cash"], 2)}


def snapshot() -> dict:
    """面板展示用的当前状态。"""
    state = _load_state()
    if state is None:
        state = init_state()
    cfg = state["config"]
    positions = []
    for sym, pos in state["positions"].items():
        last = None
        try:
            cache = data._cache_path(sym, "1d")
            if cache.exists():
                df = pd.read_csv(cache, index_col=0, parse_dates=True)
                last = float(df["close"].iloc[-1])
        except Exception:  # noqa: BLE001
            pass
        mv = pos["shares"] * last if last else None
        positions.append(
            {
                "symbol": sym,
                "shares": pos["shares"],
                "avg_cost": pos["avg_cost"],
                "last": last,
                "market_value": round(mv, 2) if mv else None,
                "pnl_pct": round((last / pos["avg_cost"] - 1), 4) if last and pos["avg_cost"] else None,
            }
        )
    eq = state["equity_history"][-1]["equity"] if state["equity_history"] else cfg["initial_cash"]
    return {
        "config": cfg,
        "created_at": state["created_at"],
        "last_run": state["last_run"],
        "cash": round(state["cash"], 2),
        "equity": eq,
        "total_return": round(eq / cfg["initial_cash"] - 1, 4),
        "positions": sorted(positions, key=lambda p: -(p["market_value"] or 0)),
        "pending": state["pending"],
        "trades": state["trades"][-100:],
        "equity_history": state["equity_history"],
    }
