"""HTTP API 集成测试：登记、整批提交、并发修订号、矛盾拒绝、查询、快照。"""
from tests.conftest import batch, register_site, register_strata, rev


# ---------- 登记 ----------

def test_register_site_and_strata(client):
    r = register_site(client, "S9", "测试遗址")
    assert r.status_code == 201
    r = client.post("/api/strata", json={"code": "Z1", "site_code": "S9"})
    assert r.status_code == 201


def test_stratum_unknown_site(client):
    register_site(client, "SA")
    r = client.post("/api/strata", json={"code": "X1", "site_code": "NOPE"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_stratum"


def test_self_relation_rejected(client):
    register_strata(client, "SB", ("Q1",))
    r = batch(client, rev(client), add=[{"evidence_id": "t-self", "kind": "same", "a": "Q1", "b": "Q1"}])
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "self_relation"


def test_cross_site_rejected(client):
    register_site(client, "SX1", "遗址一")
    register_site(client, "SX2", "遗址二")
    client.post("/api/strata", json={"code": "K1", "site_code": "SX1"})
    client.post("/api/strata", json={"code": "K2", "site_code": "SX2"})
    r = batch(client, rev(client), add=[{"evidence_id": "t-cross", "kind": "before", "a": "K1", "b": "K2"}])
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "cross_site_relation"


# ---------- 整批提交与修订号 ----------

def test_batch_happy_path_and_revision(client):
    register_strata(client, "S1", ("L1", "L2", "L3"))
    r0 = rev(client)
    r = batch(client, r0, add=[
        {"evidence_id": "e1", "kind": "same", "a": "L1", "b": "L2"},
        {"evidence_id": "e2", "kind": "before", "a": "L2", "b": "L3"},
    ])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["revision"] == r0 + 1
    assert body["added"] == ["e1", "e2"]
    assert body["assertion_count"] == 2
    assert rev(client) == r0 + 1


def test_stale_revision_rejected(client):
    register_strata(client, "S2", ("M1", "M2"))
    cur = rev(client)
    r = batch(client, cur - 1, add=[{"evidence_id": "stale1", "kind": "same", "a": "M1", "b": "M2"}])
    assert r.status_code == 409
    body = r.json()["error"]
    assert body["code"] == "stale_revision"
    assert body["details"]["current_revision"] == cur
    # 状态不变
    assert rev(client) == cur


def test_duplicate_evidence_in_batch(client):
    register_strata(client, "S3", ("N1", "N2", "N3"))
    cur = rev(client)
    r = batch(client, cur, add=[
        {"evidence_id": "dup", "kind": "same", "a": "N1", "b": "N2"},
        {"evidence_id": "dup", "kind": "before", "a": "N2", "b": "N3"},
    ])
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "duplicate_evidence"
    assert rev(client) == cur


def test_duplicate_evidence_across_batches_even_withdrawn(client):
    register_strata(client, "S4", ("O1", "O2"))
    cur = rev(client)
    assert batch(client, cur, add=[{"evidence_id": "ev1", "kind": "same", "a": "O1", "b": "O2"}]).status_code == 200
    cur = rev(client)
    # 撤回后编号仍永久占用
    assert batch(client, cur, withdraw=["ev1"]).status_code == 200
    cur = rev(client)
    r = batch(client, cur, add=[{"evidence_id": "ev1", "kind": "same", "a": "O1", "b": "O2"}])
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "duplicate_evidence"


def test_withdraw_missing_assertion(client):
    register_strata(client, "S5", ("P1", "P2"))
    cur = rev(client)
    r = batch(client, cur, withdraw=["ghost"])
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "assertion_not_found"
    assert rev(client) == cur


def test_invalid_stratum_in_assertion(client):
    register_strata(client, "S6", ("R1",))
    r = batch(client, rev(client), add=[{"evidence_id": "iv1", "kind": "before", "a": "R1", "b": "R404"}])
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_stratum"


# ---------- 矛盾整批拒绝 ----------

def test_contradiction_intra_group_whole_batch_rejected(client):
    register_strata(client, "S7", ("T1", "T2"))
    cur = rev(client)
    r = batch(client, cur, add=[
        {"evidence_id": "c1", "kind": "same", "a": "T1", "b": "T2"},
        {"evidence_id": "c2", "kind": "before", "a": "T1", "b": "T2"},
    ])
    assert r.status_code == 409
    body = r.json()["error"]
    assert body["code"] == "contradiction"
    assert body["details"]["conflict_type"] == "intra_group"
    assert set(body["details"]["evidence_path"]) == {"c1", "c2"}
    # 整批拒绝：修订号与断言状态都不变
    assert rev(client) == cur
    listing = client.get("/api/assertions").json()
    assert all(x["evidence_id"] not in ("c1", "c2") for x in listing)


def test_contradiction_cycle_with_path(client):
    register_strata(client, "S8", ("U1", "U2", "U3"))
    cur = rev(client)
    # 先放两条形成链
    r = batch(client, cur, add=[
        {"evidence_id": "u1", "kind": "before", "a": "U1", "b": "U2"},
        {"evidence_id": "u2", "kind": "before", "a": "U2", "b": "U3"},
    ])
    assert r.status_code == 200
    cur = rev(client)
    # 第三条闭环，整批拒绝
    r = batch(client, cur, add=[{"evidence_id": "u3", "kind": "before", "a": "U3", "b": "U1"}])
    assert r.status_code == 409
    details = r.json()["error"]["details"]
    assert details["conflict_type"] == "cycle"
    assert set(details["evidence_path"]) == {"u1", "u2", "u3"}
    assert rev(client) == cur
    # 旧断言仍可查询：U1 早于 U3
    q = client.get("/api/relation", params={"from": "U1", "to": "U3"}).json()
    assert q["relation"] == "before"
    assert q["evidence_path"] == ["u1", "u2"]


# ---------- 查询 ----------

def test_relation_same_before_after_unknown(client):
    register_strata(client, "SQ", ("V1", "V2", "V3", "V4"))
    cur = rev(client)
    batch(client, cur, add=[
        {"evidence_id": "v1", "kind": "same", "a": "V1", "b": "V2"},
        {"evidence_id": "v2", "kind": "before", "a": "V2", "b": "V3"},
    ])
    assert client.get("/api/relation", params={"from": "V1", "to": "V2"}).json()["relation"] == "same"
    after = client.get("/api/relation", params={"from": "V3", "to": "V1"}).json()
    assert after["relation"] == "after"
    assert after["relation_label"] == "晚于"
    before = client.get("/api/relation", params={"from": "V1", "to": "V3"}).json()
    assert before["relation"] == "before"
    assert before["evidence_path"] == ["v1", "v2"]
    unknown = client.get("/api/relation", params={"from": "V1", "to": "V4"}).json()
    assert unknown["relation"] == "unknown"
    assert unknown["evidence_path"] == []


def test_relation_invalid_stratum(client):
    register_strata(client, "SR", ("W1",))
    r = client.get("/api/relation", params={"from": "W1", "to": "MISSING"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "invalid_stratum"


# ---------- 撤回与传递 ----------

def test_withdraw_changes_derived_relation(client):
    register_strata(client, "SW", ("X1", "X2", "X3"))
    cur = rev(client)
    batch(client, cur, add=[
        {"evidence_id": "x1", "kind": "same", "a": "X1", "b": "X2"},
        {"evidence_id": "x2", "kind": "before", "a": "X2", "b": "X3"},
    ])
    assert client.get("/api/relation", params={"from": "X1", "to": "X3"}).json()["relation"] == "before"
    cur = rev(client)
    assert batch(client, cur, withdraw=["x2"]).status_code == 200
    q = client.get("/api/relation", params={"from": "X1", "to": "X3"}).json()
    assert q["relation"] == "unknown"


# ---------- 定版快照不可变 ----------

def test_snapshot_immutable(client):
    register_strata(client, "SF", ("Y1", "Y2", "Y3"))
    cur = rev(client)
    batch(client, cur, add=[
        {"evidence_id": "y1", "kind": "before", "a": "Y1", "b": "Y2"},
        {"evidence_id": "y2", "kind": "before", "a": "Y2", "b": "Y3"},
    ])
    frozen_rev = rev(client)
    r = client.post("/api/snapshots", json={"version": "v2024-final", "note": "结稿"})
    assert r.status_code == 201
    assert r.json()["revision"] == frozen_rev

    # 旧版结论：Y1 早于 Y3
    old = client.get(
        "/api/relation", params={"from": "Y1", "to": "Y3", "snapshot": "v2024-final"}
    ).json()
    assert old["relation"] == "before"
    assert old["snapshot_version"] == "v2024-final"
    assert old["revision"] == frozen_rev

    # 后续撤回改变当前态
    cur = rev(client)
    assert batch(client, cur, withdraw=["y2"]).status_code == 200
    assert client.get("/api/relation", params={"from": "Y1", "to": "Y3"}).json()["relation"] == "unknown"

    # 旧版结论不变
    old2 = client.get(
        "/api/relation", params={"from": "Y1", "to": "Y3", "snapshot": "v2024-final"}
    ).json()
    assert old2["relation"] == "before"
    assert old2["evidence_path"] == ["y1", "y2"]

    # 定版号唯一
    r = client.post("/api/snapshots", json={"version": "v2024-final"})
    assert r.status_code == 422

    # 列表
    versions = [x["version"] for x in client.get("/api/snapshots").json()]
    assert "v2024-final" in versions


def test_mixed_add_and_withdraw_single_batch(client):
    register_strata(client, "SM", ("G1", "G2", "G3"))
    cur = rev(client)
    batch(client, cur, add=[{"evidence_id": "g1", "kind": "before", "a": "G1", "b": "G2"}])
    cur = rev(client)
    # 同一批撤回旧断言并新增断言
    r = batch(client, cur, add=[{"evidence_id": "g2", "kind": "before", "a": "G2", "b": "G3"}], withdraw=["g1"])
    assert r.status_code == 200
    body = r.json()
    assert body["added"] == ["g2"]
    assert body["withdrawn"] == ["g1"]
    assert client.get("/api/relation", params={"from": "G1", "to": "G3"}).json()["relation"] == "unknown"
    assert client.get("/api/relation", params={"from": "G2", "to": "G3"}).json()["relation"] == "before"
