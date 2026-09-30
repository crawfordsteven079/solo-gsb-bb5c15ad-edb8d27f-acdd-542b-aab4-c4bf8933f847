"""ORM 模型。

* Site / Stratum：遗址与地层登记（地层编码全局唯一）。
* Assertion：断言历史。evidence_id 永久唯一；撤回仅置 active=False 并记录修订号，
  旧版快照仍可引用其数据。
* RepoState：单行表，保存当前修订号（乐观并发控制）。
* Snapshot：定版快照，含冻结修订号与全部有效断言（JSON），不可变。
"""
from __future__ import annotations

from sqlalchemy import JSON, Boolean, CheckConstraint, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, relationship

from .database import Base

KIND_SAME = "same"
KIND_BEFORE = "before"


class Site(Base):
    __tablename__ = "sites"

    code: Mapped[str] = Column(String(64), primary_key=True)
    name: Mapped[str] = Column(String(256), nullable=False, default="")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    strata: Mapped[list["Stratum"]] = relationship(back_populates="site")


class Stratum(Base):
    __tablename__ = "strata"

    code: Mapped[str] = Column(String(64), primary_key=True)
    site_code: Mapped[str] = Column(String(64), ForeignKey("sites.code", ondelete="RESTRICT"), nullable=False, index=True)
    name: Mapped[str] = Column(String(256), nullable=False, default="")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    site: Mapped[Site] = relationship(back_populates="strata")


class Assertion(Base):
    __tablename__ = "assertions"
    __table_args__ = (
        UniqueConstraint("evidence_id", name="uq_assertions_evidence_id"),
        CheckConstraint("kind IN ('same', 'before')", name="ck_assertions_kind"),
    )

    id: Mapped[int] = Column(Integer, primary_key=True, autoincrement=True)
    evidence_id: Mapped[str] = Column(String(128), nullable=False)
    kind: Mapped[str] = Column(String(16), nullable=False)
    a_code: Mapped[str] = Column(String(64), ForeignKey("strata.code", ondelete="RESTRICT"), nullable=False)
    b_code: Mapped[str] = Column(String(64), ForeignKey("strata.code", ondelete="RESTRICT"), nullable=False)

    active: Mapped[bool] = Column(Boolean, nullable=False, default=True, index=True)
    created_revision: Mapped[int] = Column(Integer, nullable=False)
    withdrawn_revision: Mapped[int | None] = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class RepoState(Base):
    """单行表（id 恒为 1），承载全局修订号。"""

    __tablename__ = "repo_state"

    id: Mapped[int] = Column(Integer, primary_key=True, autoincrement=False)
    revision: Mapped[int] = Column(Integer, nullable=False, default=0)

    @classmethod
    def ensure(cls, session) -> "RepoState":
        state = session.get(cls, 1)
        if state is None:
            state = cls(id=1, revision=0)
            session.add(state)
            session.flush()
        return state


class Snapshot(Base):
    __tablename__ = "snapshots"

    version: Mapped[str] = Column(String(64), primary_key=True)
    revision: Mapped[int] = Column(Integer, nullable=False)
    note: Mapped[str] = Column(String(256), nullable=False, default="")
    # 冻结内容：{"assertions": [{evidence_id, kind, a, b}, ...]}
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
