"""
项目配置管理
使用 pydantic-settings 从环境变量读取配置，避免硬编码敏感信息
"""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # LLM API 配置（支持 Moonshot/智谱/OpenAI 兼容接口）
    LLM_API_KEY: str = "your-api-key-here"
    LLM_BASE_URL: str = "https://api.moonshot.cn/v1"  # Moonshot Kimi
    LLM_MODEL: str = "moonshot-v1-32k"

    # 搜索工具配置
    TAVILY_API_KEY: str = ""  # 可选，用于高质量搜索
    SEARCH_MAX_RESULTS: int = 5

    # Redis 配置（用于 Celery 和缓存）
    REDIS_URL: str = "redis://localhost:6379/0"

    # 应用配置
    APP_NAME: str = "DeepResearchAgent"
    DEBUG: bool = True

    class Config:
        env_file = ".env.example"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    """
    使用 lru_cache 避免重复读取配置文件，提升性能
    这是 FastAPI 依赖注入的标准做法
    """
    return Settings()
