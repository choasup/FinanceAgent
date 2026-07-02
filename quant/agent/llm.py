"""LLM Agent —— Claude 自主调用工具做深度个股研究。

工作方式 (手动 agentic loop):
    1. 把 tools.py 里的工具集暴露给 Claude
    2. Claude 自主决定调用哪些工具 (行情/指标/回测/基本面)
    3. 工具在本地执行, 结果回传
    4. 循环直到 Claude 完成分析, 输出结构化中文研究报告

依赖: pip install anthropic;  环境变量 ANTHROPIC_API_KEY (或 `ant auth login`)。
"""

from __future__ import annotations

import json

from .tools import TOOLS, TOOL_IMPL

MODEL = "claude-opus-4-8"
MAX_TOOL_ROUNDS = 12

SYSTEM = """你是一名严谨的量化股票分析师。你可以调用工具获取行情、技术指标、历史回测和基本面数据。

分析流程要求:
1. 先用 get_price_snapshot 和 get_technical_indicators 了解现状
2. 用 run_backtest 验证技术信号在该标的历史上是否有效 (至少测一个策略)
3. 如可用, 用 get_fundamentals 补充基本面视角
4. 所有结论必须引用工具返回的具体数字, 不得凭空编造

输出一份中文研究报告, 包含:
## 核心观点  (一句话评级: 看多/中性/看空 + 置信度)
## 技术面    (趋势/动量/超买超卖, 引用具体读数)
## 信号有效性 (回测结果说明该标的适不适合技术策略)
## 基本面    (如数据可用)
## 风险提示
## 操作参考  (关注价位/止损思路, 强调仓位管理)

最后必须注明: 本报告为量化研究工具生成, 不构成投资建议。"""


def _execute_tool(name: str, tool_input: dict) -> str:
    """执行本地工具, 返回 JSON 字符串; 出错时返回错误描述。"""
    fn = TOOL_IMPL.get(name)
    if fn is None:
        return json.dumps({"error": f"未知工具 {name}"}, ensure_ascii=False)
    try:
        return json.dumps(fn(**tool_input), ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": str(exc)}, ensure_ascii=False)


def research(symbol: str, question: str | None = None, verbose: bool = True) -> str:
    """对单只股票运行 LLM 深度研究, 返回报告文本。"""
    try:
        import anthropic
    except ImportError as exc:
        raise RuntimeError("需要安装 anthropic SDK: pip install anthropic") from exc

    client = anthropic.Anthropic()

    user_prompt = question or f"请对 {symbol} 做一次全面的量化分析并给出研究报告。"
    messages: list[dict] = [{"role": "user", "content": user_prompt}]

    for _round in range(MAX_TOOL_ROUNDS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            system=SYSTEM,
            tools=TOOLS,
            messages=messages,
        )

        if response.stop_reason == "refusal":
            return "[agent] 请求被安全策略拒绝, 请调整问题后重试。"

        if response.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": response.content})
            continue

        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if response.stop_reason != "tool_use" or not tool_uses:
            # 完成: 提取全部文本
            return "".join(b.text for b in response.content if b.type == "text")

        # 执行所有工具调用, 结果合并进同一条 user 消息
        messages.append({"role": "assistant", "content": response.content})
        results = []
        for tu in tool_uses:
            if verbose:
                print(f"[agent] 调用工具 {tu.name}({json.dumps(tu.input, ensure_ascii=False)})")
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": _execute_tool(tu.name, tu.input),
                }
            )
        messages.append({"role": "user", "content": results})

    return "[agent] 超过最大工具调用轮数, 分析未完成。"
