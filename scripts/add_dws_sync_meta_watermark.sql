-- 为 dws_sync_meta 增加 ID 类字段增量水位列（记录每张表上次同步到的最大 id）。
-- 该列由后端增量同步逻辑按需维护；代码已幂等处理（information_schema 判断不存在才加），
-- 所以通常无需手动执行本脚本。仅作为 DBA / 手动初始化参考。
-- 注意：MySQL 不支持 ADD COLUMN IF NOT EXISTS，故先确认列是否存在再执行。
ALTER TABLE dws_sync_meta
  ADD COLUMN last_watermark_value BIGINT NOT NULL DEFAULT 0
  COMMENT 'ID 类字段增量同步的水位：上次同步到的最大 id';
