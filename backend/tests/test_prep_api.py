"""当日上限 + 整组失败 的端到端行为测试（sqlite 文件库，每用例重建）。

三套账分套记账：当日已占量(prep_usage) / 当前备料单(prep_runs) / 未备清单(shortages)。
"""
import json
import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="kitprep_test_")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"

import pytest
from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models.models import PrepRun, PrepUsage
from app.services.seed import seed_if_empty

# 种子数据下各原料当日需求：五花肉 10 / 茄子 9 / 鸡肉 6 / 大米 10.5 / 面条 10 / 生抽 1.75 / 食用油 1.95
NEED = {"I-PR": 10.0, "I-EG": 9.0, "I-CK": 6.0, "I-RC": 10.5, "I-ND": 10.0, "I-SC": 1.75, "I-OL": 1.95}


@pytest.fixture()
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_if_empty(db)
    finally:
        db.close()
    with TestClient(app) as c:
        yield c


def inv(client):
    return {r["code"]: r for r in client.get("/api/inventory").json()}


def set_limit(client, code, value):
    iid = inv(client)[code]["id"]
    return client.put(f"/api/inventory/{iid}/limit", json={"daily_limit": value})


def run_prep(client):
    return client.post("/api/prep/run?order_id=1")


def test_limit_saved_and_listed(client):
    r = set_limit(client, "I-PR", 12.5)
    assert r.status_code == 200 and r.json()["daily_limit"] == 12.5
    row = inv(client)["I-PR"]
    assert row["daily_limit"] == 12.5
    assert row["occupied_today"] == 0.0


def test_negative_limit_rejected_nothing_moves(client):
    assert set_limit(client, "I-PR", 100).status_code == 200
    assert run_prep(client).status_code == 200
    before = inv(client)["I-PR"]
    r = set_limit(client, "I-PR", -1)
    assert r.status_code == 422
    assert "负数" in r.json()["detail"]
    after = inv(client)["I-PR"]
    # 定义与已有单都不动：上限保持、已占保持、结存保持
    assert after["daily_limit"] == before["daily_limit"] == 100.0
    assert after["occupied_today"] == before["occupied_today"] == NEED["I-PR"]
    assert after["stock_qty"] == before["stock_qty"] == 8.0


def test_nan_limit_rejected(client):
    iid = inv(client)["I-PR"]["id"]
    r = client.put(f"/api/inventory/{iid}/limit",
                   content='{"daily_limit": NaN}', headers={"content-type": "application/json"})
    assert r.status_code == 422
    assert inv(client)["I-PR"]["daily_limit"] == 0.0


def test_zero_limit_means_uncapped(client):
    assert set_limit(client, "I-PR", 0).status_code == 200
    assert run_prep(client).status_code == 200


def test_latest_404_and_shortages_empty_before_first_run(client):
    assert client.get("/api/prep/latest?order_id=1").status_code == 404
    r = client.get("/api/prep/shortages?order_id=1")
    assert r.status_code == 200 and r.json()["shortages"] == []


def test_successful_run_occupies_without_touching_stock(client):
    r = run_prep(client)
    assert r.status_code == 200
    line = next(l for l in r.json()["prep_lines"] if l["ingredient_code"] == "I-PR")
    assert line["need_qty"] == NEED["I-PR"]
    assert line["occupied_before"] == 0.0
    assert line["occupied_after"] == NEED["I-PR"]
    row = inv(client)["I-PR"]
    assert row["occupied_today"] == NEED["I-PR"]
    assert row["stock_qty"] == 8.0  # 账面结存不被生成改小，不做成出库
    # 未备清单仍按库存口径（need − stock），与占用台账分套
    shortages = client.get("/api/prep/shortages?order_id=1").json()["shortages"]
    s = next(x for x in shortages if x["ingredient_code"] == "I-PR")
    assert s["shortage"] == 2.0  # 10 − 8


def test_breach_fails_whole_group_and_writes_nothing(client):
    set_limit(client, "I-PR", 5)  # 需求 10 > 上限 5
    r = run_prep(client)
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "daily_limit_exceeded"
    assert detail["message"] == "当日可领已满"  # 不是“结存不够”
    assert len(detail["items"]) == 1
    item = detail["items"][0]
    assert item["ingredient_code"] == "I-PR"
    assert item["need_qty"] == NEED["I-PR"] and item["daily_limit"] == 5.0
    # 整组失败：没有备料单、占用全为 0、未备清单没有新挂行、结存未动
    assert client.get("/api/prep/latest?order_id=1").status_code == 404
    assert all(v["occupied_today"] == 0.0 for v in inv(client).values())
    assert client.get("/api/prep/shortages?order_id=1").json()["shortages"] == []
    assert inv(client)["I-PR"]["stock_qty"] == 8.0
    db = SessionLocal()
    try:
        assert db.query(PrepRun).count() == 0
        assert db.query(PrepUsage).count() == 0
    finally:
        db.close()


def test_second_run_breaches_on_accumulated_occupancy(client):
    set_limit(client, "I-PR", 15)  # 首单 10 通过，再来 10 触顶
    first = run_prep(client)
    assert first.status_code == 200
    r = run_prep(client)
    assert r.status_code == 409
    assert r.json()["detail"]["message"] == "当日可领已满"
    item = r.json()["detail"]["items"][0]
    assert item["occupied_today"] == NEED["I-PR"]  # 已占含首单
    # 第二次生成未留下任何痕迹：占用退回、最新单仍是首单
    assert inv(client)["I-PR"]["occupied_today"] == NEED["I-PR"]
    assert client.get("/api/prep/latest?order_id=1").json()["id"] == first.json()["id"]


def test_limit_change_applies_forward_history_untouched(client):
    set_limit(client, "I-PR", 15)
    first = run_prep(client)
    assert first.status_code == 200
    first_id = first.json()["id"]
    # 改小上限：历史单占用不跟着改，新单按新上限整组失败
    set_limit(client, "I-PR", 5)
    assert inv(client)["I-PR"]["occupied_today"] == NEED["I-PR"]
    assert run_prep(client).status_code == 409
    db = SessionLocal()
    try:
        run1 = db.get(PrepRun, first_id)
        line1 = next(l for l in json.loads(run1.result_json)["prep_lines"]
                     if l["ingredient_code"] == "I-PR")
        assert line1["occupied_after"] == NEED["I-PR"]
        usage1 = db.query(PrepUsage).filter_by(run_id=first_id).all()
        assert sum(u.qty for u in usage1 if u.ingredient_id == inv(client)["I-PR"]["id"]) == NEED["I-PR"]
    finally:
        db.close()
    # 改大上限：按新上限放行
    set_limit(client, "I-PR", 25)
    r = run_prep(client)
    assert r.status_code == 200
    line = next(l for l in r.json()["prep_lines"] if l["ingredient_code"] == "I-PR")
    assert line["occupied_before"] == NEED["I-PR"]
    assert line["occupied_after"] == 2 * NEED["I-PR"]
    assert inv(client)["I-PR"]["occupied_today"] == 2 * NEED["I-PR"]


def test_limit_failure_is_not_reported_as_stock_shortage(client):
    # 大米库存 20 充足、需求 10.5，上限 5 → 只能报“当日可领已满”
    set_limit(client, "I-RC", 5)
    r = run_prep(client)
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["message"] == "当日可领已满"
    assert "结存" not in detail["message"] and "库存不足" not in detail["message"]
    assert detail["items"][0]["ingredient_code"] == "I-RC"
    # 未备清单不得因此新挂行
    assert client.get("/api/prep/shortages?order_id=1").json()["shortages"] == []
