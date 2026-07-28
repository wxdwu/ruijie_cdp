-- 营销看板冷查询索引（MySQL 8.4）。
-- 幂等、逐个在线创建；建议在低流量窗口执行。

SET @ddl = IF(
  EXISTS(
    SELECT 1 FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'dws_customer_360'
      AND index_name = 'idx_campaign_industry_customer'
  ),
  'DO 0',
  'ALTER TABLE dws_customer_360 ADD INDEX idx_campaign_industry_customer (campaign_tag, industry, customer_name), ALGORITHM=INPLACE, LOCK=NONE'
);
PREPARE campaign_index_stmt FROM @ddl;
EXECUTE campaign_index_stmt;
DEALLOCATE PREPARE campaign_index_stmt;

SET @ddl = IF(
  EXISTS(
    SELECT 1 FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'dws_customer_360'
      AND index_name = 'idx_campaign_default_sort'
  ),
  'DO 0',
  'ALTER TABLE dws_customer_360 ADD INDEX idx_campaign_default_sort (campaign_tag, intent_score DESC, active_opp_amount DESC, customer_name), ALGORITHM=INPLACE, LOCK=NONE'
);
PREPARE campaign_index_stmt FROM @ddl;
EXECUTE campaign_index_stmt;
DEALLOCATE PREPARE campaign_index_stmt;

SET @ddl = IF(
  EXISTS(
    SELECT 1 FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'dws_interaction_detail'
      AND index_name = 'idx_customer_event_time'
  ),
  'DO 0',
  'ALTER TABLE dws_interaction_detail ADD INDEX idx_customer_event_time (customer_name, event_time), ALGORITHM=INPLACE, LOCK=NONE'
);
PREPARE campaign_index_stmt FROM @ddl;
EXECUTE campaign_index_stmt;
DEALLOCATE PREPARE campaign_index_stmt;

SET @ddl = IF(
  EXISTS(
    SELECT 1 FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'dws_interaction_detail'
      AND index_name = 'idx_customer_channel_event_time'
  ),
  'DO 0',
  'ALTER TABLE dws_interaction_detail ADD INDEX idx_customer_channel_event_time (customer_name, channel, event_time), ALGORITHM=INPLACE, LOCK=NONE'
);
PREPARE campaign_index_stmt FROM @ddl;
EXECUTE campaign_index_stmt;
DEALLOCATE PREPARE campaign_index_stmt;

SET @ddl = IF(
  EXISTS(
    SELECT 1 FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'dws_customer_360_backup'
      AND index_name = 'idx_campaign_industry_customer'
  ),
  'DO 0',
  'ALTER TABLE dws_customer_360_backup ADD INDEX idx_campaign_industry_customer (campaign_tag, industry, customer_name), ALGORITHM=INPLACE, LOCK=NONE'
);
PREPARE campaign_index_stmt FROM @ddl;
EXECUTE campaign_index_stmt;
DEALLOCATE PREPARE campaign_index_stmt;

SET @ddl = IF(
  EXISTS(
    SELECT 1 FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'dws_customer_360_backup'
      AND index_name = 'idx_campaign_default_sort'
  ),
  'DO 0',
  'ALTER TABLE dws_customer_360_backup ADD INDEX idx_campaign_default_sort (campaign_tag, intent_score DESC, active_opp_amount DESC, customer_name), ALGORITHM=INPLACE, LOCK=NONE'
);
PREPARE campaign_index_stmt FROM @ddl;
EXECUTE campaign_index_stmt;
DEALLOCATE PREPARE campaign_index_stmt;

SET @ddl = IF(
  EXISTS(
    SELECT 1 FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'dws_interaction_detail_backup'
      AND index_name = 'idx_customer_event_time'
  ),
  'DO 0',
  'ALTER TABLE dws_interaction_detail_backup ADD INDEX idx_customer_event_time (customer_name, event_time), ALGORITHM=INPLACE, LOCK=NONE'
);
PREPARE campaign_index_stmt FROM @ddl;
EXECUTE campaign_index_stmt;
DEALLOCATE PREPARE campaign_index_stmt;

SET @ddl = IF(
  EXISTS(
    SELECT 1 FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name = 'dws_interaction_detail_backup'
      AND index_name = 'idx_customer_channel_event_time'
  ),
  'DO 0',
  'ALTER TABLE dws_interaction_detail_backup ADD INDEX idx_customer_channel_event_time (customer_name, channel, event_time), ALGORITHM=INPLACE, LOCK=NONE'
);
PREPARE campaign_index_stmt FROM @ddl;
EXECUTE campaign_index_stmt;
DEALLOCATE PREPARE campaign_index_stmt;

ANALYZE TABLE
  dws_customer_360,
  dws_customer_360_backup,
  dws_interaction_detail,
  dws_interaction_detail_backup;
