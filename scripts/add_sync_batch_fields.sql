-- 为 DWS 表添加 sync_batch_id 字段，用于增量同步时检测被删除的记录
-- 注意：只新增字段，不修改或删除现有字段

-- dws_contact_mapping 表添加 sync_batch_id 字段
ALTER TABLE dws_contact_mapping 
ADD COLUMN IF NOT EXISTS sync_batch_id BIGINT DEFAULT 0 COMMENT '同步批次ID，用于增量同步删除检测';

-- dws_interaction_detail 表添加 sync_batch_id 字段
ALTER TABLE dws_interaction_detail 
ADD COLUMN IF NOT EXISTS sync_batch_id BIGINT DEFAULT 0 COMMENT '同步批次ID，用于增量同步删除检测';

-- dws_customer_360 表添加 sync_batch_id 字段
ALTER TABLE dws_customer_360 
ADD COLUMN IF NOT EXISTS sync_batch_id BIGINT DEFAULT 0 COMMENT '同步批次ID，用于增量同步删除检测';

-- dws_contact_360 表添加 sync_batch_id 字段
ALTER TABLE dws_contact_360 
ADD COLUMN IF NOT EXISTS sync_batch_id BIGINT DEFAULT 0 COMMENT '同步批次ID，用于增量同步删除检测';

-- 为 sync_batch_id 字段创建索引（可选，视数据量而定）
-- CREATE INDEX idx_cm_sync_batch ON dws_contact_mapping(sync_batch_id);
-- CREATE INDEX idx_id_sync_batch ON dws_interaction_detail(sync_batch_id);
-- CREATE INDEX idx_c360_sync_batch ON dws_customer_360(sync_batch_id);
-- CREATE INDEX idx_ct360_sync_batch ON dws_contact_360(sync_batch_id);
