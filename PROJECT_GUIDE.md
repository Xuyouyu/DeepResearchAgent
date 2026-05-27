# DeepResearchAgent 源码阅读指南

> 按本文档顺序阅读源码，可在 30 分钟内建立完整认知。建议打开 PyCharm，边读边打断点跑一遍流式调研接口，观察 `memory.get_context_for_llm()` 在每步的输出。

---

## 阅读路线图

```
第一轮（骨架）：schemas.py → config.py → main.py
第二轮（大脑）：react_loop.py → planner.py → memory.py
第三轮（手脚）：tools.py → llm.py
第四轮（展示）：frontend/index.html
```

---

## 第一轮：建立全局地图

### 1. `backend/models/schemas.py` —— 系统的"血液类型"

**作用**：用 Pydantic 定义所有数据模型，是前后端、各模块之间的"通用语言"。

**核心类型**：

| 模型 | 含义 | 出现位置 |
|------|------|---------|
| `ResearchRequest` | 用户输入（query + depth + language） | `main.py` 的接口参数 |
| `ResearchReport` | 最终报告（content + sources + conflicts） | `react_loop.py` 的产出 |
| `ProgressUpdate` | SSE 进度推送的数据结构 | `run_stream()` 的 yield 对象 |
| `SearchResult` | 单条搜索结果（title/url/snippet/content/credibility_score） | `tools.py` 的产出，`memory.py` 的存储单元 |
| `ConflictInfo` | 冲突记录（claim_a vs claim_b + analysis） | `_detect_conflicts()` 的产出 |
| `ResearchStatus` | 状态机枚举（pending → planning → searching → ... → completed） | 贯穿整个流式推送 |

**设计要点**：
- `SearchResult.credibility_score` 用 `Field(ge=0.0, le=1.0)` 做数值范围校验，体现 Pydantic v2 的校验能力。
- `ProgressUpdate.report_data` 为可选字段，只在 `completed` 状态时携带完整报告，避免每步都传输大量数据。

---

### 2. `backend/core/config.py` —— 配置管理

**作用**：从 `.env` 文件读取环境变量，统一暴露为类型化的 Settings 对象。

**关键代码**：
```python
class Settings(BaseSettings):
    LLM_API_KEY: str
    LLM_BASE_URL: str = "https://api.moonshot.cn/v1"
    LLM_MODEL: str = "moonshot-v1-8k"
    ...

    class Config:
        env_file = ".env"
```

**设计要点**：
- `lru_cache()` 包装 `get_settings()`，避免重复读取文件。
- 默认值设计：没有 Key 时程序能启动（虽然会报错），方便新人 clone 下来先跑通结构。

---

### 3. `backend/main.py` —— FastAPI 入口与对外接口

**作用**：暴露 HTTP 接口，承接前端请求，调度 Agent 执行。

**两个核心接口**：

#### `POST /api/research`（非流式）
- 适合后台任务或不关心进度的场景。
- 直接返回 `ResearchReport` JSON，响应时间 30s~120s。
- 异常时抛 `HTTPException(status_code=500)`。

#### `POST /api/research/stream`（流式 SSE）
- 返回 `StreamingResponse`，`media_type="text/event-stream"`。
- `event_generator()` 是异步生成器，每执行一步就 `yield` 一个 `ProgressUpdate`。
- SSE 格式要求：`data: {...}\n\n`（以两个换行结束）。

**关键设计**：
```python
headers = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no"  # 禁用 Nginx 缓冲，确保实时推送
}
```

**静态文件挂载**：
```python
app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")
```
- 这行让 `http://localhost:8000/` 直接返回前端页面，前后端一体化运行。

---

## 第二轮：Agent 核心逻辑（项目精华）

### 4. `backend/agent/react_loop.py` —— ReAct 大脑

**作用**：项目最核心的文件。实现 `Thought → Action → Observation` 循环，统筹整个调研流程。

**主流程（`run()` 方法）**：

```
1. 分析复杂度（shallow/medium/deep）
2. 生成执行计划（plan: List[str]）
3. for 循环执行每一步：
   a. _think(memory, step_desc)      → Thought
   b. _act(thought, memory)          → Action + Observation
   c. _detect_conflicts(memory)      → 冲突检测（每步结束后）
4. _generate_report(memory, language) → 最终报告
```

**四个核心方法解析**：

#### `_think(memory, step_desc)` —— 决策
- 输入：当前工作记忆 + 当前步骤描述
- 输出：一句话的执行策略（如"我应该搜索 XXX 来获取 YYY 信息"）
- 关键：`memory.get_context_for_llm(limit=8)` 只取最近 8 条记忆，**防止上下文爆炸**。

#### `_act(thought, memory)` —— 执行
- 直接用 Thought 的内容当搜索词（简化设计）。
- 搜索后取前 2 个结果，用 `BrowserTool.fetch()` 获取详细内容。
- 每条来源计算可信度 `CredibilityScorer.score()`，存入 `memory`。

