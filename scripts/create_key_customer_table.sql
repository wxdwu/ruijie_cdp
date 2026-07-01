-- ============================================================
-- 重要客户表创建脚本（MySQL 版本）
-- 说明：根据 Excel "重要客户.xlsx" 的字段创建表
-- 数据库：MySQL
-- ============================================================

-- 删除表（如果需要重新创建）
DROP TABLE IF EXISTS ods_key_customer;

-- 创建重要客户表
CREATE TABLE ods_key_customer (
    -- 主键
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键ID',
    
    -- 基础信息字段
    category VARCHAR(255) COMMENT '分类',
    key_customer_name VARCHAR(500) COMMENT '重客名称',
    key_customer_code VARCHAR(100) COMMENT '重客编码',
    customer_name VARCHAR(500) COMMENT '名称（客户名称）',
    employee_id VARCHAR(100) COMMENT '工号',
    
    -- 客户类型字段
    customer_type_old_new VARCHAR(100) COMMENT '重客新老客户',
    customer_type_25_old_new VARCHAR(100) COMMENT '25年重客新老客户',
    industry_category VARCHAR(255) COMMENT '客户行业整理',
    
    -- 客户关联信息
    associated_customer_name VARCHAR(500) COMMENT '客户名',
    associated_customer_code VARCHAR(100) COMMENT '重客关联客户编码-整理',
    
    -- 组织架构信息
    department_level3 VARCHAR(255) COMMENT '三级部门名称',
    department_level3_alt VARCHAR(255) COMMENT '三级部门名称1',
    pre_sales_expert VARCHAR(255) COMMENT '售前重客专家',
    
    -- 属性标识
    attribute VARCHAR(100) COMMENT '属性',
    is_key_customer VARCHAR(10) COMMENT '重客',
    sales_volume_category VARCHAR(100) COMMENT '重客销量统计分类',
    is_valid VARCHAR(50) COMMENT '是否有效',
    
    -- 净销售额字段（单位：万）
    net_sales_2026 DECIMAL(18, 2) COMMENT '2026-净销售额万',
    net_sales_2025_same_period DECIMAL(18, 2) COMMENT '2025-25年同期净销售额',
    net_sales_2025 DECIMAL(18, 2) COMMENT '2025-净销售额万',
    net_sales_2024 DECIMAL(18, 2) COMMENT '2024-净销售额万',
    net_sales_2023 DECIMAL(18, 2) COMMENT '2023-净销售额万',
    net_sales_2022 DECIMAL(18, 2) COMMENT '2022-净销售额万',
    
    -- 漏斗金额字段（单位：万）
    funnel_inner_amount DECIMAL(18, 2) COMMENT '漏斗内金额万',
    confirmed_amount DECIMAL(18, 2) COMMENT '确保金额（万）',
    advantage_amount DECIMAL(18, 2) COMMENT '优势金额（万）',
    possible_amount DECIMAL(18, 2) COMMENT '可能+金额（万）',
    funnel_outer_amount DECIMAL(18, 2) COMMENT '漏斗外金额万（不含线索）',
    
    -- 2025年季度净销售额（单位：万）
    net_sales_2025_q1 DECIMAL(18, 2) COMMENT '2025年Q1-净销售额万',
    net_sales_2025_q2 DECIMAL(18, 2) COMMENT '2025年Q2-净销售额万',
    net_sales_2025_q3 DECIMAL(18, 2) COMMENT '2025年Q3-净销售额万',
    net_sales_2025_q4 DECIMAL(18, 2) COMMENT '2025年Q4-净销售额万',
    
    -- 2026年季度净销售额（单位：万）
    net_sales_2026_q1 DECIMAL(18, 2) COMMENT '2026年Q1-净销售额万',
    net_sales_2026_q2 DECIMAL(18, 2) COMMENT '2026年Q2-净销售额万',
    
    -- 2026年Q2漏斗金额（单位：万）
    funnel_inner_2026_q2 DECIMAL(18, 2) COMMENT '2026年Q2-漏斗内金额万',
    funnel_outer_2026_q2 DECIMAL(18, 2) COMMENT '2026年Q2-漏斗外金额万（不含线索）',
    
    -- 2026年Q3漏斗金额（单位：万）
    funnel_inner_2026_q3 DECIMAL(18, 2) COMMENT '2026年Q3-漏斗内金额万',
    funnel_outer_2026_q3 DECIMAL(18, 2) COMMENT '2026年Q3-漏斗外金额万（不含线索）',
    
    -- 2026年Q4漏斗金额（单位：万）
    funnel_inner_2026_q4 DECIMAL(18, 2) COMMENT '2026年Q4-漏斗内金额万',
    funnel_outer_2026_q4 DECIMAL(18, 2) COMMENT '2026年Q4-漏斗外金额万（不含线索）',
    
    -- 业务机会字段
    opportunity_count_lead_stage INT COMMENT '业务机会数-线索阶段',
    
    -- 创建时间字段（系统自动生成）
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    
    -- 主键
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='重要客户信息表';

-- 创建索引（可选，根据实际查询需求调整）
CREATE INDEX idx_key_customer_code ON ods_key_customer(key_customer_code);
CREATE INDEX idx_key_customer_name ON ods_key_customer(key_customer_name);
CREATE INDEX idx_category ON ods_key_customer(category);
CREATE INDEX idx_industry ON ods_key_customer(industry_category);

-- 完成提示
SELECT 'ods_key_customer table created successfully!' AS message;
