"""
Pydantic 数据模型定义
负责请求/响应的数据校验和序列化
"""
from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from datetime import datetime
from enum import Enum


class ResearchStatus(str, Enum):
    """调研任务状态机"""
    PENDING = "pending"
    PLANNING = "planning"      # 正在规划任务
    SEARCHING = "searching"    # 正在搜索信息
    ANALYZING = "analyzing"    # 正在分析整合
    WRITING = "writing"        # 正在生成报告
    COMPLETED = "completed"
    FAILED = "failed"


class SearchResult(BaseModel):
    """单条搜索结果"""
    title: str = Field(description="网页标题")
    url: str = Field(description="网页链接")
    snippet: str = Field(description="摘要片段")
    content: Optional[str] = Field(default=None, description="完整正文内容")
    source_type: Literal["search", "browse"] = "search"
    credibility_score: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="可信度评分（创新点）"
    )


class ConflictInfo(BaseModel):
    """
    信息冲突检测（创新点）
    当多个来源对同一事实表述不一致时记录
    """
    claim_a: str = Field(description="来源A的观点")
    source_a: str = Field(description="来源A链接")
    claim_b: str = Field(description="来源B的观点")
    source_b: str = Field(description="来源B链接")
    analysis: str = Field(description="LLM对冲突的分析")


class ResearchStep(BaseModel):
    """单个研究步骤的记录"""
    step_number: int
    action_type: Literal["plan", "search", "browse", "extract", "think", "write"]
    action_input: str = Field(description="执行的动作内容")
    observation: Optional[str] = Field(default=None, description="观察到的结果")
    timestamp: datetime = Field(default_factory=datetime.now)


class ResearchRequest(BaseModel):
    """用户发起调研的请求体"""
    query: str = Field(min_length=1, max_length=500, description="调研主题")
    depth: Optional[Literal["auto", "shallow", "medium", "deep"]] = Field(
        default="auto",
        description="调研深度：自动/浅层(3步)/中等(5步)/深度(7步+)"
    )
    language: Optional[Literal["zh", "en"]] = "zh"


class ProgressUpdate(BaseModel):
    """SSE 流式进度推送的数据结构"""
    task_id: str
    status: ResearchStatus
    current_step: int
    total_steps: int
    message: str
    step_detail: Optional[ResearchStep] = None
    report_data: Optional[dict] = None  # 完成时附赠完整报告数据


class ResearchReport(BaseModel):
    """最终生成的调研报告"""
    task_id: str
    query: str
    status: ResearchStatus
    created_at: datetime
    completed_at: Optional[datetime] = None
    outline: List[str] = Field(default_factory=list, description="报告大纲")
    content: str = Field(description="Markdown格式报告正文")
    sources: List[SearchResult] = Field(default_factory=list, description="引用来源")
    conflicts: List[ConflictInfo] = Field(default_factory=list, description="检测到的冲突")
    metadata: dict = Field(default_factory=dict, description="额外元数据")
