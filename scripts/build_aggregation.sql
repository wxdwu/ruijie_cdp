-- ============================================================
-- CDP Aggregation Layer DDL
-- Target: 192.168.159.22:33307/app_cdp
-- Created: 2026-06-11
-- ============================================================

-- 1. dws_sync_meta - sync state tracking
CREATE TABLE IF NOT EXISTS dws_sync_meta (
  table_name VARCHAR(128) PRIMARY KEY,
  last_sync_time DATETIME NOT NULL,
  last_run_time DATETIME NOT NULL,
  rows_synced INT DEFAULT 0,
  status VARCHAR(16) DEFAULT 'success'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 2. dws_contact_mapping - cross-system contact mapping
CREATE TABLE IF NOT EXISTS dws_contact_mapping (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  customer_name VARCHAR(255) NOT NULL,
  contact_name VARCHAR(128), mobile VARCHAR(64), email VARCHAR(255),
  department VARCHAR(128), position VARCHAR(128),
  purchase_role VARCHAR(64), role_category VARCHAR(32),
  source_table VARCHAR(64), linkflow_contact_id BIGINT,
  zhique_matched TINYINT DEFAULT 0, etl_time DATETIME,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_customer_mobile (customer_name, mobile),
  INDEX idx_mobile (mobile), INDEX idx_linkflow_id (linkflow_contact_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 3. dws_customer_360 - customer aggregation
CREATE TABLE IF NOT EXISTS dws_customer_360 (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  customer_name VARCHAR(255) NOT NULL,
  industry VARCHAR(128), region VARCHAR(128), owner_name VARCHAR(128),
  attribute VARCHAR(4) DEFAULT NULL COMMENT '客户分级 H/M/L/空',
  campaign_tag VARCHAR(255) DEFAULT '企业彩光ICT',
  purchase_stage VARCHAR(64), forecast_type VARCHAR(64),
  role_coverage VARCHAR(16), role_detail JSON,
  intent_score INT DEFAULT 0, intent_level VARCHAR(16),
  interaction_count_30d INT DEFAULT 0, interaction_count_total INT DEFAULT 0,
  last_interaction_time DATETIME, last_interaction_channel VARCHAR(64),
  top_channels JSON,
  active_opp_count INT DEFAULT 0, active_opp_amount DECIMAL(20,4) DEFAULT 0,
  funnel_opp_count INT DEFAULT 0, won_amount DECIMAL(20,4) DEFAULT 0,
  highest_stage_opp JSON, contact_count INT DEFAULT 0, mobile_count INT DEFAULT 0,
  product_categories JSON, is_existing_customer TINYINT DEFAULT 0,
  source_tables JSON, data_coverage JSON,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_customer_name (customer_name),
  INDEX idx_industry (industry), INDEX idx_owner (owner_name),
  INDEX idx_intent (intent_level), INDEX idx_stage (purchase_stage)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 4. dws_contact_360 - contact aggregation
CREATE TABLE IF NOT EXISTS dws_contact_360 (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  customer_id BIGINT NOT NULL,
  contact_name VARCHAR(128), mobile VARCHAR(64), email VARCHAR(255),
  department VARCHAR(128), position VARCHAR(128),
  purchase_role VARCHAR(64), role_category VARCHAR(32),
  interaction_count INT DEFAULT 0, interaction_count_30d INT DEFAULT 0,
  last_interaction_time DATETIME,
  top_content_types JSON, product_interests JSON,
  activity_level VARCHAR(16), intent_level VARCHAR(16), lead_stage VARCHAR(64),
  source_tables JSON, linkflow_contact_id BIGINT,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uk_customer_mobile (customer_id, contact_name, mobile),
  INDEX idx_role (role_category)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 5. dws_interaction_detail - interaction detail
CREATE TABLE IF NOT EXISTS dws_interaction_detail (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  customer_name VARCHAR(255) NOT NULL,
  contact_name VARCHAR(128), mobile VARCHAR(64),
  source_table VARCHAR(64), channel VARCHAR(64),
  behavior_type VARCHAR(128), content VARCHAR(512),
  event_time DATETIME, is_high_value TINYINT DEFAULT 0,
  source_id BIGINT, etl_time DATETIME,
  UNIQUE KEY uk_source_id (source_table, source_id),
  INDEX idx_customer (customer_name), INDEX idx_mobile (mobile),
  INDEX idx_time (event_time), INDEX idx_channel (channel)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 6. dws_review_queue - review queue
CREATE TABLE IF NOT EXISTS dws_review_queue (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  review_type VARCHAR(32) NOT NULL,
  candidate_a VARCHAR(500), candidate_b VARCHAR(500),
  match_score DECIMAL(5,2), evidence JSON,
  status VARCHAR(16) DEFAULT 'pending',
  reviewer VARCHAR(64), reviewed_at DATETIME,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_status (status), INDEX idx_type (review_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;