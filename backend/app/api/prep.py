import json
from datetime import date, datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import BomLine, Ingredient, KitchenOrder, OrderLine, PrepRun, PrepUsage
from app.services.bom_engine import explode_and_merge, limit_breaches, result_to_dict
router = APIRouter(prefix="/prep", tags=["prep"])

def _occupied_today(db: Session, today: date) -> dict[int, float]:
    """当日已占量台账：今日全部成功备料单的占用合计（与库存结存分套记账）。"""
    rows = db.execute(
        select(PrepUsage.ingredient_id, func.coalesce(func.sum(PrepUsage.qty), 0.0))
        .where(PrepUsage.biz_date == today)
        .group_by(PrepUsage.ingredient_id)
    ).all()
    return {iid: float(qty) for iid, qty in rows}

def _latest_run(db: Session, order_id: int) -> PrepRun | None:
    return db.scalars(
        select(PrepRun).where(PrepRun.order_id == order_id).order_by(PrepRun.id.desc())
    ).first()

@router.post("/run")
def run_prep(order_id: int = 1, db: Session = Depends(get_db)):
    order = db.get(KitchenOrder, order_id)
    if not order: raise HTTPException(404, "订单不存在")
    today = date.today()  # 同一请求只取一次，整组同一口径
    # 锁全部原料行（按 id 顺序，避免死锁）：与改上限、并发生成互斥，
    # 本次判断用到的上限/已占在提交前不会被别的事务改掉。SQLite 单写者，无需行锁。
    stmt = select(Ingredient).order_by(Ingredient.id)
    if db.get_bind().dialect.name != "sqlite":
        stmt = stmt.with_for_update()
    ing_rows = db.scalars(stmt).all()
    occupied = _occupied_today(db, today)
    ols = [{"dish_id": l.dish_id, "portions": l.portions}
           for l in db.scalars(select(OrderLine).where(OrderLine.order_id == order_id)).all()]
    bom = [{"dish_id": b.dish_id, "ingredient_id": b.ingredient_id, "qty_per_portion": b.qty_per_portion}
           for b in db.scalars(select(BomLine)).all()]
    ings = {i.id: {"code": i.code, "name": i.name, "unit": i.unit, "stock_qty": i.stock_qty,
                   "daily_limit": i.daily_limit or 0.0,
                   "occupied_today": occupied.get(i.id, 0.0)}
            for i in ing_rows}
    lines = explode_and_merge(ols, bom, ings)
    breaches = limit_breaches(lines)
    if breaches:
        # 触顶 → 整组失败：不写备料单行、不挂占用、不新增未备行、不动结存。
        db.rollback()
        raise HTTPException(status_code=409, detail={
            "code": "daily_limit_exceeded",
            "message": "当日可领已满",
            "biz_date": today.isoformat(),
            "items": [{
                "ingredient_id": b.ingredient_id,
                "ingredient_code": b.ingredient_code,
                "ingredient_name": b.ingredient_name,
                "unit": b.unit,
                "daily_limit": b.daily_limit,
                "occupied_today": b.occupied_before,
                "need_qty": b.need_qty,
            } for b in breaches],
        })
    result = result_to_dict(lines)
    result["order"] = {"id": order.id, "code": order.code, "outlet": order.outlet}
    result["biz_date"] = today.isoformat()
    run = PrepRun(order_id=order_id, created_at=datetime.utcnow(), biz_date=today,
                  result_json=json.dumps(result, ensure_ascii=False))
    db.add(run); db.flush()
    for l in lines:
        db.add(PrepUsage(run_id=run.id, ingredient_id=l.ingredient_id,
                         biz_date=today, qty=l.need_qty))
    db.commit(); db.refresh(run)
    return {"id": run.id, **result}

@router.get("/latest")
def latest(order_id: int = 1, db: Session = Depends(get_db)):
    run = _latest_run(db, order_id)
    if not run:
        raise HTTPException(404, "尚未生成备料单")
    data = json.loads(run.result_json)
    return {"id": run.id, **data}

@router.get("/shortages")
def shortages(order_id: int = 1, db: Session = Depends(get_db)):
    run = _latest_run(db, order_id)
    if not run:
        return {"order_id": order_id, "shortages": [],
                "stats": {"ingredient_count": 0, "shortage_count": 0, "total_shortage_qty": 0}}
    data = json.loads(run.result_json)
    return {"order_id": order_id, "shortages": data.get("shortages", []), "stats": data.get("stats", {})}
