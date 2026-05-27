"""
ReAct 核心循环
ReAct = Reasoning + Acting，论文来自 Princeton & Google (2022)
核心思想：LLM 交替进行 思考(Thought) -> 行动(Action) -> 观察(Observation)
"""
import asyncio
import uuid
from typing import AsyncIterator, Optional
from datetime import datetime

from backend.models.schemas import (
    ResearchRequest, ResearchReport, ResearchStatus,
    ResearchStep, ProgressUpdate, ConflictInfo
)
from backend.core.llm import LLMClient
from backend.agent.memory import WorkingMemory
from backend.agent.planner import AdaptivePlanner
from backend.agent.tools import SearchTool, BrowserTool, CredibilityScorer


class ReActResearchAgent:
    """
    深度调研 Agent
    创新点整合：
    1. 自适应深度规划：根据问题复杂度动态调整步骤
    2. 冲突检测：多源信息不一致时自动标记
    3. 可信度评分：对来源进行可信度评估
    4. 流式进度：SSE 实时推送思考过程
    """

    def __init__(self):
        self.llm = LLMClient()
        self.planner = AdaptivePlanner(self.llm)
        self.search_tool = SearchTool()
        self.browser = BrowserTool()

    async def run(
        self,
        request: ResearchRequest,
        task_id: Optional[str] = None
    ) -> ResearchReport:
        """
        同步执行完整调研流程（用于非流式接口）
        """
        task_id = task_id or str(uuid.uuid4())[:8]
        memory = WorkingMemory(query=request.query)

        report = ResearchReport(
            task_id=task_id,
            query=request.query,
            status=ResearchStatus.PLANNING,
            created_at=datetime.now()
        )

        try:
            # 1. 确定深度
            if request.depth == "shallow":
                depth = "shallow"
            elif request.depth == "deep":
                depth = "deep"
            else:
                depth = await self.planner.analyze_complexity(request.query)

            # 2. 生成计划
            plan = await self.planner.create_plan(request.query, depth)
            memory.update_plan(plan)
            report.status = ResearchStatus.SEARCHING

            # 3. 执行 ReAct 循环
            for step_idx, step_desc in enumerate(plan):
                memory.current_step_index = step_idx

                # Thought: 思考当前步骤要做什么
                thought = await self._think(memory, step_desc)
                memory.add_thought(thought, step_type="think")

                # Action: 执行搜索或浏览
                action_result = await self._act(thought, memory)
                memory.add_thought(action_result, step_type="observe")

                # 冲突检测（每步结束后检查）
                if len(memory.collected_sources) >= 2:
                    await self._detect_conflicts(memory)

            # 4. 生成报告
            report.status = ResearchStatus.WRITING
            report.content = await self._generate_report(memory, request.language)
            report.outline = plan
            report.sources = memory.collected_sources
            report.conflicts = memory.conflicts
            report.status = ResearchStatus.COMPLETED
            report.completed_at = datetime.now()

        except Exception as e:
            report.status = ResearchStatus.FAILED
            report.content = f"调研过程中出现错误: {str(e)}"

        finally:
            await self.browser.close()
            await self.llm.close()

        return report

    async def run_stream(
        self,
        request: ResearchRequest,
        task_id: Optional[str] = None
    ) -> AsyncIterator[ProgressUpdate]:
        """
        流式执行调研流程（SSE 用）
        """
        task_id = task_id or str(uuid.uuid4())[:8]
        memory = WorkingMemory(query=request.query)
        total_steps = 5  # 先预估，等计划生成后更新

        yield ProgressUpdate(
            task_id=task_id,
            status=ResearchStatus.PENDING,
            current_step=0,
            total_steps=total_steps,
            message="正在分析查询复杂度..."
        )

        try:
            # 1. 规划
            if request.depth == "auto":
                depth = await self.planner.analyze_complexity(request.query)
            else:
                depth = request.depth
            plan = await self.planner.create_plan(request.query, depth)
            memory.update_plan(plan)
            total_steps = len(plan)

            yield ProgressUpdate(
                task_id=task_id,
                status=ResearchStatus.PLANNING,
                current_step=0,
                total_steps=total_steps,
                message=f"已生成调研计划（深度: {depth}），共 {total_steps} 步: {' -> '.join(plan)}"
            )

            await asyncio.sleep(0.5)  # 让前端有时间渲染

            # 2. 执行循环
            for step_idx, step_desc in enumerate(plan):
                memory.current_step_index = step_idx

                yield ProgressUpdate(
                    task_id=task_id,
                    status=ResearchStatus.SEARCHING,
                    current_step=step_idx + 1,
                    total_steps=total_steps,
                    message=f"步骤 {step_idx + 1}/{total_steps}: {step_desc}"
                )

                # Thought
                thought = await self._think(memory, step_desc)
                memory.add_thought(thought, step_type="think")
                yield ProgressUpdate(
                    task_id=task_id,
                    status=ResearchStatus.ANALYZING,
                    current_step=step_idx + 1,
                    total_steps=total_steps,
                    message=f"🧠 思考: {thought[:100]}..."
                )

                # Action
                action_result = await self._act(thought, memory)
                memory.add_thought(action_result, step_type="observe")
                yield ProgressUpdate(
                    task_id=task_id,
                    status=ResearchStatus.SEARCHING,
                    current_step=step_idx + 1,
                    total_steps=total_steps,
                    message=f"🔍 获取到 {len(memory.collected_sources)} 条信息源"
                )

                # 冲突检测
                if len(memory.collected_sources) >= 2:
                    conflicts_found = await self._detect_conflicts(memory)
                    if conflicts_found:
                        yield ProgressUpdate(
                            task_id=task_id,
                            status=ResearchStatus.ANALYZING,
                            current_step=step_idx + 1,
                            total_steps=total_steps,
                            message=f"⚠️ 检测到 {len(memory.conflicts)} 处信息冲突"
                        )

                await asyncio.sleep(0.3)

            # 3. 生成报告
            yield ProgressUpdate(
                task_id=task_id,
                status=ResearchStatus.WRITING,
                current_step=total_steps,
                total_steps=total_steps,
                message="正在整合信息并生成报告..."
            )

            content = await self._generate_report(memory, request.language)

            # 最终完成消息，把完整报告放在 report_data 里
            yield ProgressUpdate(
                task_id=task_id,
                status=ResearchStatus.COMPLETED,
                current_step=total_steps,
                total_steps=total_steps,
                message="调研完成，报告已生成",
                report_data={
                    "content": content,
                    "sources": [s.model_dump() for s in memory.collected_sources],
                    "conflicts": [c.model_dump() for c in memory.conflicts],
                    "outline": memory.current_plan
                }
            )

        except Exception as e:
            yield ProgressUpdate(
                task_id=task_id,
                status=ResearchStatus.FAILED,
                current_step=0,
                total_steps=total_steps,
                message=f"错误: {str(e)}"
            )
        finally:
            await self.browser.close()
            await self.llm.close()

    async def _think(self, memory: WorkingMemory, step_desc: str) -> str:
        """
        Thought 步骤：基于当前记忆，决定具体怎么执行这一步
        """
        context = memory.get_context_for_llm(limit=8)
        prompt = f"""你是一位研究分析师，正在执行调研任务。请根据已有信息，思考下一步该如何执行。

{context}

当前步骤要求：{step_desc}

请用 1-2 句话说明你的具体执行策略（例如"我应该搜索 XXX 来获取 YYY 信息"）。只输出思考内容，不要输出多余解释。"""

        return await self.llm.chat([{"role": "user", "content": prompt}], temperature=0.4)

    async def _act(self, thought: str, memory: WorkingMemory) -> str:
        """
        Action 步骤：根据思考结果，调用工具获取信息
        简化版逻辑：从 thought 中提取搜索关键词并执行搜索
        """
        # 从 thought 中提取搜索词（简化：直接用 thought 当查询词，或让 LLM 提取）
        search_query = thought.strip()
        if len(search_query) > 100:
            search_query = search_query[:100]

        results = await self.search_tool.search(search_query)

        if not results:
            return f"搜索 '{search_query}' 未返回结果，尝试换个关键词。"

        # 访问前 2 个结果获取详细内容
        detailed_sources = []
        for r in results[:2]:
            content = await self.browser.fetch(r.url)
            r.content = content
            r.credibility_score = CredibilityScorer.score(r.url, len(content))
            memory.add_source(r)
            detailed_sources.append(f"{r.title} (可信度: {r.credibility_score:.2f}): {content[:300]}...")

        return "\n".join(detailed_sources)

    async def _detect_conflicts(self, memory: WorkingMemory) -> bool:
        """
        冲突检测（创新点）
        当收集到多条信息时，让 LLM 判断是否存在事实冲突
        """
        if len(memory.collected_sources) < 2:
            return False

        # 取最近两条来源进行对比
        recent = memory.collected_sources[-2:]
        s1, s2 = recent[0], recent[1]

        prompt = f"""请判断以下两个来源的信息是否存在事实冲突。如果不冲突，只回复"无冲突"。

来源 A ({s1.title}, {s1.url}):
{s1.content[:500]}

来源 B ({s2.title}, {s2.url}):
{s2.content[:500]}

如果存在冲突，请用 JSON 格式回复：
{{"conflict": true, "claim_a": "来源A的观点", "claim_b": "来源B的观点", "analysis": "你的分析"}}
如果不冲突，回复：{{"conflict": false}}"""

        try:
            response = await self.llm.chat([{"role": "user", "content": prompt}], temperature=0.2)
            import json
            result = json.loads(response.strip())
            if result.get("conflict"):
                memory.add_conflict(ConflictInfo(
                    claim_a=result.get("claim_a", ""),
                    source_a=s1.url,
                    claim_b=result.get("claim_b", ""),
                    source_b=s2.url,
                    analysis=result.get("analysis", "")
                ))
                return True
        except Exception:
            pass
        return False

    async def _generate_report(self, memory: WorkingMemory, language: str) -> str:
        """
        生成最终调研报告
        """
        sources_text = memory.get_collected_contents()
        conflict_text = ""
        if memory.conflicts:
            conflict_text = "\n\n以下信息源之间存在冲突，请注意甄别：\n"
            for i, c in enumerate(memory.conflicts, 1):
                conflict_text += f"{i}. {c.claim_a} (来源: {c.source_a}) vs {c.claim_b} (来源: {c.source_b})\n   分析: {c.analysis}\n"

        lang_instruction = "用中文撰写" if language == "zh" else "Write in English"

        prompt = f"""你是一位资深行业分析师。请根据以下收集到的信息，撰写一份结构清晰的调研报告。

调研主题：{memory.query}

已收集的信息：
{sources_text}
{conflict_text}

要求：
1. {lang_instruction}
2. 报告应包含：执行摘要、背景介绍、核心发现、对比分析、结论与建议
3. 每个关键论点都要标注来源编号（如 [来源1]）
4. 如果存在信息冲突，请在报告中明确说明并给出你的判断
5. 使用 Markdown 格式，适当使用列表、表格、加粗等排版
6. 字数不少于 800 字

调研报告："""

        return await self.llm.chat([{"role": "user", "content": prompt}], temperature=0.5, max_tokens=4000)
