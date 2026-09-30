"""业务服务层：登记、整批断言提交、关系查询、定版快照。

并发控制
--------
所有写操作在单个事务内先 ``SELECT ... FOR UPDATE`` 锁定 repo_state 单行，
校验 base_revision 后再变更，成功则原子 revision += 1。矛盾时抛出
ContradictionError，事务随请求回滚，原状态不变。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import graph, models
from .errors import (
    ContradictionError,
    CrossSiteError,
    DuplicateEvidenceError,
    InvalidStratumError,
    MissingAssertionError,
    NotFoundError,
    SelfRelationError,
    StaleRevisionError,
)


# ---------- 登记 ----------

def create_site(session: Session, code: str, name: str) -> models.Site:
    existing = session.get(models.Site, code)
    if existing is not None:
        # 登记幂等：同码同名直接返回，同名冲突报错
        if existing.name == name:
            return existing
        raise DuplicateEvidenceError(f"遗址编码 {code} 已存在且名称不一致")
    site = models.Site(code=code, name=name)
    session.add(site)
    session.flush()
    return site


def create_stratum(session: Session, code: str, site_code: str, name: str) -> models.Stratum:
    if session.get(models.Site, site_code) is None:
        raise InvalidStratumError(f"遗址 {site_code} 未登记", {"site_code": site_code})
    existing = session.get(models.Stratum, code)
    if existing is not None:
        if existing.site_code == site_code and existing.name == name:
            return existing
        raise InvalidStratumError(f"地层编码 {code} 已存在")
    stratum = models.Stratum(code=code, site_code=site_code, name=name)
    session.add(stratum)
    session.flush()
    return stratum


# ---------- 断言装载 ----------

def _load_active_assertions(session: Session) -> list[graph.Assertion]:
    rows = session.execute(
        select(models.Assertion).where(models.Assertion.active.is_(True))
    ).scalars().all()
    return [graph.Assertion(r.evidence_id, r.kind, r.a_code, r.b_code) for r in rows]


def _payload_to_assertions(payload: dict) -> list[graph.Assertion]:
    return [
        graph.Assertion(x["evidence_id"], x["kind"], x["a"], x["b"])
        for x in payload.get("assertions", [])
    ]


# ---------- 整批提交 ----------

def apply_batch(
    session: Session,
    base_revision: int,
    additions: list[dict],
    withdrawals: list[str],
) -> dict:
    state = (
        session.query(models.RepoState)
        .with_for_update()
        .filter_by(id=1)
        .one()
    )
    if state.revision != base_revision:
        raise StaleRevisionError(
            f"过期修订号：期望 {state.revision}，收到 {base_revision}",
            {"current_revision": state.revision, "provided_revision": base_revision},
        )

    # 1) 批次内部合法性
    add_ids = [x["evidence_id"] for x in additions]
    if len(set(add_ids)) != len(add_ids):
        dup = sorted({e for e in add_ids if add_ids.count(e) > 1})
        raise DuplicateEvidenceError("本批次内证据编号重复", {"evidence_ids": dup})

    overlap = sorted(set(add_ids) & set(withdrawals))
    if overlap:
        raise DuplicateEvidenceError(
            "同一证据编号在本批次中既新增又撤回", {"evidence_ids": overlap}
        )
    if len(set(withdrawals)) != len(withdrawals):
        raise DuplicateEvidenceError("撤回列表中证据编号重复")

    # 2) 证据编号历史唯一性 + 撤回目标存在且有效
    if add_ids:
        rows = session.execute(
            select(models.Assertion.evidence_id, models.Assertion.active).where(
                models.Assertion.evidence_id.in_(add_ids)
            )
        ).all()
        for evidence_id, active in rows:
            verb = "已存在（有效）" if active else "已撤回（编号永久占用）"
            raise DuplicateEvidenceError(
                f"证据编号 {evidence_id} {verb}", {"evidence_id": evidence_id}
            )

    withdraw_rows: dict[str, models.Assertion] = {}
    if withdrawals:
        found = session.execute(
            select(models.Assertion).where(models.Assertion.evidence_id.in_(withdrawals))
        ).scalars().all()
        found_map = {r.evidence_id: r for r in found}
        for eid in withdrawals:
            row = found_map.get(eid)
            if row is None:
                raise MissingAssertionError(
                    f"证据编号 {eid} 不存在，无法撤回", {"evidence_id": eid}
                )
            if not row.active:
                raise MissingAssertionError(
                    f"证据编号 {eid} 的断言已撤回", {"evidence_id": eid}
                )
            withdraw_rows[eid] = row

    # 3) 地层存在性、自关联、同遗址约束
    strata_cache: dict[str, models.Stratum] = {}

    def _stratum(code: str) -> models.Stratum:
        if code not in strata_cache:
            obj = session.get(models.Stratum, code)
            if obj is None:
                raise InvalidStratumError(f"地层 {code} 未登记", {"stratum_code": code})
            strata_cache[code] = obj
        return strata_cache[code]

    site_of: dict[str, str] = {}
    for item in additions:
        a, b = _stratum(item["a"]), _stratum(item["b"])
        site_of[a.code] = a.site_code
        site_of[b.code] = b.site_code
        if a.code == b.code:
            raise SelfRelationError(
                "断言的两个地层不能相同", {"stratum_code": a.code, "kind": item["kind"]}
            )
        if a.site_code != b.site_code:
            raise CrossSiteError(
                f"地层 {a.code}（遗址 {a.site_code}）与 {b.code}（遗址 {b.site_code}）"
                "分属不同遗址，不能登记断言",
                {"a": a.code, "b": b.code, "sites": [a.site_code, b.site_code]},
            )

    # 4) 应用变更到事务内状态（尚未提交，失败即整体回滚）
    new_revision = state.revision + 1
    for item in additions:
        session.add(
            models.Assertion(
                evidence_id=item["evidence_id"],
                kind=item["kind"],
                a_code=item["a"],
                b_code=item["b"],
                active=True,
                created_revision=new_revision,
            )
        )
    for eid in withdrawals:
        row = withdraw_rows[eid]
        row.active = False
        row.withdrawn_revision = new_revision

    # 5) 按整批最终关系核验
    session.flush()
    final_assertions = _load_active_assertions(session)
    conflict = graph.find_contradiction(final_assertions)
    if conflict is not None:
        raise ContradictionError(
            conflict["message"],
            {
                "conflict_type": conflict["type"],
                "evidence_path": conflict["evidence_path"],
                "stratum_path": conflict["stratum_path"],
                **({"class_path": conflict["class_path"]} if "class_path" in conflict else {}),
            },
        )

    state.revision = new_revision
    session.commit()
    return {
        "revision": new_revision,
        "added": sorted(add_ids),
        "withdrawn": sorted(withdrawals),
        "assertion_count": len(final_assertions),
    }


# ---------- 查询 ----------

def _check_query_strata(session: Session, a: str, b: str) -> None:
    if a == b:
        raise SelfRelationError("不能查询同一地层与其自身的关系", {"stratum_code": a})
    for code in (a, b):
        if session.get(models.Stratum, code) is None:
            raise InvalidStratumError(f"地层 {code} 未登记", {"stratum_code": code})


def query_current(session: Session, a: str, b: str) -> dict:
    _check_query_strata(session, a, b)
    state = session.get(models.RepoState, 1)
    result = graph.query_relation(_load_active_assertions(session), a, b)
    result.update({"revision": state.revision, "snapshot_version": None})
    return result


def query_snapshot(session: Session, version: str, a: str, b: str) -> dict:
    if a == b:
        raise SelfRelationError("不能查询同一地层与其自身的关系", {"stratum_code": a})
    snap = session.get(models.Snapshot, version)
    if snap is None:
        raise NotFoundError(f"定版 {version} 不存在", {"snapshot_version": version})
    known = _all_snapshot_strata(snap)
    for code in (a, b):
        if code not in known:
            raise InvalidStratumError(
                f"地层 {code} 不在定版 {version} 的关系数据中",
                {"stratum_code": code, "snapshot_version": version},
            )
    result = graph.query_relation(_payload_to_assertions(snap.payload), a, b)
    result.update({"revision": snap.revision, "snapshot_version": snap.version})
    return result


def _all_snapshot_strata(snap: models.Snapshot) -> set[str]:
    out = set()
    for x in snap.payload.get("assertions", []):
        out.add(x["a"])
        out.add(x["b"])
    return out


# ---------- 定版快照 ----------

def create_snapshot(session: Session, version: str, note: str) -> dict:
    state = (
        session.query(models.RepoState)
        .with_for_update()
        .filter_by(id=1)
        .one()
    )
    if session.get(models.Snapshot, version) is not None:
        raise DuplicateEvidenceError(f"定版号 {version} 已存在", {"version": version})

    # 快照只允许在当前一致状态下定版
    conflict = graph.find_contradiction(_load_active_assertions(session))
    if conflict is not None:
        raise ContradictionError(
            "当前关系存在矛盾，不能定版",
            {
                "conflict_type": conflict["type"],
                "evidence_path": conflict["evidence_path"],
                "stratum_path": conflict["stratum_path"],
            },
        )

    payload = {
        "assertions": [
            {"evidence_id": x.evidence_id, "kind": x.kind, "a": x.a, "b": x.b}
            for x in _load_active_assertions(session)
        ]
    }
    snap = models.Snapshot(version=version, revision=state.revision, note=note, payload=payload)
    session.add(snap)
    session.commit()
    return {
        "version": version,
        "revision": state.revision,
        "note": note,
        "assertion_count": len(payload["assertions"]),
    }


def list_snapshots(session: Session) -> list[dict]:
    rows = session.execute(select(models.Snapshot).order_by(models.Snapshot.version)).scalars().all()
    return [
        {
            "version": r.version,
            "revision": r.revision,
            "note": r.note,
            "assertion_count": len(r.payload.get("assertions", [])),
        }
        for r in rows
    ]


def list_assertions(session: Session, active_only: bool) -> list[dict]:
    stmt = select(models.Assertion).order_by(models.Assertion.evidence_id)
    if active_only:
        stmt = stmt.where(models.Assertion.active.is_(True))
    rows = session.execute(stmt).scalars().all()
    return [
        {
            "evidence_id": r.evidence_id,
            "kind": r.kind,
            "a": r.a_code,
            "b": r.b_code,
            "active": r.active,
            "created_revision": r.created_revision,
            "withdrawn_revision": r.withdrawn_revision,
        }
        for r in rows
    ]
