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
3. 在「库存」给原料设置**当日最多可领量（当日上限）**：`0` 表示该料不按当日上限拦截；负数拒绝保存。
4. 打开「备料单」展开合并原料需求，点「生成备料单」落账。
5. 在「未备」查看整组成功后仍结存不足的原料。

## 当日上限与整组失败记账

三套账分开记，互不混用：

- **备料单 / 占用列**：`prep_runs` + `prep_lines`，整组成功才写出；`prep_lines.need_qty` 是「当日已占量」的唯一来源。
- **未备清单**：`unprep_items`，仅整组成功后，需求高于**账面结存**的原料按「结存不够」挂行。
- **账面结存**：`ingredients.stock_qty`，生成备料单**不会**改小它（备料不是出库）。

生成规则：

- 判定口径统一为 `当日已占 + 本次需求 > 当日上限` 才算触顶；**恰好相等放行**（含浮点尾数容差）。
- 任一受上限管理的原料触顶，**整组失败**：先写出的行随事务全部撤回，占用退回、未备清单不挂新行、结存不变。不允许「前面的菜成单、后面的菜进未备」。
- 触顶只返回 **409「当日可领已满」**，绝不写成「结存不够」。
- 改上限后按**新上限**判定；历史备料单的占用行不随上限修改而变动。
- 生成备料单与库存页改上限都对同一批原料行按主键 `FOR UPDATE` 加锁串行化，两处同口径，不会一个按旧上限截半桌、一个整组失败。
- 只有显式 `POST /prep/run` 写账；`GET /prep/latest`、`/preview`、`/shortages`、`/occupancy` 全只读，缺单时不代为生成。
- 占用按营业日（`business_date`，默认当天）分日累计，跨天互不占用。

## 开发与测试

```bash
docker compose exec api pytest -q
```
