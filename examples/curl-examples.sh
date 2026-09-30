#!/bin/sh
# 考古地层关系核验服务 —— curl 调用速查（服务启动后执行：sh examples/curl-examples.sh）
set -e
BASE=${BASE_URL:-http://localhost:8000}

echo "== 健康检查 / 当前修订号 =="
curl -s "$BASE/health"; echo

echo "== 登记遗址 =="
curl -s -X POST "$BASE/api/sites" -H 'Content-Type: application/json' \
  -d '{"code":"YZS","name":"某遗址"}'; echo

echo "== 登记地层 =="
for c in L1 L2 L3 L4; do
  curl -s -X POST "$BASE/api/strata" -H 'Content-Type: application/json' \
    -d "{\"code\":\"$c\",\"site_code\":\"YZS\",\"name\":\"地层$c\"}"; echo
done

echo "== 整批新增断言（注意替换 base_revision 为 /health 返回值）=="
curl -s -X POST "$BASE/api/assertions/batch" -H 'Content-Type: application/json' -d '{
  "base_revision": 0,
  "add": [
    {"evidence_id":"EV-001","kind":"same",  "a":"L1","b":"L2"},
    {"evidence_id":"EV-002","kind":"before","a":"L2","b":"L3"},
    {"evidence_id":"EV-003","kind":"same",  "a":"L3","b":"L4"}
  ],
  "withdraw": []
}'; echo

echo "== 查询 L1 相对 L3（推导：早于，证据路径 EV-001, EV-002）=="
curl -s "$BASE/api/relation?from=L1&to=L3"; echo

echo "== 查询 L4 相对 L1（晚于）=="
curl -s "$BASE/api/relation?from=L4&to=L1"; echo

echo "== 定版快照 =="
curl -s -X POST "$BASE/api/snapshots" -H 'Content-Type: application/json' \
  -d '{"version":"v2024-final","note":"结稿"}'; echo

echo "== 矛盾批（L3 早于 L1 形成闭环）→ 409，整批拒绝 =="
curl -s -i -X POST "$BASE/api/assertions/batch" -H 'Content-Type: application/json' -d '{
  "base_revision": 1,
  "add": [{"evidence_id":"EV-BAD","kind":"before","a":"L3","b":"L1"}],
  "withdraw": []
}' | head -20

echo "== 撤回断言（携当前修订号）=="
curl -s -X POST "$BASE/api/assertions/batch" -H 'Content-Type: application/json' -d '{
  "base_revision": 1,
  "add": [],
  "withdraw": ["EV-002"]
}'; echo

echo "== 查询定版旧结论（不受撤回影响）=="
curl -s "$BASE/api/relation?from=L1&to=L3&snapshot=v2024-final"; echo
