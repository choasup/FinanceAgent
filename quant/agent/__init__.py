"""Stock Agent —— 从"回测框架"到"分析代理"。

两层能力, 共享同一套工具集 (tools.py):

    analyst.py   规则引擎: 多因子打分 -> 评级/理由/风险, 离线可用, 零依赖
    llm.py       LLM Agent: Claude 自主调用工具 (行情/指标/回测/基本面),
                 输出深度研究报告 (需要 ANTHROPIC_API_KEY)

用法见根目录 agent.py。
"""

from .analyst import analyze, rank
from .tools import TOOLS

__all__ = ["analyze", "rank", "TOOLS"]
