"""Central kitchen BOM explode: order lines × BOM qty, merge ingredients, shortage = need - stock.

Daily-issue-limit ledger model (三套账，互不混记):
  - 当日已占量 occupied_today: sum of PrepUsage rows for today (passed in via ingredients dict)
  - 当前这次备料单 need_qty: this run's exploded demand, checked against limit - occupied
  - 未备清单 shortages: need - stock, stock ledger only; a limit failure never writes here
"""
from __future__ import annotations
from dataclasses import asdict, dataclass

# float tolerance so occupied + need == limit exactly is allowed (上限含本数)
EPS = 1e-9

@dataclass
class NeedLine:
    ingredient_id: int
    ingredient_code: str
    ingredient_name: str
    unit: str
    need_qty: float
    stock_qty: float
    shortage: float
    daily_limit: float = 0.0        # 0 = 当日不限
    occupied_before: float = 0.0    # 本次生成前当日已占
    occupied_after: float = 0.0     # 含本次需求后的当日占用

def explode_and_merge(
    order_lines: list[dict],
    bom_lines: list[dict],
    ingredients: dict[int, dict],
) -> list[NeedLine]:
    """order_lines: dish_id, portions; bom_lines: dish_id, ingredient_id, qty_per_portion.

    ingredients may carry daily_limit and occupied_today; both default to 0
    (0 limit = not capped) so stock-only callers keep working unchanged.
    """
    need: dict[int, float] = {}
    for ol in order_lines:
        for bl in bom_lines:
            if bl["dish_id"] != ol["dish_id"]:
                continue
            need[bl["ingredient_id"]] = need.get(bl["ingredient_id"], 0.0) + ol["portions"] * bl["qty_per_portion"]
    lines: list[NeedLine] = []
    for iid, qty in sorted(need.items()):
        ing = ingredients[iid]
        stock = float(ing.get("stock_qty", 0))
        occupied = float(ing.get("occupied_today", 0) or 0)
        limit = float(ing.get("daily_limit", 0) or 0)
        qty = round(qty, 3)
        shortage = max(0.0, qty - stock)
        lines.append(NeedLine(
            ingredient_id=iid,
            ingredient_code=ing["code"],
            ingredient_name=ing["name"],
            unit=ing.get("unit", ""),
            need_qty=qty,
            stock_qty=round(stock, 3),
            shortage=round(shortage, 3),
            daily_limit=round(limit, 3),
            occupied_before=round(occupied, 3),
            occupied_after=round(occupied + qty, 3),
        ))
    return lines

def limit_breaches(lines: list[NeedLine]) -> list[NeedLine]:
    """Lines whose 当日已占 + 本次需求 exceeds 当日上限. Limit 0 means uncapped.

    Any non-empty result must fail the WHOLE run (整组失败) — callers must not
    persist a partial prep sheet, bump occupancy, or append shortage rows.
    """
    return [l for l in lines if l.daily_limit > 0 and l.occupied_after > l.daily_limit + EPS]

def result_to_dict(lines: list[NeedLine]) -> dict:
    return {
        "prep_lines": [asdict(l) for l in lines],
        "shortages": [asdict(l) for l in lines if l.shortage > 0],
        "stats": {
            "ingredient_count": len(lines),
            "shortage_count": sum(1 for l in lines if l.shortage > 0),
            "total_shortage_qty": round(sum(l.shortage for l in lines), 3),
        },
    }
