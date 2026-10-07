from datetime import date
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Ingredient, PrepUsage
router = APIRouter(prefix="/inventory", tags=["inventory"])

class DailyLimitIn(BaseModel):
    daily_limit: float

def _occupied_map(db: Session, today: date) -> dict[int, float]:
    rows = db.execute(
        select(PrepUsage.ingredient_id, func.coalesce(func.sum(PrepUsage.qty), 0.0))
        .where(PrepUsage.biz_date == today)
        .group_by(PrepUsage.ingredient_id)
    ).all()
    return {iid: float(qty) for iid, qty in rows}

@router.get("")
def list_inventory(db: Session = Depends(get_db)):
    occupied = _occupied_map(db, date.today())
    return [{"id": r.id, "code": r.code, "name": r.name, "unit": r.unit,
             "stock_qty": r.stock_qty,
             "daily_limit": r.daily_limit or 0.0,
             "occupied_today": round(occupied.get(r.id, 0.0), 3)}
            for r in db.scalars(select(Ingredient).order_by(Ingredient.id)).all()]

@router.put("/{ingredient_id}/limit")
def set_daily_limit(ingredient_id: int, body: DailyLimitIn, db: Session = Depends(get_db)):
    # 负数（含 NaN）拒绝保存：定义与已有单一律不动；0 表示不按当日上限拦截。
    if not (body.daily_limit >= 0):
        raise HTTPException(422, "当日上限不能为负数")
    ing = db.get(Ingredient, ingredient_id)
    if not ing:
        raise HTTPException(404, "原料不存在")
    ing.daily_limit = body.daily_limit
    db.commit()
    return {"id": ing.id, "code": ing.code, "name": ing.name, "daily_limit": ing.daily_limit}
