#!/usr/bin/env python3
"""FinanceAgent —— 股票量化回测 "一步到位" 入口。

最常用:
    python main.py                          # 按 config.yaml 跑
    python main.py --symbols AAPL MSFT      # 临时指定标的
    python main.py --strategy momentum      # 临时换策略
    python main.py --list-strategies        # 看有哪些策略
    python main.py --ml --symbols AAPL      # 训练 ML 模型并按其信号回测

整条链路: 配置 -> (基本面选股) -> 拉数据 -> 逐 bar 回测 -> 绩效 -> 报告/图表。
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from quant import data, fundamentals, report
from quant.backtest import BacktestEngine
from quant.strategy import get_strategy, list_strategies

import strategies  # noqa: F401  -> 触发策略注册


def load_config(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="FinanceAgent 量化回测")
    ap.add_argument("-c", "--config", default="config.yaml", help="配置文件路径")
    ap.add_argument("--symbols", nargs="+", help="标的代码 (覆盖配置)")
    ap.add_argument("--strategy", help="策略名 (覆盖配置)")
    ap.add_argument("--start", help="起始日期 YYYY-MM-DD")
    ap.add_argument("--end", help="结束日期 YYYY-MM-DD")
    ap.add_argument("--no-plot", action="store_true", help="不输出图表")
    ap.add_argument("--list-strategies", action="store_true", help="列出可用策略后退出")
    ap.add_argument("--ml", action="store_true",
                    help="ML 预测策略, walk-forward 滚动训练 (严格样本外, 较慢但诚实)")
    ap.add_argument("--ml-insample", action="store_true",
                    help="ML 样本内快速演示 (结果被高估, 仅看流程)")
    ap.add_argument("--html", action="store_true", help="生成自包含 HTML 仪表盘到 reports/dashboard.html")
    return ap.parse_args()


def run_ml(symbol: str, df, engine, plot: bool, insample: bool = False):
    """对单标的跑 ML 策略回测。默认 walk-forward (样本外); insample 仅演示。"""
    if insample:
        from quant.ml import PricePredictor, MLStrategy

        predictor = PricePredictor(horizon=5, n_estimators=200, max_depth=3, random_state=42)
        scores = predictor.fit(df)
        print(f"[ml] {symbol} 样本内训练: 训练准确率={scores['train_acc']:.2%} "
              f"验证准确率={scores['test_acc']:.2%} (n_train={scores['n_train']})")
        model_path = predictor.save(f"reports/{symbol}_model.joblib")
        print(f"[ml] 模型已保存: {model_path}")
        print("[ml] ⚠️ 样本内回测, 收益被高估; 诚实结果请用 --ml (walk-forward)")
        strat = MLStrategy(predictor)
    else:
        from quant.ml import WalkForwardStrategy

        print(f"[ml] {symbol} walk-forward 滚动训练中 (每个信号严格样本外) ...")
        strat = WalkForwardStrategy(
            horizon=5, n_estimators=200, max_depth=3, random_state=42
        )

    result = engine.run(df, strat, symbol=symbol)
    report.print_report(result)
    if plot:
        p = report.plot_report(result)
        if p:
            print(f"[report] 图表: {p}")
    return result


def main() -> None:
    args = parse_args()

    if args.list_strategies:
        print("可用策略:")
        for s in list_strategies():
            print(f"  - {s}")
        print("  - ml_predictor (用 --ml 启用)")
        return

    cfg = load_config(args.config)
    symbols = args.symbols or cfg.get("symbols", ["AAPL"])
    strat_name = args.strategy or cfg.get("strategy", "sma_cross")
    start = args.start or cfg.get("start", "2019-01-01")
    end = args.end or (cfg.get("end") or None)
    plot = not args.no_plot and cfg.get("plot", True)
    params = cfg.get("params", {}) if not args.strategy else {}

    # 基本面选股 (可选)
    fs = cfg.get("fundamental_screen", {})
    if fs.get("enabled"):
        before = list(symbols)
        symbols = fundamentals.screen(
            symbols, min_roe=fs.get("min_roe", 0.10), max_pe=fs.get("max_pe", 40)
        )
        print(f"[screen] 基本面过滤: {before} -> {symbols}")

    engine = BacktestEngine(
        initial_cash=cfg.get("initial_cash", 100_000),
        commission=cfg.get("commission", 0.0005),
        slippage=cfg.get("slippage", 0.0005),
        allow_short=cfg.get("allow_short", False),
    )

    results = []
    for symbol in symbols:
        print(f"\n>>> 回测 {symbol} ...")
        df = data.load(symbol, start=start, end=end)

        if args.ml or args.ml_insample:
            try:
                results.append(run_ml(symbol, df, engine, plot, insample=args.ml_insample))
            except Exception as exc:  # noqa: BLE001
                print(f"[ml] {symbol} 失败: {exc}")
            continue

        strat = get_strategy(strat_name, **params)
        result = engine.run(df, strat, symbol=symbol)
        report.print_report(result)
        if plot:
            p = report.plot_report(result)
            if p:
                print(f"[report] 图表: {p}")
        results.append(result)

    if len(results) > 1:
        print("\n" + "=" * 60)
        print("多标的对比")
        print("=" * 60)
        print(report.compare_table(results))

    if args.html and results:
        from quant.dashboard import build_html

        path = build_html(results)
        print(f"\n[dashboard] HTML 仪表盘已生成: {path}  (浏览器直接打开)")


if __name__ == "__main__":
    main()