#### `_detect_conflicts(memory)` —— 冲突检测（创新点）
- 取最近两条来源，让 LLM 判断是否存在事实冲突。
- LLM 输出 JSON 格式：`{"conflict": true/false, "claim_a": ..., "claim_b": ..., "analysis": ...}`
- 如果冲突，存入 `memory.conflicts`，最终在报告中展示。

#### `_generate_report(memory, language)` —— 报告生成
- 收集所有来源内容（已做截断保护），拼接成 prompt。
- 要求 LLM 按固定结构输出：执行摘要、背景介绍、核心发现、对比分析、结论与建议。
- `temperature=0.5` 比思考时略高，让报告有一定创造性；`max_tokens=4000` 确保报告长度。

**流式版 `run_stream()`**：
- 逻辑与 `run()` 完全一致，但在每个关键节点 `yield ProgressUpdate(...)`，让前端实时看到进度。
- `await asyncio.sleep(0.3)` 故意留一点延迟，让前端动画更自然。

---

### 5. `backend/agent/planner.py` —— 自适应规划器

**作用**：根据问题复杂度，动态决定调研深度和具体步骤。

**两个方法**：

#### `analyze_complexity(query)` —— 复杂度判断
- 给 LLM 一个极简 prompt，要求只回复 `shallow`、`medium`、`deep` 之一。
- `temperature=0.1` 几乎确定性输出，减少随机性。
- 兜底：如果 LLM 输出异常，默认返回 `medium`。

#### `create_plan(query, depth)` —— 生成步骤列表
- 根据 depth 取 `DEPTH_CONFIG`（shallow=3步, medium=5步, deep=7步）。
- 让 LLM 生成 JSON 数组，如 `["搜索背景", "对比方案", "分析趋势", "生成报告"]`。
- **容错设计**：如果 LLM 返回的不是合法 JSON，有三层 fallback：
  1. 直接解析；
  2. 提取 markdown 代码块；
  3. 按行分割，过滤无效字符；
  4. 最终兜底用默认三步计划。

---

### 6. `backend/agent/memory.py` —— 工作记忆

**作用**：Agent 的"短期记忆"，存储当前任务的中间状态。

**核心数据结构**：
```python
self.thoughts: List[Dict]          # 思考链（Think + Observe）
self.collected_sources: List[SearchResult]  # 已收集的来源
self.conflicts: List[ConflictInfo] # 检测到的冲突
self.current_plan: List[str]       # 当前执行计划
```

**两个关键方法**：

#### `get_context_for_llm(limit=8)` —— 记忆压缩
- 只取最近 `limit` 条 thought，拼接成文本供 LLM 使用。
- 包含：调研主题、当前计划、当前步骤、近期思考与观察、已检测冲突。
- **为什么 limit=8？** 因为上下文窗口有限，必须截断。这是工程上最常见的妥协。

#### `get_collected_contents()` —— 来源汇总（已加固）
- 按可信度排序，只取前 10 个来源。
- 每个来源内容最多 2000 字，超长截断 + `...`。
- 防止生成报告时 prompt 过长导致 token 超限。

**记忆防溢出**：
```python
def _trim_if_needed(self):
    if len(self.thoughts) > self.max_items:
        early_summary = self._summarize_early_thoughts()
        self.thoughts = [early_summary] + self.thoughts[-(self.max_items - 1):]
```
- 超过 50 条时，把早期记忆压缩成一条摘要，保留最近细节。**这是分层记忆策略的简化实现。**

---

## 第三轮：工具与基础设施

### 7. `backend/agent/tools.py` —— 工具集

**作用**：Agent 的"手脚"——搜索网页、获取正文、评估可信度。

**三个工具类**：

#### `SearchTool`
- **优先 Tavily**：专为 AI RAG 设计的搜索 API，返回已清洗的摘要，质量高。
- **降级 DuckDuckGo**：无需 API Key，适合快速验证。用 `html.duckduckgo.com` 的 HTML 版本解析结果。
- `max_results` 从配置读取（默认 5）。

#### `BrowserTool`
- `fetch(url)`：用 `httpx` 异步获取网页，超时 30 秒。
- `_extract_text(html)`：正文提取的简化实现：
  1. 移除 `script/style/nav/footer/header/aside/noscript` 等噪声标签；
  2. 优先取 `<main>` / `<article>` / `div.content`；
  3. 清理空行；
  4. **截断到 8000 字符**，防止单页过长。
- **为什么不用完整浏览器（如 Selenium/Playwright）？** 因为 Agent 对 JS 渲染需求不高，简化方案减少依赖和启动时间。

#### `CredibilityScorer`（创新点）
- 基于规则的可信度评分，0.0~1.0：
  - 基础分 0.5；
  - 可信域名（github/arxiv/wikipedia/知乎等）+0.2；
  - HTTPS +0.1；
  - 内容长度适中（500~5000 字）+0.1。
