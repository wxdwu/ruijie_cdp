-- 监控聚合表数据规模：记录每次监控时各表的数据量
-- 该表由后端 monitor 模块在首次运行时自动创建（CREATE TABLE IF NOT EXISTS），
-- 此脚本仅作为 DBA / 手动初始化参考。
CREATE TABLE IF NOT EXISTS dws_sync_obs (
    id          BIGINT       NOT NULL AUTO_INCREMENT COMMENT '主键，自增',
    table_name  VARCHAR(128) NOT NULL                COMMENT '被监控的表名',
    table_count BIGINT       NOT NULL DEFAULT 0      COMMENT '该表当前数据量（行数）',
    create_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '监控运行时间',
    PRIMARY KEY (id),
    KEY idx_table_time (table_name, create_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用于监控聚合表数据规模';
