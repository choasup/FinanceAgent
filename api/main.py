"""FinanceAgent REST API (FastAPI)。

为 Next.js 前端提供数据接口, 复用 quant/ 回测引擎与 Agent 分析:

    GET  /api/health          存活检查
    GET  /api/strategies      策略列表 (含参数 schema 与中文说明)
    POST /api/backtest        运行回测, 返回 K线/买卖点/净值/回撤/指标
    POST /api/agent/rank      多标的技术面评级排序

本地运行:
    uvicorn api.main:app --reload --port 8000
"""

from __future__ import annotations

import inspect
import json
import math
import os
from dataclasses import asdict
from pathlib import Path

import pandas as pd
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from quant import data
from quant.backtest import BacktestEngine
from quant.metrics import drawdown_series
from quant.strategy import get_strategy, list_strategies

import strategies  # noqa: F401 -> 注册内置策略

app = FastAPI(title="FinanceAgent API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 同源部署时不生效; 便于本地 next dev 联调
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- 策略元信息 (与旧 Streamlit 版一致的中文文案) ------------------------------

STRAT_DESC = {
    "trend_vol": "趋势跟踪+波动率控仓: 牛市跟涨、熊市空仓躲大跌 (推荐)",
    "sma_cross": "双均线交叉: 快线上穿慢线买入, 下穿卖出, 经典入门",
    "macd_trend": "MACD 趋势: 信号频繁, 手续费磨损大, 仅供对比",
    "momentum": "动量: 近期涨得多就持有, 带长期均线过滤",
    "rsi_reversion": "RSI 超卖反弹: 跌过头买入, 回到中位卖出",
}

PARAM_LABELS = {
    "fast": ("快线周期(日)", "短周期均线天数, 越小越灵敏"),
    "slow": ("慢线周期(日)", "长周期均线天数"),
    "signal": ("信号线周期(日)", "MACD 信号平滑天数"),
    "window": ("计算窗口(日)", "指标回看的天数"),
    "oversold": ("超卖阈值", "RSI 低于该值视为跌过头"),
    "exit_level": ("离场阈值", "RSI 回到该值以上卖出"),
    "lookback": ("动量回看(日)", "比较多少天前的价格"),
    "trend_filter": ("趋势过滤均线(日)", "价格在该均线上方才允许持仓"),
    "trend_window": ("趋势均线(日)", "收盘价站上该均线才持仓, 跌破清仓"),
    "confirm_window": ("确认均线(日)", "该均线也需在趋势均线上方, 过滤假突破"),
    "vol_window": ("波动率窗口(日)", "用最近多少天估算波动"),
    "target_vol": ("目标年化波动", "市场越疯狂仓位越轻, 波动钉在此水平"),
    "step": ("仓位档位", "仓位按该步长量化, 减少碎单"),
    "rebalance_every": ("调仓间隔(日)", "持仓中最多隔多少天微调一次仓位"),
}


def _clean(v):
    """JSON 不接受 NaN/inf, 统一转 None。"""
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/strategies")
def strategies_meta():
    out = []
    for name in list_strategies():
        cls = get_strategy(name).__class__
        sig = inspect.signature(cls.__init__)
        params = []
        for pname, p in sig.parameters.items():
            if pname == "self" or p.default is inspect.Parameter.empty:
                continue
            label, help_ = PARAM_LABELS.get(pname, (pname, ""))
            params.append(
                {
                    "name": pname,
                    "label": label,
                    "help": help_,
                    "type": "float" if isinstance(p.default, float) else "int",
                    "default": p.default,
                }
            )
        out.append({"name": name, "desc": STRAT_DESC.get(name, ""), "params": params})
    return out


class BacktestReq(BaseModel):
    symbols: list[str] = Field(min_length=1, max_length=10)
    strategy: str = "trend_vol"
    params: dict = {}
    start: str = "2019-01-01"
    end: str | None = None
    initial_cash: float = 100_000
    commission: float = 0.0005
    slippage: float = 0.0005


def _series_points(s: pd.Series) -> list[dict]:
    return [
        {"time": t.strftime("%Y-%m-%d"), "value": _clean(round(float(v), 6))}
        for t, v in s.items()
    ]


@app.post("/api/backtest")
def backtest(req: BacktestReq):
    engine = BacktestEngine(
        initial_cash=req.initial_cash,
        commission=req.commission,
        slippage=req.slippage,
    )
    results, errors = [], []
    for symbol in [s.strip().upper() for s in req.symbols if s.strip()]:
        try:
            df = data.load(symbol, start=req.start, end=req.end or None)
            strat = get_strategy(req.strategy, **req.params)
            r = engine.run(df, strat, symbol=symbol)

            candles = [
                {
                    "time": t.strftime("%Y-%m-%d"),
                    "open": round(float(o), 4),
                    "high": round(float(h), 4),
                    "low": round(float(l), 4),
                    "close": round(float(c), 4),
                }
                for t, o, h, l, c in zip(
                    df.index, df["open"], df["high"], df["low"], df["close"]
                )
            ]
            trades = [
                {
                    "date": pd.Timestamp(t["date"]).strftime("%Y-%m-%d"),
                    "side": t["side"],
                    "shares": round(float(t["shares"]), 2),
                    "price": round(float(t["price"]), 4),
                    "cost": round(float(t["cost"]), 4),
                }
                for t in r.trades.to_dict("records")
            ]
            metrics = {k: _clean(v) for k, v in asdict(r.metrics).items()}
            bench = {k: _clean(v) for k, v in asdict(r.benchmark_metrics).items()}
            results.append(
                {
                    "symbol": symbol,
                    "strategy": r.strategy,
                    "metrics": metrics,
                    "benchmark_metrics": bench,
                    "candles": candles,
                    "equity": _series_points(r.equity),
                    "benchmark": _series_points(r.benchmark),
                    "drawdown": _series_points(drawdown_series(r.equity)),
                    "trades": trades,
                }
            )
        except Exception as exc:  # noqa: BLE001
            errors.append({"symbol": symbol, "message": str(exc)})
    return {"results": results, "errors": errors}


# ---- 自选股面板 ---------------------------------------------------------------

WATCHLIST_PATH = Path(os.environ.get("QUANT_DATA_DIR", "data")) / "watchlist.json"


def _load_watchlist() -> list[dict]:
    if WATCHLIST_PATH.exists():
        try:
            return json.loads(WATCHLIST_PATH.read_text())
        except Exception:  # noqa: BLE001
            return []
    return []


@app.get("/api/watchlist")
def get_watchlist():
    return {"items": _load_watchlist()}


class WatchlistReq(BaseModel):
    items: list[dict] = Field(max_length=200)


@app.put("/api/watchlist")
def put_watchlist(req: WatchlistReq):
    items = [
        {"symbol": str(i.get("symbol", "")).strip().upper(), "name": str(i.get("name", ""))}
        for i in req.items
        if str(i.get("symbol", "")).strip()
    ]
    WATCHLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    WATCHLIST_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=1))
    return {"items": items}


