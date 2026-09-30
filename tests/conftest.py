"""测试夹具：用临时 SQLite 驱动整套 FastAPI + SQLAlchemy 代码路径。"""
import os
import tempfile

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.name}"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import init_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _init():
    init_db()
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def register_site(client, code="S1", name="一号遗址"):
    return client.post("/api/sites", json={"code": code, "name": name})


def register_strata(client, site="S1", codes=("L1", "L2", "L3", "L4", "L5", "L6")):
    register_site(client, site)
    for code in codes:
        client.post("/api/strata", json={"code": code, "site_code": site, "name": code})


def rev(client):
    return client.get("/health").json()["revision"]


def batch(client, base, add=None, withdraw=None):
    return client.post(
        "/api/assertions/batch",
        json={"base_revision": base, "add": add or [], "withdraw": withdraw or []},
    )
