#!/usr/bin/env python3
"""每日自动扫描 —— 对 watchlist 跑 Stock Agent, 生成榜单报告。

用法:
    python scan.py                          # 扫 config.yaml 里的 symbols
    python scan.py --symbols AAPL MSFT ...  # 临时指定
    python scan.py --out reports/           # 报告输出目录 (默认 reports/)

输出:
    - 控制台榜单
    - reports/scan_YYYY-MM-DD.md  (Markdown 报告, 可发邮件/IM)

定时运行 (服务器 crontab, 美东收盘后):
    30 16 * * 1-5  cd /opt/FinanceAgent && /usr/bin/python3 scan.py >> /var/log/financeagent-scan.log 2>&1
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import yaml

from quant.agent.analyst import rank, rank_table


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="FinanceAgent 每日扫描")
    ap.add_argument("--symbols", nargs="+", help="标的列表 (默认读 config.yaml)")
    ap.add_argument("-c", "--config", default="config.yaml")
    ap.add_argument("--out", default="reports", help="报告输出目录")
    ap.add_argument("--no-fundamentals", action="store_true", help="跳过基本面 (更快)")
    return ap.parse_args()


def build_markdown(verdicts, generated_at: str) -> str:
    lines = [
        f"# FinanceAgent 每日扫描报告",
        f"",
        f"生成时间: {generated_at}  |  标的数: {len(verdicts)}",
        f"",
        "## 榜单 (按综合得分)",
        "",
        "| 排名 | 标的 | 评级 | 得分 | RSI | 3月动量 | 距52周高 |",
        "|---|---|---|---|---|---|---|",
    ]
    for i, v in enumerate(verdicts, 1):
        rsi = v.technicals.get("rsi14")
        mom = v.technicals.get("momentum_3m")
        dd = v.snapshot.get("pct_below_52w_high")
        lines.append(
            f"| {i} | **{v.symbol}** | {v.rating} | {v.score:+.0f} "
            f"| {'' if rsi is None else f'{rsi:.0f}'} "
            f"| {'' if mom is None else f'{mom:+.1%}'} "
            f"| {'' if dd is None else f'{dd:+.1%}'} |"
        )
    lines.append("")
    lines.append("## 逐标的详情")
    for v in verdicts:
        lines += [f"", f"### {v.symbol} — {v.rating} ({v.score:+.0f})", ""]
        for r in v.reasons:
            lines.append(f"- ✅ {r}")
        for r in v.risks:
            lines.append(f"- ⚠️ {r}")
    lines += ["", "---", "*本报告由 FinanceAgent 自动生成, 仅供研究, 不构成投资建议。*"]
    return "\n".join(lines)


def main() -> None:
    args = parse_args()

    symbols = args.symbols
    if not symbols:
        cfg_path = Path(args.config)
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
        symbols = (cfg or {}).get("symbols", ["AAPL", "MSFT", "NVDA", "SPY"])

    now = datetime.now()
    print(f"[scan] {now:%Y-%m-%d %H:%M} 扫描 {len(symbols)} 个标的: {symbols}")
    verdicts = rank(symbols, with_fundamentals=not args.no_fundamentals)

    print()
    print(rank_table(verdicts))

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / f"scan_{now:%Y-%m-%d}.md"
    report_path.write_text(build_markdown(verdicts, f"{now:%Y-%m-%d %H:%M}"), encoding="utf-8")
    print(f"\n[scan] 报告已生成: {report_path}")


if __name__ == "__main__":
    main()
