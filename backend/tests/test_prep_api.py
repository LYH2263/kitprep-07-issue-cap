from sqlalchemy import func, select

from app.models.models import (
    Dish, Ingredient, KitchenOrder, OrderLine, PrepLine, PrepRun, UnprepItem,
)


def _counts(Session):
    s = Session()
    try:
        return {
            "runs": s.scalar(select(func.count()).select_from(PrepRun)),
            "lines": s.scalar(select(func.count()).select_from(PrepLine)),
            "unprep": s.scalar(select(func.count()).select_from(UnprepItem)),
        }
    finally:
        s.close()


def _ing(Session, code):
    s = Session()
    try:
        return s.scalars(select(Ingredient).where(Ingredient.code == code)).first()
    finally:
        s.close()


def test_first_run_succeeds_at_exact_boundary(client, db_session, order_id):
    # 五花肉需求 40*0.25=10，恰好等于当日上限 10，放行
    res = client.post(f"/prep/run?order_id={order_id}")
    assert res.status_code == 200, res.text
    data = res.json()
    meat = next(l for l in data["prep_lines"] if l["ingredient_code"] == "I1")
    assert meat["need_qty"] == 10.0
    assert meat["daily_limit"] == 10.0
    assert meat["occupied_qty"] == 10.0  # 已含本次
    assert meat["remaining_qty"] == 0.0
    assert _counts(db_session) == {"runs": 1, "lines": 2, "unprep": 1}
    # 结存缺口挂未备，理由是「结存不够」
    assert data["unprep"][0]["ingredient_code"] == "I1"
    assert data["unprep"][0]["qty"] == 2.0
    assert data["unprep"][0]["reason"] == "结存不够"
    # 账面结存不被改小（不是出库）
    assert _ing(db_session, "I1").stock_qty == 8.0


def test_second_run_fails_as_whole_group(client, db_session, order_id):
    assert client.post(f"/prep/run?order_id={order_id}").status_code == 200
    counts_after_first = _counts(db_session)

    res = client.post(f"/prep/run?order_id={order_id}")
    assert res.status_code == 409
    body = res.json()["detail"]
    assert body["message"] == "当日可领已满"
    assert "结存不够" not in str(body)
    assert body["violations"][0]["ingredient_code"] == "I1"
    assert body["violations"][0]["occupied_qty"] == 10.0
    assert body["violations"][0]["need_qty"] == 10.0

    # 触顶后：没有新单、没有新占用行、未备不挂行、结存不变
    assert _counts(db_session) == counts_after_first
    assert _ing(db_session, "I1").stock_qty == 8.0


def test_get_endpoints_never_write(client, db_session, order_id):
    latest = client.get(f"/prep/latest?order_id={order_id}")
    assert latest.status_code == 200
    assert latest.json()["latest_run"] is None
    assert latest.json()["prep_lines"] == []
    short = client.get(f"/prep/shortages?order_id={order_id}")
    assert short.status_code == 200
    assert short.json()["unprep"] == []
    preview = client.get(f"/prep/preview?order_id={order_id}")
    assert preview.status_code == 200
    assert preview.json()["would_exceed_cap"] is False
    assert _counts(db_session) == {"runs": 0, "lines": 0, "unprep": 0}


def test_change_limit_then_recheck_keeps_history(client, db_session, order_id):
    assert client.post(f"/prep/run?order_id={order_id}").status_code == 200
    # 第二次按旧上限 10 必触顶
    assert client.post(f"/prep/run?order_id={order_id}").status_code == 409

    meat = _ing(db_session, "I1")
    res = client.patch(f"/inventory/{meat.id}", json={"daily_limit": 20.0})
    assert res.status_code == 200
    # 改上限后按新判：已占 10 + 本次 10 = 20，边界相等放行
    res = client.post(f"/prep/run?order_id={order_id}")
    assert res.status_code == 200, res.text

    # 历史单占用行不跟着改：两张单各记 10，当日合计已占 20
    s = db_session()
    try:
        rows = s.scalars(select(PrepLine).where(PrepLine.ingredient_id == meat.id)
                         .order_by(PrepLine.run_id)).all()
        assert [r.need_qty for r in rows] == [10.0, 10.0]
    finally:
        s.close()
    latest = client.get(f"/prep/preview?order_id={order_id}").json()
    meat_line = next(l for l in latest["prep_lines"] if l["ingredient_code"] == "I1")
    assert meat_line["occupied_qty"] == 20.0


