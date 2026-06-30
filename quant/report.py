"""回测报告: 控制台文本 + 图表 (净值曲线 / 回撤)。"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # 无显示环境也能出图
import matplotlib.pyplot as plt  # noqa: E402

from .backtest import BacktestResult
from .metrics import drawdown_series

REPORT_DIR = Path("reports")
REPORT_DIR.mkdir(parents=True, exist_ok=True)


def print_report(result: BacktestResult) -> None:
    print("=" * 60)
    print(result.summary())
    print("=" * 60)


def build_figure(result: BacktestResult):
    """构建净值对比 + 回撤的 matplotlib Figure (供保存或内嵌)。"""
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(11, 7), sharex=True, gridspec_kw={"height_ratios": [3, 1]}
    )

    # 图内统一用英文标签, 避免不同环境缺中文字体导致乱码/方块
    ax1.plot(result.equity.index, result.equity, label=f"Strategy: {result.strategy}", lw=1.6)
    ax1.plot(result.benchmark.index, result.benchmark, label="Buy & Hold", lw=1.2, alpha=0.7)
    ax1.set_title(f"{result.symbol} - {result.strategy} backtest")
    ax1.set_ylabel("Equity (normalized)")
    ax1.legend(loc="upper left")
    ax1.grid(alpha=0.3)

    dd = drawdown_series(result.equity)
    ax2.fill_between(dd.index, dd.values, 0, color="crimson", alpha=0.4)
    ax2.set_ylabel("Drawdown")
    ax2.grid(alpha=0.3)

    fig.tight_layout()
    return fig


def plot_report(result: BacktestResult, save: bool = True, show: bool = False) -> Path | None:
    """绘制净值对比 + 回撤, 保存到 reports/ 并返回路径。"""
    fig = build_figure(result)
    path = None
    if save:
        path = REPORT_DIR / f"{result.symbol}_{result.strategy}.png"
        fig.savefig(path, dpi=120)
    if show:
        plt.show()
    plt.close(fig)
    return path


def fig_to_base64(result: BacktestResult) -> str:
    """把回测图渲染为 base64 PNG 字符串, 用于内嵌 HTML。"""
    import base64
    import io

    fig = build_figure(result)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def compare_table(results: list[BacktestResult]) -> str:
    """多策略 / 多标的横向对比表。"""
    header = f"{'标的':<10}{'策略':<16}{'年化':>9}{'夏普':>8}{'最大回撤':>10}{'胜率':>8}"
    lines = [header, "-" * len(header)]
    for r in results:
        m = r.metrics
        lines.append(
            f"{r.symbol:<10}{r.strategy:<16}{m.cagr:>8.1%}{m.sharpe:>8.2f}"
            f"{m.max_drawdown:>10.1%}{m.win_rate:>8.1%}"
        )
    return "\n".join(lines)
