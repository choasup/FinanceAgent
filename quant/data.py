"""行情数据获取与本地缓存.

默认数据源为 yfinance (美股 / 全球股票)。当网络不可用或抓取失败时,
自动回退到可复现的合成数据 (geometric brownian motion), 保证回测流程
在任何环境下都能跑通。

缓存以 parquet/csv 落盘到 ``data/`` 目录, 重复回测无需反复联网。
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

CACHE_DIR = Path(os.environ.get("QUANT_DATA_DIR", "data"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 标准列名: 全部小写, OHLCV
COLUMNS = ["open", "high", "low", "close", "volume"]


def _cache_path(symbol: str, period: str) -> Path:
    safe = symbol.replace("/", "_").replace(".", "_")
    return CACHE_DIR / f"{safe}_{period}.csv"


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """统一为小写 OHLCV 列, DatetimeIndex, 升序。"""
    df = df.copy()
    # yfinance 有时返回 MultiIndex 列 (单标的下载时)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.columns = [str(c).lower().replace(" ", "_") for c in df.columns]
    rename = {"adj_close": "adj_close"}
    df = df.rename(columns=rename)
    keep = [c for c in COLUMNS if c in df.columns]
    df = df[keep]
    df.index = pd.to_datetime(df.index)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df.dropna()


def _synthetic(
    symbol: str,
    start: str,
    end: str,
    period: str = "1d",
    seed: int | None = None,
) -> pd.DataFrame:
    """生成可复现的合成 OHLCV 数据, 作为离线回退。"""
    if seed is None:
        # 用 symbol 派生稳定种子, 同一标的每次结果一致
        seed = abs(hash(symbol)) % (2**32)
    rng = np.random.default_rng(seed)

    idx = pd.bdate_range(start=start, end=end)
    n = len(idx)
    if n == 0:
        idx = pd.bdate_range(start=start, periods=252)
        n = len(idx)

    mu, sigma = 0.0004, 0.018  # 日漂移 / 波动
    rets = rng.normal(mu, sigma, n)
    close = 100 * np.exp(np.cumsum(rets))
    open_ = close * (1 + rng.normal(0, 0.003, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.004, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.004, n)))
    volume = rng.integers(1_000_000, 5_000_000, n)

    df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )
    df.index.name = "date"
    return df


def _fetch_stooq(symbol: str, start: str, end: str) -> pd.DataFrame:
    """备用免费数据源 stooq.com (日线, 无需 key, 基本不限流)。

    美股代码需加 ``.us`` 后缀; 已带交易所后缀的代码 (如 ``0700.HK``) 原样尝试。
    """
    sym = symbol.lower()
    candidates = [f"{sym}.us"] if "." not in sym else [sym]
    d1 = start.replace("-", "")
    d2 = end.replace("-", "")
    for s in candidates:
        url = f"https://stooq.com/q/d/l/?s={s}&d1={d1}&d2={d2}&i=d"
        try:
            raw = pd.read_csv(url, index_col=0, parse_dates=True)
            if len(raw) > 0 and "Close" in raw.columns:
                print(f"[data] {symbol}: 使用 stooq 数据源。")
                return _normalize(raw)
        except Exception as exc:  # noqa: BLE001
            print(f"[data] stooq 抓取 {s} 失败 ({exc})。")
    return pd.DataFrame()


def load(
    symbol: str,
    start: str = "2018-01-01",
    end: str | None = None,
    period: str = "1d",
    use_cache: bool = True,
    allow_synthetic: bool = True,
) -> pd.DataFrame:
    """加载单个标的的历史 OHLCV 数据。

    Args:
        symbol: 标的代码, 如 "AAPL"、"MSFT"、"SPY"。
        start/end: 起止日期 (YYYY-MM-DD)。end 默认今天。
        period: K 线周期, 目前缓存键用, 默认日线 "1d"。
        use_cache: 是否使用/写入本地缓存。
        allow_synthetic: 抓取失败时是否回退到合成数据。

    Returns:
        DataFrame, 列为 open/high/low/close/volume, DatetimeIndex。
    """
    end = end or datetime.now().strftime("%Y-%m-%d")
    cache = _cache_path(symbol, period)

    if use_cache and cache.exists():
        cached = pd.read_csv(cache, index_col=0, parse_dates=True)
        # 缓存必须覆盖请求区间才可用, 否则会拿部分数据冒充全量 (留 30 天容差)
        tol = pd.Timedelta(days=30)
        covers = (
            len(cached) > 10
            and cached.index.min() <= pd.Timestamp(start) + tol
            and cached.index.max() >= pd.Timestamp(end) - tol
        )
        if covers:
            df = cached.loc[
                (cached.index >= pd.Timestamp(start)) & (cached.index <= pd.Timestamp(end))
            ]
            if len(df) > 10:
                return df

    df = pd.DataFrame()
    try:
        import yfinance as yf

        raw = yf.download(
            symbol,
            start=start,
            end=end,
            interval=period,
            auto_adjust=True,
            progress=False,
        )
        if raw is not None and len(raw) > 0:
            df = _normalize(raw)
    except Exception as exc:  # noqa: BLE001 - 网络/解析错误统一回退
        print(f"[data] yfinance 抓取 {symbol} 失败 ({exc}); 尝试回退。")

    if len(df) < 10 and period == "1d":
        df = _fetch_stooq(symbol, start, end)

    if len(df) >= 10:
        # 只有真实行情才写缓存; 合成数据入缓存会永久污染后续回测
        if use_cache:
            df.to_csv(cache)
        return df

    if not allow_synthetic:
        raise RuntimeError(f"无法获取 {symbol} 的行情数据, 且未允许合成回退。")
    print(f"[data] {symbol}: 使用合成数据 (离线回退, 不入缓存)。")
    return _synthetic(symbol, start, end, period)


def load_many(
    symbols: list[str],
    start: str = "2018-01-01",
    end: str | None = None,
    period: str = "1d",
    **kwargs,
) -> dict[str, pd.DataFrame]:
    """批量加载多个标的, 返回 {symbol: DataFrame}。"""
    return {s: load(s, start=start, end=end, period=period, **kwargs) for s in symbols}
