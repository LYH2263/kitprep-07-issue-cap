from app.services.bom_engine import evaluate_caps, explode_and_merge, merge_needs

INGREDIENTS = {
    1: {"code": "A", "name": "肉", "unit": "kg", "stock_qty": 1.0, "daily_limit": 5.0},
    2: {"code": "B", "name": "米", "unit": "kg", "stock_qty": 5.0, "daily_limit": 0.0},
}

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

def test_merge_needs_sums_by_ingredient():
    need = merge_needs(
        [{"dish_id": 1, "portions": 10}, {"dish_id": 2, "portions": 5}],
        [
            {"dish_id": 1, "ingredient_id": 1, "qty_per_portion": 0.2},
            {"dish_id": 2, "ingredient_id": 1, "qty_per_portion": 0.3},
        ],
    )
    assert need == {1: 3.5}

def test_cap_zero_means_unlimited():
    # daily_limit=0：无论已占多少都不拦截
    v = evaluate_caps({2: 999.0}, {2: 999.0}, INGREDIENTS)
    assert v == []

def test_cap_boundary_equal_passes():
    # 已占 2 + 本次 3 = 5，恰好等于上限 5，放行
    assert evaluate_caps({1: 3.0}, {1: 2.0}, INGREDIENTS) == []

def test_cap_exceeded_by_need():
    v = evaluate_caps({1: 3.1}, {1: 2.0}, INGREDIENTS)
    assert len(v) == 1
    assert v[0].ingredient_id == 1
    assert v[0].daily_limit == 5.0
    assert v[0].occupied_qty == 2.0
    assert v[0].need_qty == 3.1

def test_cap_exceeded_by_occupied_alone():
    # 历史单已占满，本次任何正数需求都触顶
    v = evaluate_caps({1: 0.01}, {1: 5.0}, INGREDIENTS)
    assert len(v) == 1

def test_cap_reports_every_violating_ingredient():
    ings = {
        1: {"code": "A", "name": "肉", "unit": "kg", "daily_limit": 1.0},
        2: {"code": "B", "name": "米", "unit": "kg", "daily_limit": 1.0},
        3: {"code": "C", "name": "油", "unit": "L", "daily_limit": 0.0},
    }
    v = evaluate_caps({1: 2.0, 2: 2.0, 3: 50.0}, {}, ings)
    assert {x.ingredient_id for x in v} == {1, 2}
