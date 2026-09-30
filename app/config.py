"""应用配置：全部来自环境变量，见 README「配置」一节。"""
from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 数据库。默认值供容器外本地运行；容器中由 compose 注入。
    # 测试时可将 DATABASE_URL 指向 sqlite（如 sqlite:///./test.db）。
    database_url: str = "postgresql+psycopg2://strata:strata@localhost:5432/strata"
    # 0.0.0.0 便于容器内监听
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"


settings = Settings()
