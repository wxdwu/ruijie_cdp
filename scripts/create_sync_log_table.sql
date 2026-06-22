-- 创建 dws_sync_log 表，用于记录全量和增量同步的日志
CREATE TABLE IF NOT EXISTS dws_sync_log (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  sync_type VARCHAR(16) NOT NULL COMMENT 'full|incremental',
  trigger_by VARCHAR(64) DEFAULT 'system' COMMENT '触发人',
  status VARCHAR(16) NOT NULL COMMENT 'running|success|failed',
  start_time DATETIME NOT NULL COMMENT '同步开始时间',
  end_time DATETIME COMMENT '同步结束时间',
  rows_synced INT DEFAULT 0 COMMENT '同步行数',
  error_message TEXT COMMENT '错误信息',
  details JSON COMMENT '步骤级统计信息',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_sync_type (sync_type),
  INDEX idx_status (status),
  INDEX idx_start_time (start_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='同步日志表';
