import os
os.environ.setdefault("DATABASE_URL", "sqlite://")  # 必须在导入 app.* 之前

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.models import BomLine, Dish, Ingredient, KitchenOrder, OrderLine


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestingSession()

    d1 = Dish(code="D1", name="红烧肉套餐")
    d2 = Dish(code="D2", name="鱼香茄子")
    db.add_all([d1, d2]); db.flush()
    # 肉：当日上限 10；米/油：0 不拦截。肉结存 8 < 需求，会挂结存不够。
    i1 = Ingredient(code="I1", name="五花肉", unit="kg", stock_qty=8.0, daily_limit=10.0)
    i2 = Ingredient(code="I2", name="大米", unit="kg", stock_qty=20.0, daily_limit=0.0)
    i3 = Ingredient(code="I3", name="油", unit="L", stock_qty=5.0, daily_limit=0.0)
    db.add_all([i1, i2, i3]); db.flush()
    db.add_all([
        BomLine(dish_id=d1.id, ingredient_id=i1.id, qty_per_portion=0.25),  # 40 份 -> 10
        BomLine(dish_id=d1.id, ingredient_id=i2.id, qty_per_portion=0.15),  # 40 份 -> 6.0000…1
        BomLine(dish_id=d2.id, ingredient_id=i3.id, qty_per_portion=0.1),
    ])
    order = KitchenOrder(code="KO-1", outlet="城西门店", status="open")
    db.add(order); db.flush()
    db.add(OrderLine(order_id=order.id, dish_id=d1.id, portions=40))
    db.commit()

    def override_get_db():
        s = TestingSession()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestingSession
    app.dependency_overrides.clear()
    db.close()
    engine.dispose()


class _Api:
    """给请求路径统一补 /api 前缀。"""
    def __init__(self, raw):
        self.raw = raw
    def get(self, path, **kw):
        return self.raw.get("/api" + path, **kw)
    def post(self, path, **kw):
        return self.raw.post("/api" + path, **kw)
    def patch(self, path, **kw):
        return self.raw.patch("/api" + path, **kw)


@pytest.fixture()
def client(db_session):
    return _Api(TestClient(app))


@pytest.fixture()
def order_id(db_session):
    from app.models.models import KitchenOrder
    s = db_session()
    try:
        return s.scalars(select(KitchenOrder).where(KitchenOrder.code == "KO-1")).first().id
    finally:
        s.close()
