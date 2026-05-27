"""
任务规划器（Planner）
实现自适应深度规划（创新点）：根据问题复杂度动态调整调研步骤数

本模块采用 Plan-and-Solve + 自适应深度
"""
import json
from typing import List
from backend.core.llm import LLMClient


class AdaptivePlanner:
    """
    自适应规划器
    根据用户查询的复杂度，自动决定调研深度
    """

    DEPTH_CONFIG = {
        "shallow": {
            "max_steps": 3,
            "searches_per_step": 2,
            "description": "简单事实查询，如'某公司的创始人是谁'"
        },
        "medium": {
            "max_steps": 5,
            "searches_per_step": 3,
            "description": "需要综合多源信息的分析型问题"
        },
        "deep": {
            "max_steps": 7,
            "searches_per_step": 4,
            "description": "深度调研，需要多轮搜索、对比分析、趋势判断"
        }
    }

    def __init__(self, llm: LLMClient):
        self.llm = llm

    async def analyze_complexity(self, query: str) -> str:
        """
        自动判断问题复杂度
        如果不指定 depth，让 LLM 自己判断应该用 shallow/medium/deep
        """
        prompt = f"""请判断以下查询的调研复杂度，只回复一个字：shallow、medium 或 deep。

查询：{query}

判断标准：
- shallow：只需要一个简单事实，1-2 个来源即可验证（如"某公司成立时间"）
- medium：需要综合 3-5 个来源，进行简单对比分析（如"比较 A 和 B 两种技术的优缺点"）
- deep：需要深度调研，涉及趋势判断、多维度分析、最新进展（如"2025 年 AI Agent 领域的技术演进与商业落地分析"）

复杂度："""
        response = await self.llm.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1  # 几乎确定性输出
        )
        result = response.strip().lower()
        if result not in self.DEPTH_CONFIG:
            return "medium"
        return result

    async def create_plan(self, query: str, depth: str) -> List[str]:
        """
        为给定查询生成具体执行计划
        返回的是步骤列表，如：
        ["搜索背景定义", "搜索主流方案", "对比各方案优缺点", "分析最新趋势", "生成总结报告"]
        """
        config = self.DEPTH_CONFIG[depth]
        prompt = f"""你是一位专业的研究分析师。请为以下调研主题制定详细的执行计划。

调研主题：{query}
调研深度：{depth}（最多 {config['max_steps']} 步）

要求：
1. 每一步都是明确的动作描述（如"搜索 XX 的定义与背景"、"访问官网获取技术细节"）
2. 计划要覆盖从信息收集到分析总结的全流程
3. 不要超过 {config['max_steps']} 步
4. 直接返回 JSON 数组，不要有任何解释，例如：["步骤1", "步骤2", ...]

执行计划："""

        response = await self.llm.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3
        )

        # 解析 JSON，容错处理
        try:
            # 先尝试直接解析
            plan = json.loads(response.strip())
        except json.JSONDecodeError:
            # 如果 LLM 加了 markdown 代码块，尝试提取
            try:
                if "```json" in response:
                    json_str = response.split("```json")[1].split("```")[0]
                elif "```" in response:
                    json_str = response.split("```")[1].split("```")[0]
                else:
                    # 尝试找方括号
                    start = response.find("[")
                    end = response.rfind("]")
                    json_str = response[start:end+1]
                plan = json.loads(json_str.strip())
            except Exception:
                # 兜底：按行分割
                plan = [line.strip("- *0123456789. ") for line in response.split("\n")
                        if line.strip() and not line.strip().startswith("```")]

        # 确保是列表且不为空
        if not isinstance(plan, list) or not plan:
            plan = [f"搜索 {query} 的相关背景信息",
                    f"深入搜索 {query} 的技术细节与案例",
                    f"综合分析并生成报告"]

        return plan[:config["max_steps"]]