def test_limit_zero_means_unlimited(client, db_session, order_id):
    meat = _ing(db_session, "I1")
    assert client.patch(f"/inventory/{meat.id}", json={"daily_limit": 0.0}).status_code == 200
    # 连续生成也不拦
    assert client.post(f"/prep/run?order_id={order_id}").status_code == 200
    assert client.post(f"/prep/run?order_id={order_id}").status_code == 200


def test_negative_limit_rejected_without_touching_books(client, db_session, order_id):
    assert client.post(f"/prep/run?order_id={order_id}").status_code == 200
    counts = _counts(db_session)
    meat = _ing(db_session, "I1")
    old_limit = meat.daily_limit

    r = client.patch(f"/inventory/{meat.id}", json={"daily_limit": -1})
    assert r.status_code == 400
    assert "负数" in r.json()["detail"]
    r_nan = client.patch(f"/inventory/{meat.id}", data='{"daily_limit": NaN}',
                         headers={"Content-Type": "application/json"})
    assert r_nan.status_code == 400

    # 定义与已有单都不动
    assert _ing(db_session, "I1").daily_limit == old_limit
    assert _counts(db_session) == counts


def test_one_ingredient_capped_fails_entire_group(client, db_session, order_id):
    # 第二张订单：鱼香茄子 30 份 -> 油 3；把油当日上限压到 2
    s = db_session()
    try:
        dish2 = s.scalars(select(Dish).where(Dish.code == "D2")).first()
        order2 = KitchenOrder(code="KO-2", outlet="城东门店", status="open")
        s.add(order2); s.flush()
        s.add(OrderLine(order_id=order2.id, dish_id=dish2.id, portions=30))
        s.scalars(select(Ingredient).where(Ingredient.code == "I3")).first().daily_limit = 2.0
        oid = order2.id
        s.commit()
    finally:
        s.close()

    res = client.post(f"/prep/run?order_id={oid}")
    assert res.status_code == 409
    assert res.json()["detail"]["message"] == "当日可领已满"

    # 整组失败：这张单一行都不许落，也不许挂未备
    s = db_session()
    try:
        assert s.scalar(select(func.count()).select_from(PrepRun)
                        .where(PrepRun.order_id == oid)) == 0
        # order_id=1 从未成功生成过
        assert s.scalar(select(func.count()).select_from(PrepLine)) == 0
        assert s.scalar(select(func.count()).select_from(UnprepItem)) == 0
    finally:
        s.close()


def test_float_tick_boundary_passes(client, db_session, order_id):
    # 大米需求 40*0.15 = 6.000000000000001；上限设 6，按相等放行，不得被尾数打成触顶
    s = db_session()
    try:
        s.scalars(select(Ingredient).where(Ingredient.code == "I2")).first().daily_limit = 6.0
        s.commit()
    finally:
        s.close()
    res = client.post(f"/prep/run?order_id={order_id}")
    assert res.status_code == 200, res.text


def test_different_business_date_has_separate_occupancy(client, db_session, order_id):
    assert client.post(f"/prep/run?order_id={order_id}").status_code == 200
    assert client.post(f"/prep/run?order_id={order_id}").status_code == 409
    # 换一天：占用另算，放行
    res = client.post(f"/prep/run?order_id={order_id}&business_date=2026-10-08")
    assert res.status_code == 200
    assert res.json()["business_date"] == "2026-10-08"


def test_preview_flags_cap_without_writing(client, db_session, order_id):
    meat = _ing(db_session, "I1")
    client.patch(f"/inventory/{meat.id}", json={"daily_limit": 9.0})
    res = client.get(f"/prep/preview?order_id={order_id}")
    data = res.json()
    assert data["would_exceed_cap"] is True
    assert data["cap_violations"][0]["message"] == "当日可领已满"
    assert _counts(db_session) == {"runs": 0, "lines": 0, "unprep": 0}
