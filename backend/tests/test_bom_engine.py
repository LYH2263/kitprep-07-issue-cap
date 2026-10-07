from app.services.bom_engine import explode_and_merge, limit_breaches

def test_explode_merge():
    order_lines = [{"dish_id": 1, "portions": 10}, {"dish_id": 2, "portions": 5}]
    bom = [
        {"dish_id": 1, "ingredient_id": 1, "qty_per_portion": 0.2},
        {"dish_id": 1, "ingredient_id": 2, "qty_per_portion": 0.1},
        {"dish_id": 2, "ingredient_id": 1, "qty_per_portion": 0.3},
    ]
    ings = {
        1: {"code": "A", "name": "肉", "unit": "kg", "stock_qty": 1.0},
        2: {"code": "B", "name": "米", "unit": "kg", "stock_qty": 5.0},
    }
    lines = explode_and_merge(order_lines, bom, ings)
    by_id = {l.ingredient_id: l for l in lines}
    assert by_id[1].need_qty == 3.5  # 10*0.2 + 5*0.3
    assert by_id[1].shortage == 2.5
    assert by_id[2].need_qty == 1.0
    assert by_id[2].shortage == 0.0

def test_no_negative_shortage():
    order_lines = [{"dish_id": 1, "portions": 1}]
    bom = [{"dish_id": 1, "ingredient_id": 1, "qty_per_portion": 1.0}]
    ings = {1: {"code": "A", "name": "油", "unit": "L", "stock_qty": 10.0}}
    lines = explode_and_merge(order_lines, bom, ings)
    assert lines[0].shortage == 0.0

def _lines(limit, occupied, need):
    order_lines = [{"dish_id": 1, "portions": 1}]
    bom = [{"dish_id": 1, "ingredient_id": 1, "qty_per_portion": need}]
    ings = {1: {"code": "A", "name": "肉", "unit": "kg", "stock_qty": 999.0,
                "daily_limit": limit, "occupied_today": occupied}}
    return explode_and_merge(order_lines, bom, ings)

def test_occupancy_fields_carried():
    line = _lines(limit=10.0, occupied=4.0, need=3.0)[0]
    assert line.daily_limit == 10.0
    assert line.occupied_before == 4.0
    assert line.occupied_after == 7.0

def test_breach_when_occupied_plus_need_over_limit():
    assert [l.ingredient_id for l in limit_breaches(_lines(5.0, 4.0, 2.0))] == [1]

def test_exact_limit_allowed():
    assert limit_breaches(_lines(5.0, 2.0, 3.0)) == []

def test_zero_limit_never_breaches():
    assert limit_breaches(_lines(0.0, 0.0, 9999.0)) == []

def test_no_limit_field_defaults_uncapped():
    order_lines = [{"dish_id": 1, "portions": 2}]
    bom = [{"dish_id": 1, "ingredient_id": 1, "qty_per_portion": 3.0}]
    ings = {1: {"code": "A", "name": "米", "unit": "kg", "stock_qty": 1.0}}
    lines = explode_and_merge(order_lines, bom, ings)
    assert lines[0].daily_limit == 0.0
    assert lines[0].occupied_after == 6.0
    assert limit_breaches(lines) == []
