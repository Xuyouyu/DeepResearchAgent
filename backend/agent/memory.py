"""
Agent 记忆管理模块
面试高频问题：AI Agent 的记忆机制有哪些？
答：短期记忆（对话上下文/Working Memory）、长期记忆（向量数据库+知识图谱）、
    实体记忆（关键信息提取）、反思记忆（自我总结）

本模块实现了短期工作记忆 + 关键发现持久化
"""
from typing import List, Dict, Any, Optional
from backend.models.schemas import SearchResult, ConflictInfo


class WorkingMemory:
    """
    工作记忆：存储当前调研任务的中间状态
    类比人类大脑的工作记忆，容量有限，只保留当前最相关的信息
    """

    def __init__(self, query: str, max_items: int = 50):
        self.query = query
        self.max_items = max_items
        # 按时间顺序存储思考与观察
        self.thoughts: List[Dict[str, Any]] = []
        # 已收集的搜索结果
        self.collected_sources: List[SearchResult] = []
        # 检测到的冲突
        self.conflicts: List[ConflictInfo] = []
        # 当前计划步骤
        self.current_plan: List[str] = []
        self.current_step_index: int = 0

    def add_thought(self, thought: str, step_type: str = "think"):
        """记录 Agent 的思考过程"""
        self.thoughts.append({
            "type": step_type,
            "content": thought,
            "step": self.current_step_index
        })
        self._trim_if_needed()

    def add_source(self, source: SearchResult):
        """添加信息来源，同时检查重复"""
        existing_urls = {s.url for s in self.collected_sources}
        if source.url not in existing_urls:
            self.collected_sources.append(source)

    def add_conflict(self, conflict: ConflictInfo):
        """记录信息冲突（创新点）"""
        self.conflicts.append(conflict)

    def update_plan(self, plan: List[str]):
        """更新执行计划"""
        self.current_plan = plan
        self.current_step_index = 0

    def advance_step(self):
        """推进到下一步"""
        if self.current_step_index < len(self.current_plan) - 1:
            self.current_step_index += 1

    def get_context_for_llm(self, limit: int = 10) -> str:
        """
        将工作记忆压缩成文本，供 LLM 作为上下文使用
        面试考点：上下文窗口有限时如何处理长记忆？
        答：摘要压缩（Map-Reduce）、关键信息提取、分层记忆
        """
        recent_thoughts = self.thoughts[-limit:]
        context_parts = [
            f"调研主题: {self.query}",
            f"当前计划: {' -> '.join(self.current_plan)}",
            f"当前步骤: {self.current_step_index + 1} / {len(self.current_plan)}",
            "\n近期思考与观察:"
        ]
        for t in recent_thoughts:
            context_parts.append(f"[{t['type']}] {t['content']}")

        if self.conflicts:
            context_parts.append("\n已检测到的信息冲突:")
            for c in self.conflicts[-3:]:
                context_parts.append(f"- {c.claim_a} vs {c.claim_b}")

        return "\n".join(context_parts)

    def _trim_if_needed(self):
        """防止工作记忆无限增长"""
        if len(self.thoughts) > self.max_items:
            # 保留早期的摘要和最近的细节（分层压缩策略）
            early_summary = self._summarize_early_thoughts()
            self.thoughts = [early_summary] + self.thoughts[-(self.max_items - 1):]

    def _summarize_early_thoughts(self) -> Dict[str, Any]:
        """对早期记忆进行摘要（简化版，实际可用 LLM 做）"""
        return {
            "type": "summary",
            "content": f"已完成前 {len(self.thoughts) - self.max_items + 1} 步调研，"
                       f"共收集 {len(self.collected_sources)} 条信息源",
            "step": -1
        }

    def get_collected_contents(self, max_sources: int = 10, max_content_length: int = 2000) -> str:
        """
        获取所有已收集来源的正文，用于最终报告生成
        限制来源数量和内容长度，防止超出 LLM 上下文窗口
        """
        # 按可信度排序，优先使用高质量来源
        sorted_sources = sorted(
            self.collected_sources,
            key=lambda s: getattr(s, 'credibility_score', 0.5),
            reverse=True
        )[:max_sources]

        parts = []
        for i, src in enumerate(sorted_sources, 1):
            content = src.content or src.snippet
            if len(content) > max_content_length:
                content = content[:max_content_length] + "..."
            parts.append(f"[来源{i}] {src.title}\nURL: {src.url}\n内容: {content}\n")
        return "\n---\n".join(parts)
