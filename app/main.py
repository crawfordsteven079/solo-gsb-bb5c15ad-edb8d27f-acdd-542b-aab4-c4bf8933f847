"""FastAPI 入口：考古地层关系核验 HTTP API。"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Query
from sqlalchemy.orm import Session

from . import models, services
from .database import get_session, init_db
from .errors import install_exception_handlers
from .schemas import (
    AssertionOut,
    BatchRequest,
    BatchResponse,
    RelationResponse,
    SiteIn,
    SnapshotIn,
    SnapshotOut,
    StratumIn,
    RELATION_LABELS,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="考古地层关系核验服务",
    version="1.0.0",
    description=(
        "登记遗址地层与「同一期 / 早于」断言，整批提交按修订号乐观并发控制，"
        "自动核验传递推导后的组内早于与早于闭环；支持关系查询与不可变定版快照。"
    ),
    lifespan=lifespan,
)
install_exception_handlers(app)


@app.get("/health", tags=["meta"])
def health(session: Session = Depends(get_session)):
    state = session.get(models.RepoState, 1)
    return {"status": "ok", "revision": state.revision if state else 0}


# ---------- 登记 ----------

@app.post("/api/sites", status_code=201, tags=["登记"])
def register_site(body: SiteIn, session: Session = Depends(get_session)):
    site = services.create_site(session, body.code, body.name)
    session.commit()
    return {"code": site.code, "name": site.name}


@app.post("/api/strata", status_code=201, tags=["登记"])
def register_stratum(body: StratumIn, session: Session = Depends(get_session)):
    stratum = services.create_stratum(session, body.code, body.site_code, body.name)
    session.commit()
    return {"code": stratum.code, "site_code": stratum.site_code, "name": stratum.name}


# ---------- 断言 ----------

@app.post("/api/assertions/batch", response_model=BatchResponse, tags=["断言"], status_code=200)
def submit_batch(body: BatchRequest, session: Session = Depends(get_session)):
    """整批新增 / 撤回断言。必须携带当前修订号；矛盾则整批拒绝，修订号不变。"""
    return services.apply_batch(
        session,
        base_revision=body.base_revision,
        additions=[x.model_dump() for x in body.add],
        withdrawals=list(body.withdraw),
    )


@app.get("/api/assertions", response_model=list[AssertionOut], tags=["断言"])
def list_assertions(
    active_only: bool = Query(True, description="仅返回有效断言；false 含已撤回历史"),
    session: Session = Depends(get_session),
):
    return services.list_assertions(session, active_only)


# ---------- 关系查询 ----------

def _relation_response(result: dict, a: str, b: str) -> RelationResponse:
    return RelationResponse(
        a=a,
        b=b,
        relation=result["relation"],
        relation_label=RELATION_LABELS[result["relation"]],
        evidence_path=result["evidence_path"],
        stratum_path=result["stratum_path"],
        revision=result.get("revision"),
        snapshot_version=result.get("snapshot_version"),
    )


@app.get("/api/relation", response_model=RelationResponse, tags=["查询"])
def query_relation(
    a: str = Query(..., alias="from", description="地层 A 编码"),
    b: str = Query(..., alias="to", description="地层 B 编码"),
    snapshot: str | None = Query(None, description="可选：定版号；省略则查当前状态"),
    session: Session = Depends(get_session),
):
    """返回 A 相对 B 的关系：same / before / after / unknown 及支撑证据路径。"""
    if snapshot:
        result = services.query_snapshot(session, snapshot, a, b)
    else:
        result = services.query_current(session, a, b)
    return _relation_response(result, a, b)


# ---------- 定版快照 ----------

@app.post("/api/snapshots", response_model=SnapshotOut, status_code=201, tags=["定版"])
def freeze_snapshot(body: SnapshotIn, session: Session = Depends(get_session)):
    """保存当前关系的不可变快照。后续撤回不影响旧版结论。"""
    return services.create_snapshot(session, body.version, body.note)


@app.get("/api/snapshots", response_model=list[SnapshotOut], tags=["定版"])
def list_snapshots(session: Session = Depends(get_session)):
    return services.list_snapshots(session)
