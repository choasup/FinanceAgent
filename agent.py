#!/usr/bin/env python3
"""FinanceAgent —— Stock Agent 入口。

不只是回测: 给它股票代码, 它自动拉数据 -> 算技术面 -> 跑回测验证信号
-> 查基本面 -> 输出带评级的分析结论。

用法:
    python agent.py AAPL                    # 单只股票多因子分析 (离线可用)
    python agent.py AAPL MSFT NVDA SPY      # 多只分析 + 排序榜单
    python agent.py AAPL --json             # 输出结构化 JSON
    python agent.py AAPL --llm              # Claude 深度研究报告 (需 ANTHROPIC_API_KEY)
    python agent.py AAPL --llm -q "现在适合建仓吗?"   # 带自定义问题
"""

from __future__ import annotations

import argparse
import dataclasses
import json


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="FinanceAgent Stock Agent")
    ap.add_argument("symbols", nargs="+", help="股票代码, 如 AAPL MSFT")
    ap.add_argument("--llm", action="store_true", help="用 Claude 做深度研究 (需 API key)")
    ap.add_argument("-q", "--question", help="向 LLM Agent 提出的自定义问题")
    ap.add_argument("--json", action="store_true", help="输出结构化 JSON (仅规则引擎模式)")
    ap.add_argument("--no-fundamentals", action="store_true", help="跳过基本面 (更快/纯离线)")
    return ap.parse_args()


def main() -> None:
    args = parse_args()

    if args.llm:
        from quant.agent.llm import research

        for symbol in args.symbols:
            print(f"\n{'=' * 62}\n{symbol} — Claude 深度研究\n{'=' * 62}")
            try:
                print(research(symbol, question=args.question))
            except Exception as exc:  # noqa: BLE001
                print(f"[agent] LLM 分析失败: {exc}")
                print("提示: 需要 pip install anthropic 并设置 ANTHROPIC_API_KEY。"
                      "也可以先用规则引擎模式 (去掉 --llm)。")
        return

    from quant.agent.analyst import analyze, rank, rank_table

    with_fund = not args.no_fundamentals

    if len(args.symbols) == 1:
        verdict = analyze(args.symbols[0], with_fundamentals=with_fund)
        if args.json:
            print(json.dumps(dataclasses.asdict(verdict), ensure_ascii=False, indent=2))
        else:
            print(verdict.pretty())
        return

    verdicts = rank(args.symbols, with_fundamentals=with_fund)
    if args.json:
        print(json.dumps([dataclasses.asdict(v) for v in verdicts], ensure_ascii=False, indent=2))
        return
    for v in verdicts:
        print(v.pretty())
        print()
    print("=" * 62)
    print("多标的排序 (按综合得分)")
    print("=" * 62)
    print(rank_table(verdicts))


if __name__ == "__main__":
    main()