class RefreshReq(BaseModel):
    symbols: list[str] | None = None  # 不传 = 刷新整个自选


@app.post("/api/watch/refresh")
def watch_refresh(req: RefreshReq):
    """联网刷新自选行情缓存 (yfinance/akshare 按 QUANT_DATA_SOURCES 顺序)。"""
    targets = [s.strip().upper() for s in (req.symbols or [i["symbol"] for i in _load_watchlist()]) if s.strip()]
    start = (pd.Timestamp.now() - pd.Timedelta(days=430)).strftime("%Y-%m-%d")
    ok, fail = [], []
    for sym in targets:
        try:
            df = data.load(sym, start=start, refresh=True, allow_synthetic=False)
            if len(df) < 10:
                raise ValueError("数据太短")
            ok.append(sym)
        except Exception as exc:  # noqa: BLE001
            fail.append({"symbol": sym, "error": str(exc)})
    return {"ok": ok, "fail": fail}


@app.get("/api/watch/summary")
def watch_summary():
    """自选股面板数据: 只读本地行情缓存, 绝不联网、绝不用合成数据。"""
    from quant.indicators import rsi as rsi_ind

    out = []
    for item in _load_watchlist():
        sym, name = item["symbol"], item.get("name", "")
        base = {"symbol": sym, "name": name}
        try:
            cache = data._cache_path(sym, "1d")
            if not cache.exists():
                raise FileNotFoundError("无本地行情数据 (待预取)")
            df = pd.read_csv(cache, index_col=0, parse_dates=True).dropna()
            if len(df) < 30:
                raise ValueError("行情数据太短")
            closes = df["close"]
            last, prev = float(closes.iloc[-1]), float(closes.iloc[-2])

            def ret(n: int) -> float | None:
                return _clean(last / float(closes.iloc[-n - 1]) - 1) if len(closes) > n else None

            sma200 = closes.rolling(200).mean().iloc[-1] if len(closes) >= 200 else None
            hi52 = float(closes.tail(252).max())
            spark = [round(float(v), 4) for v in closes.tail(60)]
            out.append(
                {
                    **base,
                    "ok": True,
                    "as_of": closes.index[-1].strftime("%Y-%m-%d"),
                    "price": round(last, 3),
                    "chg_1d": _clean(last / prev - 1),
                    "ret_1w": ret(5),
                    "ret_1m": ret(21),
                    "ret_3m": ret(63),
                    "rsi14": _clean(round(float(rsi_ind(closes, 14).iloc[-1]), 1)),
                    "above_sma200": bool(last > float(sma200)) if sma200 is not None and not math.isnan(sma200) else None,
                    "pct_below_52w_high": _clean(last / hi52 - 1),
                    "spark": spark,
                }
            )
        except Exception as exc:  # noqa: BLE001
            out.append({**base, "ok": False, "error": str(exc)})
    return {"items": out}


