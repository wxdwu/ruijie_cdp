-- dws_customer_360 字段注释
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

-- dws_contact_mapping 字段注释
ALTER TABLE `dws_contact_mapping`
  MODIFY COLUMN `id` BIGINT AUTO_INCREMENT COMMENT '自增主键',
  MODIFY COLUMN `customer_name` VARCHAR(255) NOT NULL COMMENT '所属标准客户名称',
  MODIFY COLUMN `contact_name` VARCHAR(128) COMMENT '联系人姓名',
  MODIFY COLUMN `mobile` VARCHAR(64) COMMENT '手机号（跨系统关联键）',
  MODIFY COLUMN `email` VARCHAR(255) COMMENT '邮箱',
  MODIFY COLUMN `department` VARCHAR(128) COMMENT '部门',
  MODIFY COLUMN `position` VARCHAR(128) COMMENT '职位',
  MODIFY COLUMN `purchase_role` VARCHAR(64) COMMENT 'CRM采购角色',
  MODIFY COLUMN `role_category` VARCHAR(32) COMMENT '角色分类 拍板者/决策者/评估者/采购推动者/普通',
  MODIFY COLUMN `source_table` VARCHAR(64) COMMENT '来源表',
  MODIFY COLUMN `linkflow_contact_id` BIGINT COMMENT 'Linkflow联系人ID',
  MODIFY COLUMN `zhique_matched` TINYINT DEFAULT 0 COMMENT '是否在致趣中匹配到',
  MODIFY COLUMN `etl_time` DATETIME COMMENT '源表最新ETL时间',
  MODIFY COLUMN `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间';

-- dws_contact_360 字段注释
ALTER TABLE `dws_contact_360`
  MODIFY COLUMN `id` BIGINT AUTO_INCREMENT COMMENT '自增主键',
  MODIFY COLUMN `customer_id` BIGINT NOT NULL COMMENT '关联dws_customer_360.id',
  MODIFY COLUMN `contact_name` VARCHAR(128) COMMENT '联系人姓名',
  MODIFY COLUMN `mobile` VARCHAR(64) COMMENT '手机号',
  MODIFY COLUMN `email` VARCHAR(255) COMMENT '邮箱',
  MODIFY COLUMN `department` VARCHAR(128) COMMENT '部门',
  MODIFY COLUMN `position` VARCHAR(128) COMMENT '职位',
  MODIFY COLUMN `purchase_role` VARCHAR(64) COMMENT '采购角色',
  MODIFY COLUMN `role_category` VARCHAR(32) COMMENT '角色分类',
  MODIFY COLUMN `interaction_count` INT DEFAULT 0 COMMENT '总互动次数',
  MODIFY COLUMN `interaction_count_30d` INT DEFAULT 0 COMMENT '近30天互动次数',
  MODIFY COLUMN `last_interaction_time` DATETIME COMMENT '最近互动时间',
  MODIFY COLUMN `top_content_types` JSON COMMENT '内容类型兴趣Top',
  MODIFY COLUMN `product_interests` JSON COMMENT '产品兴趣',
  MODIFY COLUMN `activity_level` VARCHAR(16) COMMENT '活跃度 高/中/低',
  MODIFY COLUMN `intent_level` VARCHAR(16) COMMENT '合作意向',
  MODIFY COLUMN `lead_stage` VARCHAR(64) COMMENT '线索阶段',
  MODIFY COLUMN `source_tables` JSON COMMENT '来源表',
  MODIFY COLUMN `linkflow_contact_id` BIGINT COMMENT 'Linkflow联系人ID',
  MODIFY COLUMN `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间';

-- dws_interaction_detail 字段注释
ALTER TABLE `dws_interaction_detail`
  MODIFY COLUMN `id` BIGINT AUTO_INCREMENT COMMENT '自增主键',
  MODIFY COLUMN `customer_name` VARCHAR(255) NOT NULL COMMENT '所属客户名',
  MODIFY COLUMN `contact_name` VARCHAR(128) COMMENT '联系人姓名',
  MODIFY COLUMN `mobile` VARCHAR(64) COMMENT '手机号',
  MODIFY COLUMN `source_table` VARCHAR(64) COMMENT '来源表',
  MODIFY COLUMN `channel` VARCHAR(64) COMMENT '渠道分类 email/web/event/wechat',
  MODIFY COLUMN `behavior_type` VARCHAR(128) COMMENT '原始行为类型',
  MODIFY COLUMN `content` VARCHAR(512) COMMENT '行为内容/标题',
  MODIFY COLUMN `event_time` DATETIME COMMENT '行为发生时间',
  MODIFY COLUMN `is_high_value` TINYINT DEFAULT 0 COMMENT '是否高价值行为（留资/咨询等）',
  MODIFY COLUMN `source_id` BIGINT COMMENT '源表主键ID（用于去重）',
  MODIFY COLUMN `etl_time` DATETIME COMMENT '源ETL时间';

-- dws_review_queue 字段注释
ALTER TABLE `dws_review_queue`
  MODIFY COLUMN `id` BIGINT AUTO_INCREMENT COMMENT '自增主键',
  MODIFY COLUMN `review_type` VARCHAR(32) NOT NULL COMMENT '审核类型 company_merge/contact_merge/data_quality',
  MODIFY COLUMN `candidate_a` VARCHAR(500) COMMENT '候选A名称',
  MODIFY COLUMN `candidate_b` VARCHAR(500) COMMENT '候选B名称',
  MODIFY COLUMN `match_score` DECIMAL(5,2) COMMENT '综合匹配置信分 0-1',
  MODIFY COLUMN `evidence` JSON COMMENT '匹配证据',
  MODIFY COLUMN `status` VARCHAR(16) DEFAULT 'pending' COMMENT '状态 pending/confirmed/rejected/auto_merged',
  MODIFY COLUMN `reviewer` VARCHAR(64) COMMENT '审核人',
  MODIFY COLUMN `reviewed_at` DATETIME COMMENT '审核时间',
  MODIFY COLUMN `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间';

-- dws_sync_meta 字段注释
ALTER TABLE `dws_sync_meta`
  MODIFY COLUMN `table_name` VARCHAR(128) NOT NULL COMMENT 'ODS表名',
  MODIFY COLUMN `last_sync_time` DATETIME NOT NULL COMMENT '上次同步截止ETL时间',
  MODIFY COLUMN `last_run_time` DATETIME NOT NULL COMMENT '上次执行时间',
  MODIFY COLUMN `rows_synced` INT DEFAULT 0 COMMENT '上次同步行数',
  MODIFY COLUMN `status` VARCHAR(16) DEFAULT 'success' COMMENT '状态 success/error';