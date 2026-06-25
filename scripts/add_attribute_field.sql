-- dws_customer_360 主表
SET @sql = (
  SELECT CASE WHEN COUNT(*) = 0 THEN
    'ALTER TABLE dws_customer_360 ADD COLUMN attribute VARCHAR(4) DEFAULT NULL COMMENT ''客户分级 H/M/L/空'''
  ELSE 'SELECT ''dws_customer_360.attribute already exists'' AS msg' END
  FROM information_schema.columns
  WHERE table_schema = 'app_cdp' AND table_name = 'dws_customer_360' AND column_name = 'attribute'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- dws_customer_360_backup 备份表
SET @sql = (
  SELECT CASE WHEN COUNT(*) = 0 THEN
    'ALTER TABLE dws_customer_360_backup ADD COLUMN attribute VARCHAR(4) DEFAULT NULL COMMENT ''客户分级 H/M/L/空'''
  ELSE 'SELECT ''dws_customer_360_backup.attribute already exists'' AS msg' END
  FROM information_schema.columns
  WHERE table_schema = 'app_cdp' AND table_name = 'dws_customer_360_backup' AND column_name = 'attribute'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
