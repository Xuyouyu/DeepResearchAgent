"""
Agent 工具集合
ReAct 架构的核心：LLM 通过调用外部工具获取信息，而非仅靠参数记忆
工具设计原则：每个工具只做一件事，输入输出明确
"""
import httpx
import re
from typing import List, Optional
from bs4 import BeautifulSoup
from backend.models.schemas import SearchResult
from backend.core.config import get_settings


class SearchTool:
    """
    搜索工具
    """

    def __init__(self):
        settings = get_settings()
        self.tavily_key = settings.TAVILY_API_KEY
        self.max_results = settings.SEARCH_MAX_RESULTS

    async def search(self, query: str) -> List[SearchResult]:
        """
        执行网络搜索
        优先使用 Tavily（质量高，专为 AI RAG 设计），
        如果没有配置 Key，则降级到 DuckDuckGo 免费搜索
        """
        if self.tavily_key:
            return await self._search_tavily(query)
        return await self._search_duckduckgo(query)

    async def _search_tavily(self, query: str) -> List[SearchResult]:
        """Tavily API：返回已清洗的摘要，非常适合 Agent 使用"""
        url = "https://api.tavily.com/search"
        payload = {
            "api_key": self.tavily_key,
            "query": query,
            "max_results": self.max_results,
            "include_answer": False,
            "search_depth": "basic"
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            results = []
            for r in data.get("results", []):
                results.append(SearchResult(
                    title=r.get("title", ""),
                    url=r.get("url", ""),
                    snippet=r.get("content", ""),
                    source_type="search"
                ))
            return results

    async def _search_duckduckgo(self, query: str) -> List[SearchResult]:
        """
        DuckDuckGo 免费搜索（无需 API Key）
        使用 html 版本，适合快速原型验证
        """
        url = "https://html.duckduckgo.com/html/"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, data={"q": query})
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            results = []
            for item in soup.select(".result")[:self.max_results]:
                title_tag = item.select_one(".result__a")
                snippet_tag = item.select_one(".result__snippet")
                if title_tag and snippet_tag:
                    href = title_tag.get("href", "")
                    # DuckDuckGo 的 href 是跳转链接，需要解析或直接展示
                    results.append(SearchResult(
                        title=title_tag.get_text(strip=True),
                        url=href,
                        snippet=snippet_tag.get_text(strip=True),
                        source_type="search"
                    ))
            return results


class BrowserTool:
    """
    网页浏览与内容提取工具
    为什么不用纯 LLM 读网页？因为 LLM 上下文窗口有限，需要先提取正文
    """

    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=30.0,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.0"
                )
            },
            follow_redirects=True
        )

    async def fetch(self, url: str) -> Optional[str]:
        """
        获取网页并提取正文
        """
        try:
            resp = await self.client.get(url)
            resp.raise_for_status()
            return self._extract_text(resp.text)
        except Exception as e:
            return f"[获取网页失败: {str(e)}]"

    def _extract_text(self, html: str) -> str:
        """
        基于规则的正文提取（简化版）
        生产环境可替换为：
        - crawl4ai（专为 AI 设计的爬虫库）
        - Jina AI Reader API
        - Mozilla Readability 算法
        """
        soup = BeautifulSoup(html, "html.parser")

        # 移除噪声标签
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
            tag.decompose()

        # 尝试定位主要内容区域
        main = soup.find("main") or soup.find("article") or soup.find("div", class_=re.compile("content|article|post"))
        if main:
            text = main.get_text(separator="\n", strip=True)
        else:
            text = soup.get_text(separator="\n", strip=True)

        # 清理空行和超长行
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        text = "\n".join(lines)

        # 截断防止过长（保留前 8000 字符，约 2000 token）
        return text[:8000] + ("..." if len(text) > 8000 else "")

    async def close(self):
        await self.client.aclose()


class CredibilityScorer:
    """
    可信度评分器（创新点）
    为什么需要这个？Agent 面对多源信息时需要判断哪些更可信
    简单规则版：实际可用 LLM 做更精细的评估
    """

    TRUSTED_DOMAINS = {
        "github.com", "arxiv.org", "wikipedia.org",
        "zh.wikipedia.org", "mp.weixin.qq.com",
        "juejin.cn", "csdn.net", "zhihu.com"
    }

    @classmethod
    def score(cls, url: str, content_length: int) -> float:
        score = 0.5  # 基础分

        # 域名加分
        for domain in cls.TRUSTED_DOMAINS:
            if domain in url:
                score += 0.2
                break

        # HTTPS 加分
        if url.startswith("https://"):
            score += 0.1

        # 内容长度适中加分（太短可能是垃圾页面，太长可能是列表页）
        if 500 <= content_length <= 5000:
            score += 0.1
        elif content_length > 5000:
            score += 0.05

        return min(score, 1.0)
