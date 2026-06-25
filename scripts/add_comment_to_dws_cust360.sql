-- ============================================================
-- 为 dws_customer_360 表添加字段注释
-- 说明：仅添加注释，不修改表结构，不增删数据
-- ============================================================

ALTER TABLE `dws_customer_360`
  MODIFY COLUMN `id` BIGINT AUTO_INCREMENT COMMENT '自增主键',
  MODIFY COLUMN `customer_name` VARCHAR(255) NOT NULL COMMENT '标准化客户名称（客户池主键）',
  MODIFY COLUMN `industry` VARCHAR(128) COMMENT '行业（CRM优先->线索->致趣）',
  MODIFY COLUMN `region` VARCHAR(128) COMMENT '区域/省份',
  MODIFY COLUMN `owner_name` VARCHAR(128) COMMENT '负责人（商机所有人频次最高）',
  MODIFY COLUMN `campaign_tag` VARCHAR(255) DEFAULT '企业彩光ICT' COMMENT '专项标签',
  MODIFY COLUMN `purchase_stage` VARCHAR(64) COMMENT '采购阶段（取最高阶段商机）',
  MODIFY COLUMN `forecast_type` VARCHAR(64) COMMENT '预测类别（最高阶段）',
  MODIFY COLUMN `role_coverage` VARCHAR(16) COMMENT '关键角色覆盖 x/4',
  MODIFY COLUMN `role_detail` JSON COMMENT '已覆盖角色列表',
  MODIFY COLUMN `intent_score` INT DEFAULT 0 COMMENT '合作意向分 0-100',
  MODIFY COLUMN `intent_level` VARCHAR(16) COMMENT '合作意向等级 高/中/低',
  MODIFY COLUMN `interaction_count_30d` INT DEFAULT 0 COMMENT '近30天互动次数',
  MODIFY COLUMN `interaction_count_total` INT DEFAULT 0 COMMENT '总互动次数',
  MODIFY COLUMN `last_interaction_time` DATETIME COMMENT '最近互动时间',
  MODIFY COLUMN `last_interaction_channel` VARCHAR(64) COMMENT '最近互动渠道',
  MODIFY COLUMN `top_channels` JSON COMMENT '渠道分布统计',
  MODIFY COLUMN `active_opp_count` INT DEFAULT 0 COMMENT '在途商机数（未取消/未丢单）',
  MODIFY COLUMN `active_opp_amount` DECIMAL(20,4) DEFAULT 0 COMMENT '在途商机总金额(万元)',
  MODIFY COLUMN `funnel_opp_count` INT DEFAULT 0 COMMENT '漏斗内商机数',
  MODIFY COLUMN `won_amount` DECIMAL(20,4) DEFAULT 0 COMMENT '近2年成交金额(万元)',
  MODIFY COLUMN `highest_stage_opp` JSON COMMENT '最高阶段商机快照',
  MODIFY COLUMN `contact_count` INT DEFAULT 0 COMMENT '联系人总数',
  MODIFY COLUMN `mobile_count` INT DEFAULT 0 COMMENT '关联手机号数',
  MODIFY COLUMN `product_categories` JSON COMMENT '历史下单产品线',
  MODIFY COLUMN `is_existing_customer` TINYINT DEFAULT 0 COMMENT '是否老客户（历史成交>0）',
  MODIFY COLUMN `source_tables` JSON COMMENT '数据来源表列表',
  MODIFY COLUMN `data_coverage` JSON COMMENT '各表匹配数量统计',
  MODIFY COLUMN `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间';
