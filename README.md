# DeepResearchAgent

基于 **ReAct 架构** 的深度调研 Agent，支持自适应规划、多源冲突检测与溯源报告生成。

---

## 项目亮点

1. **自研 ReAct 循环**：不依赖 LangChain 等封装框架，自己实现 Thought -> Action -> Observation 循环，展示对 Agent 底层原理的理解。
2. **自适应深度规划**：根据查询复杂度自动选择 shallow / medium / deep 三种调研深度，而非固定步骤。
3. **多源冲突检测**：LLM 自动对比不同来源的信息，发现事实冲突时标记并分析，避免生成"和稀泥"的报告。
4. **来源可信度评分**：基于域名信誉、HTTPS、内容长度等规则，为每条信息源打分，报告引用时展示可信度。
5. **SSE 流式推送**：前端实时观看 Agent 的思考、搜索、分析全过程，提升交互体验。
6. **工程化**：FastAPI 异步后端、Pydantic 数据校验、Docker 容器化部署。

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端框架 | FastAPI + Uvicorn |
| Agent 核心 | 自研 ReAct Loop（原生 OpenAI-compatible API） |
| 数据校验 | Pydantic v2 |
| 网页解析 | BeautifulSoup4 + httpx |
| 搜索 | Tavily API / DuckDuckGo（降级） |
| 前端 | 原生 HTML/JS + SSE |
| 部署 | Docker + Docker Compose |

---

## 快速开始

### 1. 克隆与配置

```bash
cd /d/DeepResearchAgent
cp .env.example .env
# 编辑 .env，填入你的 LLM API Key（推荐 Moonshot / 智谱 GLM）
```

### 2. 本地运行（开发模式）

```bash
cd backend
pip install -r requirements.txt
cd ..
python -m backend.main
```

访问 http://localhost:8000 查看前端界面，
API 文档 http://localhost:8000/docs

### 3. Docker 部署

```bash
docker-compose up --build
```

---

## 项目结构

```
DeepResearchAgent/
├── backend/
│   ├── main.py              # FastAPI 入口，REST + SSE 接口
│   ├── agent/
│   │   ├── react_loop.py    # ReAct 核心循环（项目核心）
│   │   ├── planner.py       # 自适应任务规划器
│   │   ├── tools.py         # 搜索、浏览、可信度评分
│   │   └── memory.py        # Agent 工作记忆管理
│   ├── core/
│   │   ├── llm.py           # LLM 客户端封装（支持多厂商）
│   │   └── config.py        # 配置管理（Pydantic Settings）
│   └── models/
│       └── schemas.py       # 数据模型与类型定义
├── frontend/
│   └── index.html           # 前端界面（SSE 实时进度）
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

---

## 后续可扩展方向

- [ ] **长期记忆**：接入向量数据库（Chroma/Milvus），保存历史调研记录，支持"基于之前的研究继续深入"
- [ ] **代码 Agent**：扩展到 GitHub 仓库分析、自动文档生成
- [ ] **多 Agent 协作**：Researcher / Writer / Reviewer 三个 Agent 分工协作
- [ ] **前端升级**：React/Vue + TypeScript，支持报告导出 PDF/Markdown
