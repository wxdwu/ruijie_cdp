-- ============================================================
-- MySQL 初始化：创建应用账号 app_cdp 并授予「所有数据库」权限
-- ------------------------------------------------------------
-- 本脚本随镜像首次初始化时（数据目录为空）自动执行，执行顺序早于
-- 01_init_table_struc.sql / 02_init_table_data.sql。
-- 使用 mysql_native_password 认证插件，避免依赖 cryptography（pymysql 兼容）。
-- 与 backend/app/config/config.py 默认值保持一致：user=app_cdp / password=123456。
-- ============================================================

CREATE USER IF NOT EXISTS 'app_cdp'@'%'         IDENTIFIED WITH mysql_native_password BY '123456';
CREATE USER IF NOT EXISTS 'app_cdp'@'localhost' IDENTIFIED WITH mysql_native_password BY '123456';

GRANT ALL PRIVILEGES ON *.* TO 'app_cdp'@'%'         WITH GRANT OPTION;
GRANT ALL PRIVILEGES ON *.* TO 'app_cdp'@'localhost' WITH GRANT OPTION;

FLUSH PRIVILEGES;
