# KitPrep 中央厨房 BOM 备料

按菜品 BOM 展开订单行、合并同原料需求，对照库存计算缺料并生成备料单。

技术栈：Python 3.12 / FastAPI / SQLAlchemy / PostgreSQL / Vue 3 / TypeScript / Vite

## 启动

```bash
docker compose up --build
```

| 服务 | 地址 |
| --- | --- |
| 前端 | http://localhost:5000 |
| API | http://localhost:10100 |
| API 文档 | http://localhost:10100/docs |
| Postgres | localhost:5451 |

健康检查：`GET http://localhost:10100/api/health`

## 使用说明

1. 在「菜品」「BOM」维护中央厨房出品与用料树。
2. 在「订单」「库存」确认当日需求与现有库存。
3. 打开「备料单」展开合并原料需求。
4. 在「缺料」查看 need − stock 为正的原料。

## 当日可领上限

- 「库存」页可为每种原料设置**当日上限**：0 = 当日不限；负数拒绝保存，定义与已有单都不动。
- 「备料单」点「生成备料单」时按 `当日已占 + 本次需求 ≤ 当日上限` 判定；任一原料触顶则**整组失败**：已写出的行全部撤回、占用退回、未备清单不新挂行、库存结存不变，返回 `409 当日可领已满`（不是"结存不够"）。
- 三套账分开记：当日已占量（`prep_usage` 台账）、当前备料单（`prep_runs`）、未备清单（need − stock）。生成备料单只挂占用，不扣减库存结存，不做成出库。
- 改上限只影响之后的生成；历史备料单的占用记录禁止跟着改。
- 生成与改上限互斥于同一事务口径（生成时按 id 顺序锁定原料行），并发时点要么全按旧上限整组判定、要么全按新上限，不会各看一半。

## 开发与测试

```bash
docker compose exec api pytest -q
```
