-- ============================================================
-- CDP ETL 性能索引补充
-- Target: 192.168.159.22:33307 / app_cdp
-- 用途：加速全量/增量 ETL 同步中的聚合与分组（CRM 分组、智渠 ICP 构建、
--       交互明细按联系人分组构建 dws_contact_360 等）。
-- 说明：本脚本幂等，可重复执行（已存在的索引会自动跳过）。
--       代码侧 etl_sync._create_indexes() 也会在每次同步时自动确保这些索引。
-- ============================================================

DROP PROCEDURE IF EXISTS add_idx_if_missing;
DELIMITER $$
CREATE PROCEDURE add_idx_if_missing(
    IN p_db   VARCHAR(64),
    IN p_tbl  VARCHAR(64),
    IN p_idx  VARCHAR(64),
    IN p_cols VARCHAR(255)
)
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.statistics
        WHERE table_schema = p_db
          AND table_name   = p_tbl
          AND index_name   = p_idx
    ) THEN
        SET @sql = CONCAT('CREATE INDEX ', p_idx, ' ON ', p_tbl, ' (', p_cols, ')');
        PREPARE stmt FROM @sql;
        EXECUTE stmt;
        DEALLOCATE PREPARE stmt;
        SELECT CONCAT('已创建索引 ', p_idx, ' ON ', p_tbl) AS result;
    ELSE
        SELECT CONCAT('索引已存在，跳过 ', p_idx, ' ON ', p_tbl) AS result;
    END IF;
END$$
DELIMITER ;

-- 1) CRM 两张源表按 customer_name 分组（预聚合联系人属性、商机指标）
CALL add_idx_if_missing('app_cdp', 'ods_crm_contact_day',      'idx_crm_custname',  'customer_name');
CALL add_idx_if_missing('app_cdp', 'ods_crm_opportunity_day',  'idx_opp_custname',  'customer_name');

-- 2) 智渠联系人：按 related_company 取 ICP 客户、按 mobile 取 ICP 手机号
CALL add_idx_if_missing('app_cdp', 'ods_zhique_contact_day',    'idx_zqc_related',   'related_company');
CALL add_idx_if_missing('app_cdp', 'ods_zhique_contact_day',    'idx_zqc_mobile',    'mobile');

-- 3) 天润会话按 customer_name 过滤（建 contact_mapping / 交互明细时跳过 NULL）
CALL add_idx_if_missing('app_cdp', 'ods_tianrun_session_day',   'idx_tr_custname',   'customer_name');

-- 4) 交互明细按 (contact_name, mobile) 分组构建 dws_contact_360
--    （增量临时表由 LIKE 主表创建，自动继承该索引）
CALL add_idx_if_missing('app_cdp', 'dws_interaction_detail',    'idx_contact_mobile', 'contact_name, mobile');

DROP PROCEDURE IF EXISTS add_idx_if_missing;
