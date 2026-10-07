import math
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Ingredient
router = APIRouter(prefix="/inventory", tags=["inventory"])

def _serialize(r: Ingredient) -> dict:
    return {"id": r.id, "code": r.code, "name": r.name, "unit": r.unit,
            "stock_qty": r.stock_qty, "daily_limit": r.daily_limit}

@router.get("")
def list_inventory(db: Session = Depends(get_db)):
    return [_serialize(r) for r in db.scalars(select(Ingredient).order_by(Ingredient.id)).all()]

class DailyLimitIn(BaseModel):
    daily_limit: float

@router.patch("/{ingredient_id}")
def update_daily_limit(ingredient_id: int, payload: DailyLimitIn, db: Session = Depends(get_db)):
    value = payload.daily_limit
    if not math.isfinite(value) or value < 0:
        # 负数拒绝保存：定义、已有备料单与占用一律不动
        raise HTTPException(400, "当日上限不能为负数")
    # 行锁：与「生成备料单」锁同一批原料行，两者串行化，避免按新旧上限各算一半
    ing = db.scalars(
        select(Ingredient).where(Ingredient.id == ingredient_id).with_for_update()
    ).first()
    if not ing:
        raise HTTPException(404, "原料不存在")
    ing.daily_limit = float(value)
    db.commit()
    db.refresh(ing)
    return _serialize(ing)