- **为什么是规则而不是 LLM 打分？** 规则快、成本低、可解释；LLM 打分更准但更慢更贵。这里是权衡后的选择。

---

### 8. `backend/core/llm.py` —— LLM 客户端

**作用**：封装 HTTP 请求，统一对接多厂商 OpenAI-compatible API。

**为什么不直接用 `openai` SDK？**
- 展示自己封装 HTTP 的能力；
- 更容易控制重试、日志、多厂商适配；
- 减少黑盒依赖，降低外部依赖风险。

**两个方法**：

#### `chat(messages, temperature, max_tokens, stream=False)`
- 非流式对话，Agent 的 `_think`、`_act`、`_generate_report` 都用它。
- `temperature` 根据场景调整：决策/规划用低温度（0.1~0.3），报告生成用中温度（0.5）。

#### `chat_stream(messages, temperature)`
- 流式对话，返回 `AsyncIterator[str]`，逐字 yield。
- 解析 SSE 格式的响应行：`data: {...}\n\n`。

**全局单例**：
```python
_llm_client: Optional[LLMClient] = None

async def get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client
```
- 避免重复创建 HTTP 连接池，提升性能。

---

## 第四轮：前端展示

### 9. `frontend/index.html` —— SSE 实时进度展示

**作用**：纯原生 HTML/CSS/JS，无框架依赖，展示流式调研进度和最终报告。

**核心逻辑**：

#### `startResearch()`
1. 收集用户输入（query/depth/language）；
2. 用 `fetch()` POST 到 `/api/research/stream`；
3. 通过 `response.body.getReader()` + `TextDecoder()` 手动解析 SSE；
4. 每收到一条 `data:` 消息，调用 `handleUpdate(data)`。

**为什么不用原生 `EventSource`？**
- 因为原生 `EventSource` 只支持 GET 请求，而本项目需要 POST 携带 JSON body。
- 所以用 `fetch` + 手动解析 `data: {...}\n\n` 格式。

#### `handleUpdate(data)`
- 更新进度条、状态文字、日志区域；
- 状态为 `completed` 时，调用 `showReport()` 渲染报告。

#### `showReport(content, sources, conflicts)`
- **简易 Markdown 转 HTML**：用正则替换 `#`、`**`、`*`、`` ` ``、`>`、`-` 等语法。
- 冲突信息用黄色警告框展示。
- 来源列表带可信度百分比。

---

## 架构总图

```
用户输入
   ↓
frontend/index.html (POST /api/research/stream)
   ↓
backend/main.py (FastAPI 路由)
   ↓
ReActResearchAgent.run_stream()
   ├── AdaptivePlanner.analyze_complexity()  → shallow/medium/deep
   ├── AdaptivePlanner.create_plan()         → ["步骤1", "步骤2", ...]
   └── for step in plan:
         ├── _think()                        → LLM.chat(temperature=0.4)
         │      ↑
         │      └─ WorkingMemory.get_context_for_llm(limit=8)
         ├── _act()                          → SearchTool.search() + BrowserTool.fetch()
         │      ↓
         │      └─ WorkingMemory.add_source()
         └── _detect_conflicts()             → LLM.chat(temperature=0.2)
                ↓
                └─ WorkingMemory.add_conflict()
   └── _generate_report()                    → LLM.chat(temperature=0.5, max_tokens=4000)
         ↓
    ProgressUpdate (SSE yield) → 前端实时渲染
         ↓
    ResearchReport (completed)
```

---

## 推荐阅读策略

| 时间 | 行动 | 目标 |
|------|------|------|
 0-5 min | 读 schemas.py + main.py | 知道系统有什么接口、传什么数据 |
 5-10 min | 读 react_loop.py，同时打断点跑一遍 | 理解 ReAct 主循环的每一步 |
10-20 min | 读 planner.py + memory.py + tools.py | 理解每个模块的职责和交互 |
20-25 min | 读 llm.py + frontend/index.html | 补齐通信和展示层 |
25-30 min | 回头看 react_loop.py，对照架构图 | 建立全局认知，理解整体架构 |

---

## 扩展思考

读完源码后可以思考这些问题，展示你对项目的深度理解：

1. **上下文窗口瓶颈**：当前用 `limit=8` 和 `[:8000]` 硬截断，如果换成 128K 模型，是否能取消限制？答：不能，因为 Agent 可能跑 20 步以上，累计内容仍会爆，需要更优雅的记忆压缩（如 LLM 摘要）。
2. **单点故障**：LLM 调用失败时整个调研就失败了，怎么优化？答：加重试机制（exponential backoff）、降级到备用模型、或把失败步骤标记为"跳过"继续后续步骤。
3. **搜索质量**：DuckDuckGo 免费版经常被限流，怎么保证稳定性？答：加本地缓存、多搜索引擎轮询、或引入向量检索作为兜底。
4. **报告质量**：当前报告是单次生成，如果内容特别多，怎么保证不遗漏重点？答：Map-Reduce 策略——先让每个来源生成小摘要，再基于摘要生成报告。
