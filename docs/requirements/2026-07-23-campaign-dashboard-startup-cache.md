# 营销看板启动与缓存一体化优化

## 背景与目标

营销看板默认首屏的数据库聚合耗时约 15 秒，返回详情页后重新进入还会重复加载。
本次改造通过 Redis 分层缓存、蓝绿 generation 预热、页面 KeepAlive 和 MySQL
专项索引，在不改变数据口径的前提下缩短首次打开、硬刷新和返回页面的等待时间。

## 成功标准

- Redis 热态 bootstrap 服务端响应低于 300ms，完整看板 1 秒内可用。
- 从客户详情返回看板时保留筛选、分页、数据和滚动位置，100ms 内可交互。
- 新增索引后，Redis 冷态默认查询相对当前基线至少降低 50%。
- ETL 更新时继续读取旧 generation，新 generation 全部预热成功后才原子切换。
- Redis、预热或 generation 控制失败时自动回退 MySQL，不影响业务可用性。

## 计划变更

- 复用通用 JSON Cache-Aside，增加营销专用锁等待参数和 generation 命名空间。
- 缓存筛选项、overview、content-effect、客户分页和默认 bootstrap；关键词查询旁路。
- 启动时后台预热，ETL 成功后顺序构建新 generation，并在成功后原子切换。
- 营销接口返回 `X-Cache`、`X-Cache-TTL`、`X-Data-Generation`，健康检查暴露预热状态。
- bootstrap 从子缓存顺序组装，并直接返回真实 `content_effect`。
- CampaignBoard 使用 KeepAlive，返回页面时显示旧数据并在后台刷新。
- 为客户主表和互动明细表增加营销查询组合索引，并在 ETL 双表轮换中保持索引。
- 提供幂等 MySQL 8.4 在线迁移脚本，同时更新初始化 SQL 的主表和 backup 表。

## 测试与验证

- 单测覆盖缓存 HIT/MISS/BYPASS、长锁等待、关键词旁路、generation 切换和失败降级。
- 验证 ETL 成功触发换代，失败路径不触发；索引创建幂等且覆盖轮换表。
- 运行后端 pytest 和前端 `npm run build`。
- 部署后用固定默认参数测量冷态、热态、Redis 故障和 ETL 切换期间的响应时间。
- 迁移后执行 `ANALYZE TABLE` 与 `EXPLAIN`，确认专项过滤不再全表扫描。

## 假设与不在范围

- Redis 继续作为可丢失缓存，不开放宿主机端口，不启用 AOF/RDB。
- 保持单 Uvicorn worker，避免 lifespan 中的 ETL scheduler 被重复启动。
- 不新增预聚合业务表，不修改营销指标口径和主要 JSON 字段。
- 本次提交提供在线迁移脚本；生产数据库索引需在低流量窗口由部署流程执行。
- 不使用 localStorage/sessionStorage 保存看板状态。
