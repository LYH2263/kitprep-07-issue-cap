"""备料生成：当日上限整组失败事务。

三套账分开记：
- prep_runs / prep_lines 当前这次备料单（同时是「当日已占量」的唯一来源）；
- unprep_items 未备清单（仅整组成功后，需求高于账面结存才挂行）；
- ingredients.stock_qty 账面结存，生成备料单绝不动它（不是出库）。

触顶即整组失败：先写的行随事务回滚全部撤销，占用不加、未备不挂、结存不变。
"""
from __future__ import annotations
from dataclasses import asdict
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.models import (
    BomLine, Ingredient, KitchenOrder, OrderLine, PrepLine, PrepRun, UnprepItem,
)
from app.services.bom_engine import evaluate_caps, merge_needs

CAP_FULL_MESSAGE = "当日可领已满"

class OrderNotFound(Exception):
    pass

class CapExceeded(Exception):
    def __init__(self, violations: list[dict]):
        self.violations = violations
        super().__init__(CAP_FULL_MESSAGE)

def _load_order(db: Session, order_id: int) -> KitchenOrder:
    order = db.get(KitchenOrder, order_id)
    if not order:
        raise OrderNotFound()
    return order

def _lock_ingredients(db: Session) -> list[Ingredient]:
    # 按主键加锁并固定顺序：与库存页 PATCH 锁同一批行，两口径串行，互不插档。
    return list(db.scalars(
        select(Ingredient).order_by(Ingredient.id).with_for_update()
    ).all())

def _need_map(db: Session, order_id: int) -> dict[int, float]:
    ols = [{"dish_id": l.dish_id, "portions": l.portions}
           for l in db.scalars(select(OrderLine).where(OrderLine.order_id == order_id)).all()]
    bom = [{"dish_id": b.dish_id, "ingredient_id": b.ingredient_id, "qty_per_portion": b.qty_per_portion}
           for b in db.scalars(select(BomLine)).all()]
    return merge_needs(ols, bom)

def occupied_map(db: Session, business_date: date) -> dict[int, float]:
    """当日已占量：只从已提交的 prep_lines 汇总，prep_runs 不另存占用。"""
    rows = db.execute(
        select(PrepLine.ingredient_id, func.coalesce(func.sum(PrepLine.need_qty), 0.0))
        .where(PrepLine.business_date == business_date)
        .group_by(PrepLine.ingredient_id)
    ).all()
    return {iid: float(qty) for iid, qty in rows}

def _ingredient_dict(ings: list[Ingredient]) -> dict[int, dict]:
    return {i.id: {"code": i.code, "name": i.name, "unit": i.unit,
                   "stock_qty": i.stock_qty, "daily_limit": i.daily_limit or 0.0}
            for i in ings}

def _line_payload(iid: int, ing: dict, need: float, occupied: float) -> dict:
    limit = float(ing.get("daily_limit", 0) or 0)
    shortage = max(0.0, need - float(ing.get("stock_qty", 0)))
    return {
        "ingredient_id": iid,
        "ingredient_code": ing["code"],
        "ingredient_name": ing["name"],
        "unit": ing.get("unit", ""),
        "need_qty": round(need, 3),
        "stock_qty": round(float(ing.get("stock_qty", 0)), 3),
        "shortage_qty": round(shortage, 3),
        "daily_limit": round(limit, 3),
        "occupied_qty": round(occupied, 3),
        "remaining_qty": round(limit - occupied, 3) if limit > 0 else None,
    }

def generate_prep(db: Session, order_id: int, business_date: date) -> dict:
    order = _load_order(db, order_id)
    try:
        ings = _lock_ingredients(db)
        need = _need_map(db, order_id)
        ing_map = _ingredient_dict(ings)
        occupied = occupied_map(db, business_date)

        violations = evaluate_caps(need, occupied, ing_map)
        if violations:
            # 触顶：本事务内尚未写任何账；显式回滚，调用方返回 409。
            db.rollback()
            raise CapExceeded([
                {**asdict(v),
                 "message": CAP_FULL_MESSAGE,
                 "remaining_qty": round(v.daily_limit - v.occupied_qty, 3)}
                for v in violations
            ])

        run = PrepRun(order_id=order_id, business_date=business_date)
        db.add(run)
        db.flush()  # 取 run.id；行与单在同一事务里，失败一起回滚

        prep_lines: list[dict] = []
        for iid, qty in sorted(need.items()):
            ing = ing_map[iid]
            shortage = max(0.0, qty - float(ing.get("stock_qty", 0)))
            db.add(PrepLine(run_id=run.id, business_date=business_date,
                            ingredient_id=iid, need_qty=qty,
                            stock_qty=ing["stock_qty"], shortage_qty=shortage))
            if shortage > 0:
                # 整组成功才挂未备：这里是结存缺口，与「当日可领已满」互不相混
                db.add(UnprepItem(run_id=run.id, business_date=business_date,
                                  ingredient_id=iid, qty=shortage, reason="结存不够"))

        db.commit()  # 备料单、占用行、未备行同一提交点；stock_qty 全程未改
    except Exception:
        db.rollback()
        raise

    return latest_snapshot(db, order_id, business_date)

