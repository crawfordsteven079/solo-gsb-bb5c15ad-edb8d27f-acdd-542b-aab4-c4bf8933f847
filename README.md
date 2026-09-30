# 考古地层关系核验服务（Strata Relation Service）

用 **Python + FastAPI + PostgreSQL** 实现的考古地层关系核验 HTTP 服务：
登记遗址与地层、登记带唯一证据编号的「同一期 / 早于」断言，自动核验传递推导后的
关系一致性，支持按证据路径查询两地层关系，并可保存**不可变**的定版快照。

## 一、核心业务规则

| 规则 | 说明 |
| --- | --- |
| 同一期（`same`） | 无向、可传递：`A same B` ⇒ `A 与 B 同期`、`B same A` |
| 早于（`before`） | 有向：`A before B` 表示 A 早于 B；推导路径可沿「早于」边和「同一期」边混合传播 |
| 晚于（`after`） | 查询方向上的派生结论：`B before A` ⇒ 对查询 `A vs B` 返回 `after`（晚于） |
| 未定（`unknown`） | 之间不存在任何同/早于路径 |
| 矛盾一：组内早于 | 同一「同一期」等价组内出现 `before`（含地层自己早于自己） |
| 矛盾二：早于闭环 | 把同一期等价组收缩为节点后，`before` 边形成有向环 |
| 整批提交 | 一批新增 + 撤回必须携带**当前修订号** `base_revision`；按**整批最终关系**核验 |
| 原子性 | 矛盾、过期修订号、无效地层、重复证据编号、撤回不存在 → **整批拒绝，原状态不变**；成功才把修订号原子 `+1` |
| 证据编号 | 全局唯一、**永久占用**：断言撤回后编号也不可再次登记 |
| 路径择优 | 支撑路径先取**证据数最少**；并列时取证据编号元组**字典序最小** |
| 定版快照 | 保存当时全部关系的不可变快照；之后任何撤回/新增都**不影响旧版结论** |

冲突响应中给出两条可追溯的路径：

* `evidence_path`：冲突证据链（证据编号，有序）
* `stratum_path`：冲突经过的地层链；`cycle` 类型另附等价类链 `class_path`

## 二、一键启动（Docker Compose）

```bash
cp .env.example .env      # 可按需修改账号、端口
docker compose up --build
```

启动后：

* **API 地址**：`http://localhost:8000`
* **Swagger 交互文档**：<http://localhost:8000/docs>
* **ReDoc**：<http://localhost:8000/redoc>
* **健康检查**：<http://localhost:8000/health>（返回当前修订号）
* PostgreSQL：宿主机默认 `localhost:5432`（见配置改端口）

API 容器会等待数据库健康、自动完成建表初始化（幂等），随后启动 uvicorn，
无需手工执行迁移脚本。

停止与清理：

```bash
docker compose down          # 停止
docker compose down -v       # 停止并删除数据库卷（清空数据）
```

## 三、配置（环境变量）

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+psycopg2://strata:strata@db:5432/strata` | 数据库连接串（SQLAlchemy 形式，容器内指向 `db`） |
| `HOST` | `0.0.0.0` | API 监听地址 |
| `PORT` | `8000` | API 监听端口（容器内） |
| `LOG_LEVEL` | `info` | uvicorn 日志级别 |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `strata` / `strata` / `strata` | 数据库账号与库名 |
| `HOST_API_PORT` | `8000` | 映射到宿主机的 API 端口 |
| `HOST_DB_PORT` | `5432` | 映射到宿主机的数据库端口 |

例：本机 5432/8000 被占用时：

```bash
HOST_API_PORT=18000 HOST_DB_PORT=15432 docker compose up --build
```

### 不用 Docker 的本地运行

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL='postgresql+psycopg2://strata:strata@localhost:5432/strata'
uvicorn app.main:app --host 0.0.0.0 --port 8000   # 启动即自动建表
```

## 四、API 一览

基址 `http://localhost:8000`，所有请求/响应均为 JSON。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/health` | 健康检查与当前修订号 |
| POST | `/api/sites` | 登记遗址 |
| POST | `/api/strata` | 登记地层（需先登记遗址） |
| POST | `/api/assertions/batch` | **整批**新增 / 撤回断言（乐观锁 + 一致性核验） |
| GET | `/api/assertions?active_only=true` | 列出断言（`false` 含已撤回历史） |
| GET | `/api/relation?from=L1&to=L3[&snapshot=v1]` | 查询关系与证据路径（可查定版） |
| POST | `/api/snapshots` | 保存不可变定版快照 |
| GET | `/api/snapshots` | 定版列表 |

### 1. 登记

```bash
curl -s -X POST http://localhost:8000/api/sites \
  -H 'Content-Type: application/json' \
  -d '{"code":"YZS","name":"某遗址"}'

curl -s -X POST http://localhost:8000/api/strata \
  -H 'Content-Type: application/json' \
  -d '{"code":"L1","site_code":"YZS","name":"下层"}'
```

### 2. 整批新增断言

```bash
curl -s -X POST http://localhost:8000/api/assertions/batch \
  -H 'Content-Type: application/json' -d '{
    "base_revision": 0,
    "add": [
      {"evidence_id":"EV-001","kind":"same",  "a":"L1","b":"L2"},
      {"evidence_id":"EV-002","kind":"before","a":"L2","b":"L3"},
      {"evidence_id":"EV-003","kind":"same",  "a":"L3","b":"L4"}
    ],
    "withdraw": []
  }'
```