# ---- 模拟盘 (Paper Trading) -----------------------------------------------------


@app.get("/api/paper")
def paper_state():
    from quant import paper

    return paper.snapshot()


@app.post("/api/paper/run")
def paper_run():
    """跑一轮模拟盘 (成交挂单 + 产生新信号)。由每日定时任务在行情刷新后调用。"""
    from quant import paper

    return paper.run_cycle()


class PaperResetReq(BaseModel):
    strategy: str | None = None
    symbols: list[str] | None = None
    initial_cash: float | None = None


@app.post("/api/paper/reset")
def paper_reset(req: PaperResetReq):
    from quant import paper

    cfg = {k: v for k, v in req.model_dump().items() if v is not None}
    paper.init_state(cfg)
    return paper.snapshot()


# ---- 个股深度分析: 全策略适配对比 -----------------------------------------------


class AnalyzeReq(BaseModel):
    symbol: str
    start: str = "2019-01-01"
    end: str | None = None


@app.post("/api/stock/analyze")
def stock_analyze(req: AnalyzeReq):
    """对单只股票跑全部策略, 返回适配对比表和历史最优策略。

    回答的问题: "这只票历史上什么打法有效, 还是躺平最好?"
    """
    symbol = req.symbol.strip().upper()
    df = data.load(symbol, start=req.start, end=req.end or None, allow_synthetic=False)
    engine = BacktestEngine()

    rows = []
    benchmark = None
    for name in list_strategies():
        try:
            r = engine.run(df, get_strategy(name), symbol=symbol)
            m = r.metrics
            rows.append(
                {
                    "strategy": name,
                    "desc": STRAT_DESC.get(name, ""),
                    "cagr": _clean(m.cagr),
                    "max_drawdown": _clean(m.max_drawdown),
                    "sharpe": _clean(m.sharpe),
                    "calmar": _clean(m.calmar),
                    "trades": len(r.trades),
                }
            )
            if benchmark is None:
                b = r.benchmark_metrics
                benchmark = {
                    "strategy": "buy_hold",
                    "desc": "买入后一直拿着不动 (基准)",
                    "cagr": _clean(b.cagr),
                    "max_drawdown": _clean(b.max_drawdown),
                    "sharpe": _clean(b.sharpe),
                    "calmar": _clean(b.calmar),
                    "trades": 1,
                }
        except Exception:  # noqa: BLE001
            continue

    # 历史最优: 先看卡玛 (每单位回撤换多少收益), 全负时退回夏普
    scored = [r for r in rows if r["calmar"] is not None]
    best = max(scored, key=lambda r: r["calmar"])["strategy"] if scored else "trend_vol"
    all_rows = ([benchmark] if benchmark else []) + rows
    return {"symbol": symbol, "rows": all_rows, "best": best}


class RankReq(BaseModel):
    symbols: list[str] = Field(min_length=1, max_length=20)
    with_fundamentals: bool = False


@app.post("/api/agent/rank")
def agent_rank(req: RankReq):
    from quant.agent.analyst import rank

    syms = [s.strip().upper() for s in req.symbols if s.strip()]
    verdicts = rank(syms, with_fundamentals=req.with_fundamentals)
    out = []
    for v in verdicts:
        d = asdict(v)
        for section in ("snapshot", "technicals", "backtest", "fundamentals"):
            d[section] = {k: _clean(val) for k, val in (d.get(section) or {}).items()}
        d["score"] = _clean(d["score"])
        out.append(d)
    return {"verdicts": out}
