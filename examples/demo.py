#!/usr/bin/env python3
"""考古地层关系核验服务 —— 调用示例（标准库实现，无第三方依赖）。

用法：
    python examples/demo.py            # 默认 http://localhost:8000
    BASE_URL=http://host:port python examples/demo.py

演示流程：登记遗址/地层 → 整批新增断言 → 关系查询 →
整批撤回/新增（含修订号）→ 制造矛盾被整批拒绝 → 定版快照 → 撤回后旧版不变。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")


def call(method: str, path: str, body: dict | None = None, params: dict | None = None):
    url = BASE_URL + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def show(title: str, status: int, payload):
    print(f"\n### {title}\nHTTP {status}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def get_revision() -> int:
    _, body = call("GET", "/health")
    return body["revision"]


def relation(a: str, b: str, snapshot: str | None = None):
    params = {"from": a, "to": b}
    if snapshot:
        params["snapshot"] = snapshot
    status, body = call("GET", "/api/relation", params=params)
    show(f"查询 {a} 相对 {b}" + (f"（定版 {snapshot}）" if snapshot else "（当前态）"), status, body)
    return body


def batch(add=None, withdraw=None, base=None):
    if base is None:
        base = get_revision()
    payload = {"base_revision": base, "add": add or [], "withdraw": withdraw or []}
    status, body = call("POST", "/api/assertions/batch", payload)
    show(f"整批提交（base_revision={base}, +{len(add or [])} -{len(withdraw or [])}）", status, body)
    return status, body


def main() -> int:
    # 1. 登记遗址与地层（随机后缀保证每次运行都是干净场景，可重复执行）
    import uuid

    suffix = os.environ.get("DEMO_SUFFIX", "") or uuid.uuid4().hex[:6]
    site = f"YZS-{suffix}"          # 遗址：示例遗址
    strata = [f"{s}-{suffix}" for s in ("L1", "L2", "L3", "L4")]

    call("POST", "/api/sites", {"code": site, "name": "示例遗址"})
    for code in strata:
        status, body = call("POST", "/api/strata", {"code": code, "site_code": site, "name": f"地层{code}"})
        if status not in (201,):
            print(f"地层 {code} 已存在，继续演示（{body.get('error', {}).get('message')}）")

    # 2. 整批新增：L1 同一期 L2；L2 早于 L3；L3 同一期 L4
    #    推导：L1 早于 L3、L1 早于 L4、L2 早于 L4
    batch(add=[
        {"evidence_id": f"EV-001{suffix}", "kind": "same",   "a": strata[0], "b": strata[1]},
        {"evidence_id": f"EV-002{suffix}", "kind": "before", "a": strata[1], "b": strata[2]},
        {"evidence_id": f"EV-003{suffix}", "kind": "same",   "a": strata[2], "b": strata[3]},
    ])

    # 3. 关系查询（含推导出的关系与证据路径）
    relation(strata[0], strata[2])   # L1 早于 L3，路径 EV-001 → EV-002
    relation(strata[3], strata[0])   # L4 晚于 L1
    relation(strata[0], strata[1])   # L1 同一期 L2

    # 4. 定版快照（后续任何撤回都不会改动该版结论）
    version = f"demo-final{suffix}"
    status, body = call("POST", "/api/snapshots", {"version": version, "note": "示例结稿定版"})
    show(f"定版 {version}", status, body)

    # 5. 故意提交矛盾：L3 早于 L1 —— 与已有关系闭环，整批拒绝
    status, body = batch(add=[
        {"evidence_id": f"EV-BAD{suffix}", "kind": "before", "a": strata[2], "b": strata[0]},
    ])
    assert status == 409 and body["error"]["code"] == "contradiction"
    print(">> 矛盾批被拒绝，冲突证据路径：", body["error"]["details"]["evidence_path"])

    # 6. 过期修订号提交同样被拒（当前修订号未因上面的拒绝而变化）
    stale = get_revision() - 1
    status, body = batch(base=stale, add=[])
    assert status == 409 and body["error"]["code"] == "stale_revision"
    print(">> 过期修订号被拒绝：", body["error"]["message"])

    # 7. 撤回 EV-002（L2 早于 L3），当前态变为未定
    status, body = batch(withdraw=[f"EV-002{suffix}"])
    assert status == 200
    relation(strata[0], strata[2])  # unknown
    relation(strata[0], strata[2], snapshot=version)  # 旧版仍为 before，结论不可变

    # 8. 其他错误示例
    status, body = batch(add=[
        {"evidence_id": f"EV-X{suffix}", "kind": "before", "a": strata[0], "b": "GHOST"},
    ])
    show("无效地层", status, body)
    status, body = batch(withdraw=[f"NOT-EXIST{suffix}"])
    show("撤回不存在的断言", status, body)

    print("\n演示完成。交互式文档见 %s/docs" % BASE_URL)
    return 0


if __name__ == "__main__":
    sys.exit(main())
