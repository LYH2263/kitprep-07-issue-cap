from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.services import prep_service
router = APIRouter(prefix="/prep", tags=["prep"])

def _bdate(business_date: date | None) -> date:
    return business_date or date.today()

@router.post("/run")
def run_prep(order_id: int = 1,
             business_date: date | None = Query(default=None),
             db: Session = Depends(get_db)):
    """生成备料单：触顶整组失败，已写行全部回滚、占用退回、未备不挂、结存不变。"""
    try:
        return prep_service.generate_prep(db, order_id, _bdate(business_date))
    except prep_service.OrderNotFound:
        raise HTTPException(404, "订单不存在")
    except prep_service.CapExceeded as exc:
        # 只写「当日可领已满」，不得写成「结存不够」
        raise HTTPException(409, {"message": prep_service.CAP_FULL_MESSAGE,
                                  "violations": exc.violations})

@router.get("/preview")
def preview(order_id: int = 1,
            business_date: date | None = Query(default=None),
            db: Session = Depends(get_db)):
    """只读试算：需求、当日已占、按现上限是否触顶，绝不写账。"""
    try:
        return prep_service.preview_snapshot(db, order_id, _bdate(business_date))
    except prep_service.OrderNotFound:
        raise HTTPException(404, "订单不存在")

@router.get("/latest")
def latest(order_id: int = 1,
           business_date: date | None = Query(default=None),
           db: Session = Depends(get_db)):
    """只读：当日最近一张备料单；没有就返回空账本，绝不代为生成。"""
    return prep_service.latest_snapshot(db, order_id, _bdate(business_date))

@router.get("/shortages")
def shortages(order_id: int = 1,
              business_date: date | None = Query(default=None),
              db: Session = Depends(get_db)):
    """只读未备账本：只来自整组成功的备料单挂账。"""
    data = prep_service.latest_snapshot(db, order_id, _bdate(business_date))
    return {"order_id": order_id, "business_date": data["business_date"],
            "unprep": data["unprep"], "stats": data["stats"]}

@router.get("/occupancy")
def occupancy(business_date: date | None = Query(default=None),
              db: Session = Depends(get_db)):
    """只读：当日各原料已占/上限/剩余，备料台与库存页同口径。"""
    return prep_service.occupancy_snapshot(db, _bdate(business_date))