响应（修订号原子递增）：

```json
{"revision": 1, "added": ["EV-001", "EV-002", "EV-003"], "withdrawn": [], "assertion_count": 3}
```

同一批中可以同时 `add` 与 `withdraw`（例如修正旧证据），按最终状态统一核验。

### 3. 关系查询

```bash
curl -s 'http://localhost:8000/api/relation?from=L1&to=L3'
```

```json
{
  "a": "L1", "b": "L3",
  "relation": "before",
  "relation_label": "早于",
  "evidence_path": ["EV-001", "EV-002"],
  "stratum_path": ["L1", "L2", "L3"],
  "revision": 1,
  "snapshot_version": null
}
```

`relation` 取值：`same`（同一期）、`before`（早于）、`after`（晚于）、`unknown`（未定）。

### 4. 矛盾批被整批拒绝（含冲突路径）

```bash
curl -s -X POST http://localhost:8000/api/assertions/batch \
  -H 'Content-Type: application/json' -d '{
    "base_revision": 1,
    "add": [{"evidence_id":"EV-BAD","kind":"before","a":"L3","b":"L1"}],
    "withdraw": []
  }'
```

```json
{
  "error": {
    "code": "contradiction",
    "message": "早于闭环：等价类 L1 -> L3 -> L1，证据链 ['EV-002', 'EV-BAD', 'EV-001']",
    "details": {
      "conflict_type": "cycle",
      "evidence_path": ["EV-002", "EV-BAD", "EV-001"],
      "stratum_path": ["L2", "L3", "L1", "L2"],
      "class_path": ["L1", "L3", "L1"]
    }
  }
}
```

HTTP 409，**修订号与关系均保持提交前状态**。冲突在等价类（L1 与 L2 同组）层面
成环：`L1(类) ─EV-002→ L3(类) ─EV-BAD→ L1(类)`。组内早于的例子则返回
`"conflict_type": "intra_group"`。

### 5. 撤回（携当前修订号）

```bash
curl -s -X POST http://localhost:8000/api/assertions/batch \
  -H 'Content-Type: application/json' -d '{
    "base_revision": 1, "add": [], "withdraw": ["EV-002"]
  }'
```

### 6. 定版与旧版查询

```bash
curl -s -X POST http://localhost:8000/api/snapshots \
  -H 'Content-Type: application/json' \
  -d '{"version":"v2024-final","note":"结稿"}'

# 无论当前态如何变化，旧版结论不变
curl -s 'http://localhost:8000/api/relation?from=L1&to=L3&snapshot=v2024-final'
```

### 运行调用示例

```bash
# Python 版（仅需标准库）
python examples/demo.py
# 或 curl 版
sh examples/curl-examples.sh
```

## 五、错误码

统一错误体：`{"error": {"code": "...", "message": "...", "details": {...}}}`

| HTTP | code | 触发场景 |
| --- | --- | --- |
| 422 | `invalid_stratum` | 断言/查询引用了未登记地层；地层登记到不存在的遗址；查询定版中不存在的地层 |
| 422 | `self_relation` | 断言两地层相同，或查询同一地层自身 |
| 422 | `cross_site_relation` | 断言跨遗址连接两地层 |
| 422 | `duplicate_evidence` | 证据编号在批次内重复、与历史（含已撤回）冲突、同批既增又撤；定版号/遗址编码重复 |
| 404 | `assertion_not_found` | 撤回了不存在或已撤回的断言 |
| 409 | `stale_revision` | `base_revision` 不等于服务端当前修订号（`details.current_revision` 给出现值） |
| 409 | `contradiction` | 整批最终关系存在组内早于或早于闭环（`details` 含证据路径） |
| 404 | `not_found` | 查询不存在的定版号 |

## 六、并发与一致性说明

* 写事务以 `SELECT ... FOR UPDATE` 锁定单行修订记录（`repo_state`），提交期间串行化；
  并发提交中只有一个能以给定修订号成功，其余收到 `409 stale_revision`，调用方取
  `/health` 或错误体中的 `current_revision` 后重试。
* 每个批次在同一事务内完成：校验 → 写入 → 对**最终有效断言集**重算图核验 →
  修订号递增 → 提交。任何一步失败整体 `ROLLBACK`。
* 快照为自包含 JSON（当时的全部有效断言 + 冻结修订号），不随后续写操作变化。

## 七、测试

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

测试用 SQLite 驱动同一条 SQLAlchemy/FastAPI 代码路径（30 个用例），覆盖：
传递推导、两类矛盾及冲突路径、路径择优（最少边数 + 字典序）、乐观修订号、
整批拒绝回滚、撤回派生变化、快照不可变、全部错误码。另含随机图对照穷举脚本
（开发期使用，7000 组随机图）校验算法与暴力预言机一致。

## 八、目录结构

```
.
├── app/
│   ├── main.py        # FastAPI 路由
│   ├── services.py    # 事务、整批核验、查询、快照
│   ├── graph.py       # 纯函数图算法（推导/矛盾/最优路径）
│   ├── models.py      # ORM 模型
│   ├── schemas.py     # 请求/响应模型
│   ├── database.py    # 引擎与建表初始化
│   ├── config.py      # 环境变量配置
│   └── errors.py      # 错误类型与统一处理
├── examples/          # demo.py（Python）与 curl-examples.sh
├── tests/             # pytest 测试
├── Dockerfile
├── docker-compose.yml
├── entrypoint.sh      # 等待数据库 → 建表 → 启动
└── requirements.txt
```
