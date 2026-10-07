"""Central kitchen BOM explode: order lines × BOM qty, merge ingredients, shortage = need - stock."""
from __future__ import annotations
from dataclasses import dataclass

@dataclass
class NeedLine:
    ingredient_id: int
    ingredient_code: str
    ingredient_name: str
    unit: str
    need_qty: float
    stock_qty: float
    shortage: float

def merge_needs(
    order_lines: list[dict],
    bom_lines: list[dict],
) -> dict[int, float]:
    """订单行 × BOM 用量，按原料合并需求总量。"""
    need: dict[int, float] = {}
    for ol in order_lines:
        for bl in bom_lines:
            if bl["dish_id"] != ol["dish_id"]:
                continue
            need[bl["ingredient_id"]] = need.get(bl["ingredient_id"], 0.0) + ol["portions"] * bl["qty_per_portion"]
    return need

def explode_and_merge(
    order_lines: list[dict],
    bom_lines: list[dict],
    ingredients: dict[int, dict],
) -> list[NeedLine]:
    """order_lines: dish_id, portions; bom_lines: dish_id, ingredient_id, qty_per_portion."""
    need = merge_needs(order_lines, bom_lines)
    lines: list[NeedLine] = []
    for iid, qty in sorted(need.items()):
        ing = ingredients[iid]
        stock = float(ing.get("stock_qty", 0))
        shortage = max(0.0, qty - stock)
        lines.append(NeedLine(
            ingredient_id=iid,
            ingredient_code=ing["code"],
            ingredient_name=ing["name"],
            unit=ing.get("unit", ""),
            need_qty=round(qty, 3),
            stock_qty=round(stock, 3),
            shortage=round(shortage, 3),
        ))
    return lines

@dataclass
class CapViolation:
    ingredient_id: int
    ingredient_code: str
    ingredient_name: str
    unit: str
    daily_limit: float
    occupied_qty: float
    need_qty: float

def evaluate_caps(
    need_by_ingredient: dict[int, float],
    occupied_by_ingredient: dict[int, float],
    ingredients: dict[int, dict],
) -> list[CapViolation]:
    """当日可领上限判定，备料生成与库存页共用同一口径。

    - daily_limit <= 0：该料不按当日上限拦截；
    - occupied + need > daily_limit 才触顶（恰好相等放行）。
    返回所有触顶原料；调用方据此整组失败。
    """
    violations: list[CapViolation] = []
    for iid in sorted(need_by_ingredient):
        ing = ingredients[iid]
        limit = float(ing.get("daily_limit", 0) or 0)
        if limit <= 0:
            continue
        need = float(need_by_ingredient.get(iid, 0) or 0)
        occupied = float(occupied_by_ingredient.get(iid, 0) or 0)
        total = occupied + need
        # 容忍浮点尾数（如 40*0.15=6.000000000000001）：恰好等于上限按放行处理
        eps = 1e-9 * max(1.0, abs(total), abs(limit))
        if total > limit + eps:
            violations.append(CapViolation(
                ingredient_id=iid,
                ingredient_code=ing["code"],
                ingredient_name=ing["name"],
                unit=ing.get("unit", ""),
                daily_limit=round(limit, 3),
                occupied_qty=round(occupied, 3),
                need_qty=round(need, 3),
            ))
    return violations
