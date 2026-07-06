-- ============================================================
-- 重要客户表字段注释添加脚本（MySQL 版本）
-- 说明：仅为现有字段添加/更新注释，不改变表结构
-- 数据库：MySQL
-- 编码：UTF-8（导入时请使用 utf8mb4 字符集）
-- ============================================================

-- ============================================================
-- 重要提示：解决中文乱码问题
-- ============================================================
-- 方法1：在 MySQL 客户端中执行（推荐）
--   mysql -u username -p --default-character-set=utf8mb4 database_name
--   然后执行：SOURCE /path/to/addComment_key_customer_table.sql;
--
-- 方法2：在 SQL 文件开头添加（已添加在下方）
--   SET NAMES utf8mb4;
--
-- 方法3：在 MySQL 中执行
--   SET NAMES utf8mb4;
--   然后执行 SOURCE 命令导入 SQL 文件
-- ============================================================

-- 设置客户端字符集（解决中文乱码问题）
/*!40101 SET NAMES utf8mb4 */;
/*!40101 SET CHARACTER_SET_CLIENT = utf8mb4 */;
/*!40101 SET CHARACTER_SET_RESULTS = utf8mb4 */;
/*!40101 SET COLLATION_CONNECTION = utf8mb4_unicode_ci */;

-- 设置字符集和存储引擎（与原始表一致）
-- 注意：此脚本仅修改字段注释，不修改字段类型、长度、约束等

-- ============================================================
-- 为字段添加注释（使用 MODIFY COLUMN 保留原结构）
-- ============================================================

-- 主键
ALTER TABLE ods_key_customer 
MODIFY COLUMN id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID';

-- 基础信息字段
ALTER TABLE ods_key_customer 
MODIFY COLUMN category VARCHAR(255) COMMENT '分类';

ALTER TABLE ods_key_customer 
MODIFY COLUMN key_customer_name VARCHAR(500) COMMENT '重客名称';

ALTER TABLE ods_key_customer 
MODIFY COLUMN key_customer_code VARCHAR(100) COMMENT '重客编码';

ALTER TABLE ods_key_customer 
MODIFY COLUMN customer_name VARCHAR(500) COMMENT '名称（客户名称）';

ALTER TABLE ods_key_customer 
MODIFY COLUMN employee_id VARCHAR(100) COMMENT '工号';

-- 客户类型字段
ALTER TABLE ods_key_customer 
MODIFY COLUMN customer_type_old_new VARCHAR(100) COMMENT '重客新老客户';

ALTER TABLE ods_key_customer 
MODIFY COLUMN customer_type_25_old_new VARCHAR(100) COMMENT '25年重客新老客户';

ALTER TABLE ods_key_customer 
MODIFY COLUMN industry_category VARCHAR(255) COMMENT '客户行业整理';

-- 客户关联信息
ALTER TABLE ods_key_customer 
MODIFY COLUMN associated_customer_name VARCHAR(500) COMMENT '客户名';

ALTER TABLE ods_key_customer 
MODIFY COLUMN associated_customer_code VARCHAR(100) COMMENT '重客关联客户编码-整理';

-- 组织架构信息
ALTER TABLE ods_key_customer 
MODIFY COLUMN department_level3 VARCHAR(255) COMMENT '三级部门名称';

ALTER TABLE ods_key_customer 
MODIFY COLUMN department_level3_alt VARCHAR(255) COMMENT '三级部门名称1';

ALTER TABLE ods_key_customer 
MODIFY COLUMN pre_sales_expert VARCHAR(255) COMMENT '售前重客专家';

-- 属性标识
ALTER TABLE ods_key_customer 
MODIFY COLUMN attribute VARCHAR(100) COMMENT '属性';

ALTER TABLE ods_key_customer 
MODIFY COLUMN is_key_customer VARCHAR(10) COMMENT '重客';

ALTER TABLE ods_key_customer 
MODIFY COLUMN sales_volume_category VARCHAR(100) COMMENT '重客销量统计分类';

ALTER TABLE ods_key_customer 
MODIFY COLUMN is_valid VARCHAR(50) COMMENT '是否有效';

-- 净销售额字段（单位：万）
ALTER TABLE ods_key_customer 
MODIFY COLUMN net_sales_2026 DECIMAL(18, 2) COMMENT '2026-净销售额万';

ALTER TABLE ods_key_customer 
MODIFY COLUMN net_sales_2025_same_period DECIMAL(18, 2) COMMENT '2025-25年同期净销售额';

