# 触发一次监控：统计 5 张表数据量并写入 dws_sync_obs（每表一条）
curl -s -X POST "http://localhost:8000/api/admin/monitor/run"

# 每个表最新一次数据量快照
curl -s "http://localhost:8000/api/admin/monitor/latest"

# 最近的监控历史记录（默认 100 条，可用 limit 调整，最大 1000）
curl -s "http://localhost:8000/api/admin/monitor/history?limit=100"
