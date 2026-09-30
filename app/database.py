"""数据库引擎、会话工厂与建表初始化。"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    future=True,
    connect_args=_connect_args,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    """幂等建表，并确保修订号单行存在。"""
    from . import models  # noqa: F401  确保模型已注册

    Base.metadata.create_all(bind=engine)
    with SessionLocal() as session:
        models.RepoState.ensure(session)
        session.commit()


def get_session():
    """FastAPI 依赖：每请求一个会话。"""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
