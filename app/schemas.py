"""请求 / 响应 Pydantic 模型。"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Kind = Literal["same", "before"]
Relation = Literal["same", "before", "after", "unknown"]


# ---------- 登记 ----------

class SiteIn(BaseModel):
    code: str = Field(..., min_length=1, max_length=64, description="遗址编码，唯一")
    name: str = Field("", max_length=256)


class StratumIn(BaseModel):
    code: str = Field(..., min_length=1, max_length=64, description="地层编码，全局唯一")
    site_code: str = Field(..., min_length=1, max_length=64)
    name: str = Field("", max_length=256)


# ---------- 断言批处理 ----------

class AssertionItem(BaseModel):
    evidence_id: str = Field(..., min_length=1, max_length=128, description="唯一证据编号")
    kind: Kind
    a: str = Field(..., min_length=1, max_length=64, description="地层 A 编码")
    b: str = Field(..., min_length=1, max_length=64, description="地层 B 编码")


class BatchRequest(BaseModel):
    base_revision: int = Field(..., ge=0, description="调用方认为的当前修订号（乐观锁）")
    add: list[AssertionItem] = Field(default_factory=list)
    withdraw: list[str] = Field(default_factory=list, description="待撤回断言的证据编号")


class BatchResponse(BaseModel):
    revision: int
    added: list[str]
    withdrawn: list[str]
    assertion_count: int


# ---------- 查询 ----------

class RelationResponse(BaseModel):
    a: str
    b: str
    relation: Relation
    relation_label: str
    evidence_path: list[str]
    stratum_path: list[str]
    revision: Optional[int] = None
    snapshot_version: Optional[str] = None


class AssertionOut(BaseModel):
    evidence_id: str
    kind: Kind
    a: str
    b: str
    active: bool
    created_revision: int
    withdrawn_revision: Optional[int] = None


# ---------- 快照 ----------

class SnapshotIn(BaseModel):
    version: str = Field(..., min_length=1, max_length=64, description="定版号，唯一")
    note: str = Field("", max_length=256)


class SnapshotOut(BaseModel):
    version: str
    revision: int
    note: str
    assertion_count: int


RELATION_LABELS = {
    "same": "同一期",
    "before": "早于",
    "after": "晚于",
    "unknown": "未定",
}