def latest_snapshot(db: Session, order_id: int, business_date: date) -> dict:
    """只读：取当日该订单最近一张备料单，按三张表重建，保证三账对得齐。"""
    order = db.get(KitchenOrder, order_id)
    order_info = ({"id": order.id, "code": order.code, "outlet": order.outlet}
                  if order else None)
    run = db.scalars(
        select(PrepRun)
        .where(PrepRun.order_id == order_id, PrepRun.business_date == business_date)
        .order_by(PrepRun.id.desc())
    ).first()
    occupied = occupied_map(db, business_date)
    ings = {i.id: i for i in db.scalars(select(Ingredient)).all()}
    ing_map = _ingredient_dict(list(ings.values()))

    prep_lines: list[dict] = []
    unprep: list[dict] = []
    if run:
        for pl in db.scalars(select(PrepLine).where(PrepLine.run_id == run.id)
                             .order_by(PrepLine.ingredient_id)).all():
            prep_lines.append(_line_payload(pl.ingredient_id, ing_map[pl.ingredient_id],
                                            pl.need_qty, occupied.get(pl.ingredient_id, 0.0)))
        for u in db.scalars(select(UnprepItem).where(UnprepItem.run_id == run.id)
                            .order_by(UnprepItem.ingredient_id)).all():
            ing = ing_map[u.ingredient_id]
            unprep.append({"ingredient_id": u.ingredient_id,
                           "ingredient_code": ing["code"],
                           "ingredient_name": ing["name"], "unit": ing["unit"],
                           "qty": round(u.qty, 3), "reason": u.reason, "run_id": run.id})

    return {
        "order": order_info,
        "business_date": business_date.isoformat(),
        "latest_run": {"id": run.id, "created_at": run.created_at.isoformat()} if run else None,
        "prep_lines": prep_lines,
        "unprep": unprep,
        "stats": {
            "ingredient_count": len(prep_lines),
            "unprep_count": len(unprep),
            "total_unprep_qty": round(sum(u["qty"] for u in unprep), 3),
        },
    }

def occupancy_snapshot(db: Session, business_date: date) -> dict:
    """只读：每个原料的当日已占、上限、剩余（库存页与备料台共用同一口径）。"""
    ings = list(db.scalars(select(Ingredient).order_by(Ingredient.id)).all())
    occupied = occupied_map(db, business_date)
    rows = []
    for i in ings:
        limit = float(i.daily_limit or 0)
        used = occupied.get(i.id, 0.0)
        rows.append({
            "ingredient_id": i.id,
            "ingredient_code": i.code,
            "ingredient_name": i.name,
            "unit": i.unit,
            "stock_qty": round(i.stock_qty, 3),
            "daily_limit": round(limit, 3),
            "occupied_qty": round(used, 3),
            "remaining_qty": round(limit - used, 3) if limit > 0 else None,
        })
    return {"business_date": business_date.isoformat(), "items": rows}

def preview_snapshot(db: Session, order_id: int, business_date: date) -> dict:
    """只读试算：当前订单需求 + 当日已占 + 按现有上限是否会触顶，不写任何账。"""
    order = _load_order(db, order_id)
    ings = list(db.scalars(select(Ingredient).order_by(Ingredient.id)).all())
    ing_map = _ingredient_dict(ings)
    need = _need_map(db, order_id)
    occupied = occupied_map(db, business_date)
    violations = evaluate_caps(need, occupied, ing_map)
    lines = [_line_payload(iid, ing_map[iid], qty, occupied.get(iid, 0.0))
             for iid, qty in sorted(need.items())]
    return {
        "order": {"id": order.id, "code": order.code, "outlet": order.outlet},
        "business_date": business_date.isoformat(),
        "prep_lines": lines,
        "occupied_before": {str(k): round(v, 3) for k, v in occupied.items()},
        "cap_violations": [{**asdict(v), "message": CAP_FULL_MESSAGE,
                            "remaining_qty": round(v.daily_limit - v.occupied_qty, 3)}
                           for v in violations],
        "would_exceed_cap": bool(violations),
    }