ALTER TABLE ods_key_customer 
MODIFY COLUMN net_sales_2025 DECIMAL(18, 2) COMMENT '2025-净销售额万';

ALTER TABLE ods_key_customer 
MODIFY COLUMN net_sales_2024 DECIMAL(18, 2) COMMENT '2024-净销售额万';

ALTER TABLE ods_key_customer 
MODIFY COLUMN net_sales_2023 DECIMAL(18, 2) COMMENT '2023-净销售额万';

ALTER TABLE ods_key_customer 
MODIFY COLUMN net_sales_2022 DECIMAL(18, 2) COMMENT '2022-净销售额万';

-- 漏斗金额字段（单位：万）
ALTER TABLE ods_key_customer 
MODIFY COLUMN funnel_inner_amount DECIMAL(18, 2) COMMENT '漏斗内金额万';

ALTER TABLE ods_key_customer 
MODIFY COLUMN confirmed_amount DECIMAL(18, 2) COMMENT '确保金额（万）';

ALTER TABLE ods_key_customer 
MODIFY COLUMN advantage_amount DECIMAL(18, 2) COMMENT '优势金额（万）';

ALTER TABLE ods_key_customer 
MODIFY COLUMN possible_amount DECIMAL(18, 2) COMMENT '可能+金额（万）';

ALTER TABLE ods_key_customer 
MODIFY COLUMN funnel_outer_amount DECIMAL(18, 2) COMMENT '漏斗外金额万（不含线索）';

-- 2025年季度净销售额（单位：万）
ALTER TABLE ods_key_customer 
MODIFY COLUMN net_sales_2025_q1 DECIMAL(18, 2) COMMENT '2025年Q1-净销售额万';

ALTER TABLE ods_key_customer 
MODIFY COLUMN net_sales_2025_q2 DECIMAL(18, 2) COMMENT '2025年Q2-净销售额万';

ALTER TABLE ods_key_customer 
MODIFY COLUMN net_sales_2025_q3 DECIMAL(18, 2) COMMENT '2025年Q3-净销售额万';

ALTER TABLE ods_key_customer 
MODIFY COLUMN net_sales_2025_q4 DECIMAL(18, 2) COMMENT '2025年Q4-净销售额万';

-- 2026年季度净销售额（单位：万）
ALTER TABLE ods_key_customer 
MODIFY COLUMN net_sales_2026_q1 DECIMAL(18, 2) COMMENT '2026年Q1-净销售额万';

ALTER TABLE ods_key_customer 
MODIFY COLUMN net_sales_2026_q2 DECIMAL(18, 2) COMMENT '2026年Q2-净销售额万';

-- 2026年Q2漏斗金额（单位：万）
ALTER TABLE ods_key_customer 
MODIFY COLUMN funnel_inner_2026_q2 DECIMAL(18, 2) COMMENT '2026年Q2-漏斗内金额万';

ALTER TABLE ods_key_customer 
MODIFY COLUMN funnel_outer_2026_q2 DECIMAL(18, 2) COMMENT '2026年Q2-漏斗外金额万（不含线索）';

-- 2026年Q3漏斗金额（单位：万）
ALTER TABLE ods_key_customer 
MODIFY COLUMN funnel_inner_2026_q3 DECIMAL(18, 2) COMMENT '2026年Q3-漏斗内金额万';

ALTER TABLE ods_key_customer 
MODIFY COLUMN funnel_outer_2026_q3 DECIMAL(18, 2) COMMENT '2026年Q3-漏斗外金额万（不含线索）';

-- 2026年Q4漏斗金额（单位：万）
ALTER TABLE ods_key_customer 
MODIFY COLUMN funnel_inner_2026_q4 DECIMAL(18, 2) COMMENT '2026年Q4-漏斗内金额万';

ALTER TABLE ods_key_customer 
MODIFY COLUMN funnel_outer_2026_q4 DECIMAL(18, 2) COMMENT '2026年Q4-漏斗外金额万（不含线索）';

-- 业务机会字段
ALTER TABLE ods_key_customer 
MODIFY COLUMN opportunity_count_lead_stage INT COMMENT '业务机会数-线索阶段';

-- 创建时间字段（系统自动生成）
ALTER TABLE ods_key_customer 
MODIFY COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间';

ALTER TABLE ods_key_customer 
MODIFY COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间';

-- 完成提示
SELECT 'ods_key_customer table comments added successfully!' AS message;
