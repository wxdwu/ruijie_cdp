-- ============================================================
-- 营销看板首屏查询索引（MySQL 8.4）
-- 说明：幂等、在线创建，不删除现有单列索引。
-- ============================================================

DROP PROCEDURE IF EXISTS add_campaign_idx_if_missing;
DELIMITER $$
CREATE PROCEDURE add_campaign_idx_if_missing(
    IN p_db   VARCHAR(64),
    IN p_tbl  VARCHAR(64),
    IN p_idx  VARCHAR(64),
    IN p_cols VARCHAR(255)
)
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.statistics
        WHERE table_schema = p_db
          AND table_name = p_tbl
          AND index_name = p_idx
    ) THEN
        SET @sql = CONCAT(
            'CREATE INDEX ', p_idx, ' ON ', p_db, '.', p_tbl,
            ' (', p_cols, ') ALGORITHM=INPLACE LOCK=NONE'
        );
        PREPARE stmt FROM @sql;
        EXECUTE stmt;
        DEALLOCATE PREPARE stmt;
        SELECT CONCAT('已创建索引 ', p_idx, ' ON ', p_tbl) AS result;
    ELSE
        SELECT CONCAT('索引已存在，跳过 ', p_idx, ' ON ', p_tbl) AS result;
    END IF;
END$$
DELIMITER ;

CALL add_campaign_idx_if_missing(
    'app_cdp', 'dws_customer_360', 'idx_campaign_industry_customer',
    'campaign_tag, industry, customer_name'
);
CALL add_campaign_idx_if_missing(
    'app_cdp', 'dws_interaction_detail', 'idx_customer_event_time',
    'customer_name, event_time'
);
CALL add_campaign_idx_if_missing(
    'app_cdp', 'dws_interaction_detail', 'idx_customer_channel_event_time',
    'customer_name, channel, event_time'
);

DROP PROCEDURE IF EXISTS add_campaign_idx_if_missing;
