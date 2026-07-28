-- MySQL dump 10.13  Distrib 8.0.46, for Linux (x86_64)
--
-- Host: 127.0.0.1    Database: app_cdp
-- ------------------------------------------------------
-- Server version	8.4.10

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Current Database: `app_cdp`
--

CREATE DATABASE /*!32312 IF NOT EXISTS*/ `app_cdp` /*!40100 DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci */ /*!80016 DEFAULT ENCRYPTION='N' */;

USE `app_cdp`;

--
-- Table structure for table `bench_interaction_detail`
--

DROP TABLE IF EXISTS `bench_interaction_detail`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `bench_interaction_detail` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `customer_name` varchar(255) NOT NULL COMMENT '所属客户名',
  `contact_name` varchar(128) DEFAULT NULL COMMENT '联系人姓名',
  `mobile` varchar(64) DEFAULT NULL COMMENT '手机号',
  `source_table` varchar(64) DEFAULT NULL COMMENT '来源表',
  `channel` varchar(64) DEFAULT NULL COMMENT '渠道分类 email/web/event/wechat',
  `behavior_type` varchar(128) DEFAULT NULL COMMENT '原始行为类型',
  `content` varchar(512) DEFAULT NULL COMMENT '行为内容/标题',
  `event_time` datetime DEFAULT NULL COMMENT '行为发生时间',
  `is_high_value` tinyint DEFAULT '0' COMMENT '是否高价值行为（留资/咨询等）',
  `source_id` bigint DEFAULT NULL COMMENT '源表主键ID（用于去重）',
  `etl_time` datetime DEFAULT NULL COMMENT '源ETL时间',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
  `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '记录更新时间',
  `sync_batch_id` bigint DEFAULT '0' COMMENT '同步批次ID，用于增量同步删除检测',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_source_id` (`source_table`,`source_id`),
  KEY `idx_customer` (`customer_name`),
  KEY `idx_mobile` (`mobile`),
  KEY `idx_time` (`event_time`),
  KEY `idx_channel` (`channel`),
  KEY `idx_id_sync_batch` (`sync_batch_id`)
) ENGINE=InnoDB AUTO_INCREMENT=416971 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `bench_linkflow_contacts`
--

DROP TABLE IF EXISTS `bench_linkflow_contacts`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `bench_linkflow_contacts` (
  `contact_id` varchar(255) NOT NULL,
  `mobile_phone` varchar(255) DEFAULT NULL,
  `name` varchar(255) DEFAULT NULL,
  `customer_name` varchar(255) DEFAULT NULL,
  PRIMARY KEY (`contact_id`),
  KEY `idx_mobile` (`mobile_phone`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `dws_contact_360`
--

DROP TABLE IF EXISTS `dws_contact_360`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `dws_contact_360` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `customer_id` bigint NOT NULL COMMENT '关联dws_customer_360.id',
  `contact_name` varchar(128) DEFAULT NULL COMMENT '联系人姓名',
  `mobile` varchar(64) DEFAULT NULL COMMENT '手机号',
  `email` varchar(255) DEFAULT NULL COMMENT '邮箱',
  `department` varchar(128) DEFAULT NULL COMMENT '部门',
  `position` varchar(128) DEFAULT NULL COMMENT '职位',
  `purchase_role` varchar(64) DEFAULT NULL COMMENT '采购角色',
  `role_category` varchar(32) DEFAULT NULL COMMENT '角色分类',
  `interaction_count` int DEFAULT '0' COMMENT '总互动次数',
  `interaction_count_30d` int DEFAULT '0' COMMENT '近30天互动次数',
  `last_interaction_time` datetime DEFAULT NULL COMMENT '最近互动时间',
  `top_content_types` json DEFAULT NULL COMMENT '内容类型兴趣Top',
  `product_interests` json DEFAULT NULL COMMENT '产品兴趣',
  `activity_level` varchar(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL COMMENT '活跃度 高/中/低，参考值为''high''/''medium''/''low''',
  `intent_level` varchar(16) DEFAULT NULL COMMENT '合作意向',
  `lead_stage` varchar(64) DEFAULT NULL COMMENT '线索阶段',
  `source_tables` json DEFAULT NULL COMMENT '来源表',
  `linkflow_contact_id` bigint DEFAULT NULL COMMENT 'Linkflow联系人ID',
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `sync_batch_id` bigint DEFAULT '0' COMMENT '同步批次ID，用于增量同步删除检测',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_customer_mobile` (`customer_id`,`contact_name`,`mobile`),
  KEY `idx_role` (`role_category`)
) ENGINE=InnoDB AUTO_INCREMENT=8192 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `dws_contact_360_backup`
--

DROP TABLE IF EXISTS `dws_contact_360_backup`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `dws_contact_360_backup` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `customer_id` bigint NOT NULL COMMENT '关联dws_customer_360.id',
  `contact_name` varchar(128) DEFAULT NULL COMMENT '联系人姓名',
  `mobile` varchar(64) DEFAULT NULL COMMENT '手机号',
  `email` varchar(255) DEFAULT NULL COMMENT '邮箱',
  `department` varchar(128) DEFAULT NULL COMMENT '部门',
  `position` varchar(128) DEFAULT NULL COMMENT '职位',
  `purchase_role` varchar(64) DEFAULT NULL COMMENT '采购角色',
  `role_category` varchar(32) DEFAULT NULL COMMENT '角色分类',
  `interaction_count` int DEFAULT '0' COMMENT '总互动次数',
  `interaction_count_30d` int DEFAULT '0' COMMENT '近30天互动次数',
  `last_interaction_time` datetime DEFAULT NULL COMMENT '最近互动时间',
  `top_content_types` json DEFAULT NULL COMMENT '内容类型兴趣Top',
  `product_interests` json DEFAULT NULL COMMENT '产品兴趣',
  `activity_level` varchar(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL COMMENT '活跃度 高/中/低，参考值为''high''/''medium''/''low''',
  `intent_level` varchar(16) DEFAULT NULL COMMENT '合作意向',
  `lead_stage` varchar(64) DEFAULT NULL COMMENT '线索阶段',
  `source_tables` json DEFAULT NULL COMMENT '来源表',
  `linkflow_contact_id` bigint DEFAULT NULL COMMENT 'Linkflow联系人ID',
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `sync_batch_id` bigint DEFAULT '0' COMMENT '同步批次ID，用于增量同步删除检测',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_customer_mobile` (`customer_id`,`contact_name`,`mobile`),
  KEY `idx_role` (`role_category`)
) ENGINE=InnoDB AUTO_INCREMENT=8192 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `dws_contact_mapping`
--

DROP TABLE IF EXISTS `dws_contact_mapping`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `dws_contact_mapping` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `customer_name` varchar(255) NOT NULL COMMENT '所属标准客户名称',
  `contact_name` varchar(128) DEFAULT NULL COMMENT '联系人姓名',
  `mobile` varchar(64) DEFAULT NULL COMMENT '手机号（跨系统关联键）',
  `email` varchar(255) DEFAULT NULL COMMENT '邮箱',
  `department` varchar(128) DEFAULT NULL COMMENT '部门',
  `position` varchar(128) DEFAULT NULL COMMENT '职位',
  `purchase_role` varchar(64) DEFAULT NULL COMMENT 'CRM采购角色',
  `role_category` varchar(32) DEFAULT NULL COMMENT '角色分类 拍板者/决策者/评估者/采购推动者/普通',
  `source_table` varchar(64) DEFAULT NULL COMMENT '来源表',
  `linkflow_contact_id` bigint DEFAULT NULL COMMENT 'Linkflow联系人ID',
  `zhique_matched` tinyint DEFAULT '0' COMMENT '是否在致趣中匹配到',
  `etl_time` datetime DEFAULT NULL COMMENT '源表最新ETL时间',
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `sync_batch_id` bigint DEFAULT '0' COMMENT '同步批次ID，用于增量同步删除检测',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_customer_mobile` (`customer_name`,`mobile`),
  KEY `idx_mobile` (`mobile`),
  KEY `idx_linkflow_id` (`linkflow_contact_id`),
  KEY `idx_cm_mobile` (`mobile`),
  KEY `idx_cm_custname` (`customer_name`),
  KEY `idx_cm_sync_batch` (`sync_batch_id`)
) ENGINE=InnoDB AUTO_INCREMENT=4096 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `dws_contact_mapping_backup`
--

DROP TABLE IF EXISTS `dws_contact_mapping_backup`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `dws_contact_mapping_backup` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `customer_name` varchar(255) NOT NULL COMMENT '所属标准客户名称',
  `contact_name` varchar(128) DEFAULT NULL COMMENT '联系人姓名',
  `mobile` varchar(64) DEFAULT NULL COMMENT '手机号（跨系统关联键）',
  `email` varchar(255) DEFAULT NULL COMMENT '邮箱',
  `department` varchar(128) DEFAULT NULL COMMENT '部门',
  `position` varchar(128) DEFAULT NULL COMMENT '职位',
  `purchase_role` varchar(64) DEFAULT NULL COMMENT 'CRM采购角色',
  `role_category` varchar(32) DEFAULT NULL COMMENT '角色分类 拍板者/决策者/评估者/采购推动者/普通',
  `source_table` varchar(64) DEFAULT NULL COMMENT '来源表',
  `linkflow_contact_id` bigint DEFAULT NULL COMMENT 'Linkflow联系人ID',
  `zhique_matched` tinyint DEFAULT '0' COMMENT '是否在致趣中匹配到',
  `etl_time` datetime DEFAULT NULL COMMENT '源表最新ETL时间',
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `sync_batch_id` bigint DEFAULT '0' COMMENT '同步批次ID，用于增量同步删除检测',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_customer_mobile` (`customer_name`,`mobile`),
  KEY `idx_mobile` (`mobile`),
  KEY `idx_linkflow_id` (`linkflow_contact_id`),
  KEY `idx_cm_mobile` (`mobile`),
  KEY `idx_cm_custname` (`customer_name`),
  KEY `idx_cm_sync_batch` (`sync_batch_id`)
) ENGINE=InnoDB AUTO_INCREMENT=4096 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `dws_customer_360`
--

DROP TABLE IF EXISTS `dws_customer_360`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `dws_customer_360` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `customer_name` varchar(255) NOT NULL,
  `industry` varchar(128) DEFAULT NULL,
  `region` varchar(128) DEFAULT NULL,
  `owner_name` varchar(128) DEFAULT NULL,
  `campaign_tag` varchar(255) DEFAULT '企业彩光ICT',
  `purchase_stage` varchar(64) DEFAULT NULL,
  `forecast_type` varchar(64) DEFAULT NULL,
  `role_coverage` varchar(16) DEFAULT NULL,
  `role_detail` json DEFAULT NULL,
  `intent_score` int DEFAULT '0',
  `intent_level` varchar(16) DEFAULT NULL,
  `interaction_count_30d` int DEFAULT '0',
  `interaction_count_total` int DEFAULT '0',
  `last_interaction_time` datetime DEFAULT NULL,
  `last_interaction_channel` varchar(64) DEFAULT NULL,
  `top_channels` json DEFAULT NULL,
  `active_opp_count` int DEFAULT '0',
  `active_opp_amount` decimal(20,4) DEFAULT '0.0000',
  `funnel_opp_count` int DEFAULT '0',
  `won_amount` decimal(20,4) DEFAULT '0.0000',
  `highest_stage_opp` json DEFAULT NULL,
  `contact_count` int DEFAULT '0',
  `mobile_count` int DEFAULT '0',
  `product_categories` json DEFAULT NULL,
  `is_existing_customer` tinyint DEFAULT '0',
  `source_tables` json DEFAULT NULL,
  `data_coverage` json DEFAULT NULL,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `sync_batch_id` bigint DEFAULT '0' COMMENT '同步批次ID，用于增量同步删除检测',
  `attribute` varchar(4) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_customer_name` (`customer_name`)
) ENGINE=InnoDB AUTO_INCREMENT=1279 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `dws_customer_360_backup`
--

DROP TABLE IF EXISTS `dws_customer_360_backup`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `dws_customer_360_backup` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `customer_name` varchar(255) NOT NULL,
  `industry` varchar(128) DEFAULT NULL,
  `region` varchar(128) DEFAULT NULL,
  `owner_name` varchar(128) DEFAULT NULL,
  `campaign_tag` varchar(255) DEFAULT '企业彩光ICT',
  `purchase_stage` varchar(64) DEFAULT NULL,
  `forecast_type` varchar(64) DEFAULT NULL,
  `role_coverage` varchar(16) DEFAULT NULL,
  `role_detail` json DEFAULT NULL,
  `intent_score` int DEFAULT '0',
  `intent_level` varchar(16) DEFAULT NULL,
  `interaction_count_30d` int DEFAULT '0',
  `interaction_count_total` int DEFAULT '0',
  `last_interaction_time` datetime DEFAULT NULL,
  `last_interaction_channel` varchar(64) DEFAULT NULL,
  `top_channels` json DEFAULT NULL,
  `active_opp_count` int DEFAULT '0',
  `active_opp_amount` decimal(20,4) DEFAULT '0.0000',
  `funnel_opp_count` int DEFAULT '0',
  `won_amount` decimal(20,4) DEFAULT '0.0000',
  `highest_stage_opp` json DEFAULT NULL,
  `contact_count` int DEFAULT '0',
  `mobile_count` int DEFAULT '0',
  `product_categories` json DEFAULT NULL,
  `is_existing_customer` tinyint DEFAULT '0',
  `source_tables` json DEFAULT NULL,
  `data_coverage` json DEFAULT NULL,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `sync_batch_id` bigint DEFAULT '0' COMMENT '同步批次ID，用于增量同步删除检测',
  `attribute` varchar(4) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_customer_name` (`customer_name`),
  KEY `idx_campaign_industry_customer` (`campaign_tag`,`industry`,`customer_name`)
) ENGINE=InnoDB AUTO_INCREMENT=1279 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `dws_interaction_detail`
--

DROP TABLE IF EXISTS `dws_interaction_detail`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `dws_interaction_detail` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `customer_name` varchar(255) NOT NULL COMMENT '所属客户名',
  `contact_name` varchar(128) DEFAULT NULL COMMENT '联系人姓名',
  `mobile` varchar(64) DEFAULT NULL COMMENT '手机号',
  `source_table` varchar(64) DEFAULT NULL COMMENT '来源表',
  `channel` varchar(64) DEFAULT NULL COMMENT '渠道分类 email/web/event/wechat',
  `behavior_type` varchar(128) DEFAULT NULL COMMENT '原始行为类型',
  `content` varchar(512) DEFAULT NULL COMMENT '行为内容/标题',
  `interaction_content` varchar(100) DEFAULT NULL COMMENT 'Linkflow 行为来源搜索词（props_json->s_term）',
  `event_time` datetime DEFAULT NULL COMMENT '行为发生时间',
  `is_high_value` tinyint DEFAULT '0' COMMENT '是否高价值行为（留资/咨询等）',
  `source_id` bigint DEFAULT NULL COMMENT '源表主键ID（用于去重）',
  `etl_time` datetime DEFAULT NULL COMMENT '源ETL时间',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
  `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '记录更新时间',
  `sync_batch_id` bigint DEFAULT '0' COMMENT '同步批次ID，用于增量同步删除检测',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_source_id` (`source_table`,`source_id`),
  KEY `idx_customer` (`customer_name`),
  KEY `idx_mobile` (`mobile`),
  KEY `idx_time` (`event_time`),
  KEY `idx_channel` (`channel`),
  KEY `idx_id_sync_batch` (`sync_batch_id`),
  KEY `idx_contact_mobile` (`contact_name`,`mobile`)
) ENGINE=InnoDB AUTO_INCREMENT=598007 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `dws_interaction_detail_backup`
--

DROP TABLE IF EXISTS `dws_interaction_detail_backup`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `dws_interaction_detail_backup` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `customer_name` varchar(255) NOT NULL COMMENT '所属客户名',
  `contact_name` varchar(128) DEFAULT NULL COMMENT '联系人姓名',
  `mobile` varchar(64) DEFAULT NULL COMMENT '手机号',
  `source_table` varchar(64) DEFAULT NULL COMMENT '来源表',
  `channel` varchar(64) DEFAULT NULL COMMENT '渠道分类 email/web/event/wechat',
  `behavior_type` varchar(128) DEFAULT NULL COMMENT '原始行为类型',
  `content` varchar(512) DEFAULT NULL COMMENT '行为内容/标题',
  `event_time` datetime DEFAULT NULL COMMENT '行为发生时间',
  `is_high_value` tinyint DEFAULT '0' COMMENT '是否高价值行为（留资/咨询等）',
  `source_id` bigint DEFAULT NULL COMMENT '源表主键ID（用于去重）',
  `etl_time` datetime DEFAULT NULL COMMENT '源ETL时间',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP COMMENT '记录创建时间',
  `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '记录更新时间',
  `sync_batch_id` bigint DEFAULT '0' COMMENT '同步批次ID，用于增量同步删除检测',
  `interaction_content` varchar(100) DEFAULT NULL COMMENT '交互内容',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_source_id` (`source_table`,`source_id`),
  KEY `idx_customer` (`customer_name`),
  KEY `idx_mobile` (`mobile`),
  KEY `idx_time` (`event_time`),
  KEY `idx_channel` (`channel`),
  KEY `idx_id_sync_batch` (`sync_batch_id`),
  KEY `idx_contact_mobile` (`contact_name`,`mobile`),
  KEY `idx_customer_event_time` (`customer_name`,`event_time`),
  KEY `idx_customer_channel_event_time` (`customer_name`,`channel`,`event_time`)
) ENGINE=InnoDB AUTO_INCREMENT=598007 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `dws_review_queue`
--

DROP TABLE IF EXISTS `dws_review_queue`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `dws_review_queue` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `review_type` varchar(32) NOT NULL COMMENT '审核类型 company_merge/contact_merge/data_quality',
  `candidate_a` varchar(500) DEFAULT NULL COMMENT '候选A名称',
  `candidate_b` varchar(500) DEFAULT NULL COMMENT '候选B名称',
  `match_score` decimal(5,2) DEFAULT NULL COMMENT '综合匹配置信分 0-1',
  `evidence` json DEFAULT NULL COMMENT '匹配证据',
  `status` varchar(16) DEFAULT 'pending' COMMENT '状态 pending/confirmed/rejected/auto_merged',
  `reviewer` varchar(64) DEFAULT NULL COMMENT '审核人',
  `reviewed_at` datetime DEFAULT NULL COMMENT '审核时间',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (`id`),
  KEY `idx_status` (`status`),
  KEY `idx_type` (`review_type`)
) ENGINE=InnoDB AUTO_INCREMENT=4 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `dws_sync_log`
--

DROP TABLE IF EXISTS `dws_sync_log`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `dws_sync_log` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `sync_type` varchar(20) NOT NULL COMMENT '同步类型：full-全量，incremental-增量',
  `trigger_by` varchar(50) DEFAULT NULL COMMENT '触发人/触发来源',
  `start_time` timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '同步开始时间',
  `end_time` timestamp NULL DEFAULT NULL COMMENT '同步结束时间',
  `status` varchar(20) NOT NULL COMMENT '执行状态：running-运行中，success-成功，failed-失败',
  `rows_synced` int DEFAULT '0',
  `error_message` text COMMENT '错误信息（失败时有值）',
  `details` json DEFAULT NULL COMMENT '详细统计信息（JSON格式），记录每个步骤/表的受影响行数',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_table_status` (`status`),
  KEY `idx_start_time` (`start_time`)
) ENGINE=InnoDB AUTO_INCREMENT=162 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='同步执行日志表 - 记录每次同步的执行历史，用于问题排查和性能分析';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `dws_sync_meta`
--

DROP TABLE IF EXISTS `dws_sync_meta`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `dws_sync_meta` (
  `table_name` varchar(128) NOT NULL COMMENT 'ODS表名',
  `last_sync_time` datetime NOT NULL COMMENT '上次同步截止ETL时间',
  `last_run_time` datetime NOT NULL COMMENT '上次执行时间',
  `rows_synced` int DEFAULT '0' COMMENT '上次同步行数',
  `status` varchar(16) DEFAULT 'success' COMMENT '状态 success/error',
  `sync_status` varchar(20) DEFAULT 'pending' COMMENT '同步状态：pending-待同步，running-同步中，success-成功，failed-失败',
  `last_success_time` timestamp NULL DEFAULT NULL COMMENT '上次成功同步时间',
  `last_watermark_value` bigint NOT NULL DEFAULT '0' COMMENT 'ID 类字段增量同步的水位：上次同步到的最大 id',
  PRIMARY KEY (`table_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `dws_sync_obs`
--

DROP TABLE IF EXISTS `dws_sync_obs`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `dws_sync_obs` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '主键，自增',
  `table_name` varchar(128) NOT NULL COMMENT '被监控的表名',
  `table_count` bigint NOT NULL DEFAULT '0' COMMENT '该表当前数据量（行数）',
  `create_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '监控运行时间',
  PRIMARY KEY (`id`),
  KEY `idx_table_time` (`table_name`,`create_at`)
) ENGINE=InnoDB AUTO_INCREMENT=206 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='用于监控聚合表数据规模';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `es_sync_state`
--

DROP TABLE IF EXISTS `es_sync_state`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `es_sync_state` (
  `id` int NOT NULL DEFAULT '1',
  `last_sync_time` datetime NOT NULL,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `ods_crm_contact_day`
--

DROP TABLE IF EXISTS `ods_crm_contact_day`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `ods_crm_contact_day` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键ID',
  `contact_name` varchar(64) DEFAULT NULL COMMENT '联系人姓名',
  `customer_name` varchar(255) DEFAULT NULL COMMENT '客户名称',
  `mobile` varchar(32) DEFAULT NULL COMMENT '手机号',
  `email` varchar(128) DEFAULT NULL COMMENT '电子邮件',
  `department` varchar(128) DEFAULT NULL COMMENT '部门',
  `position` varchar(128) DEFAULT NULL COMMENT '职务',
  `purchase_role` varchar(64) DEFAULT NULL COMMENT '采购角色',
  `industry` varchar(64) DEFAULT NULL COMMENT '行业归属',
  `market_segment` varchar(128) DEFAULT NULL COMMENT '细分市场',
  `ruijie_region` varchar(128) DEFAULT NULL COMMENT '锐捷区域',
  `attribute` varchar(32) DEFAULT NULL COMMENT '属性',
  `sales_name` varchar(64) DEFAULT NULL COMMENT '销售姓名',
  `last_visit_time` datetime DEFAULT NULL COMMENT '最新拜访时间',
  `not_visit_days` int DEFAULT NULL COMMENT '未拜访天数',
  `must_follow_tags` varchar(1000) DEFAULT NULL COMMENT '必跟客户标签汇总',
  `etl_time` datetime DEFAULT CURRENT_TIMESTAMP COMMENT 'ETL加载时间',
  PRIMARY KEY (`id`),
  KEY `idx_crm_mobile` (`mobile`),
  KEY `idx_ods_crm_contact_etl` (`etl_time`),
  KEY `idx_crm_custname` (`customer_name`)
) ENGINE=InnoDB AUTO_INCREMENT=6800 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='企业彩光ICP客户-CRM联系人明细日表';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `ods_crm_key_account_output_list_day`
--

DROP TABLE IF EXISTS `ods_crm_key_account_output_list_day`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `ods_crm_key_account_output_list_day` (
  `重客编码` varchar(255) DEFAULT NULL,
  `重客名称` varchar(255) DEFAULT NULL,
  `名称` varchar(255) DEFAULT NULL,
  `工号` varchar(255) DEFAULT NULL,
  `属性` varchar(255) DEFAULT NULL,
  `重客` varchar(255) DEFAULT NULL,
  `二级部门名称` varchar(255) DEFAULT NULL,
  `三级部门名称` varchar(255) DEFAULT NULL,
  `售前重客专家` varchar(255) DEFAULT NULL,
  `客户行业整理` varchar(255) DEFAULT NULL,
  `分类` varchar(255) DEFAULT NULL,
  `2026-净销售额万` double DEFAULT NULL,
  `漏斗内金额万` double DEFAULT NULL,
  `漏斗外金额万（不含线索）` double DEFAULT NULL,
  `2025-25年同期净销售额` double DEFAULT NULL,
  `2024-净销售额万` double DEFAULT NULL,
  `2025-净销售额万` double DEFAULT NULL,
  `2023-净销售额万` double DEFAULT NULL,
  `2025年Q1-净销售额万` double DEFAULT NULL,
  `2025年Q2-净销售额万` double DEFAULT NULL,
  `2025年Q3-净销售额万` double DEFAULT NULL,
  `2025年Q4-净销售额万` double DEFAULT NULL,
  `2026年Q1-净销售额万` double DEFAULT NULL,
  `2026年Q2-净销售额万` double DEFAULT NULL,
  `2026年Q2-漏斗内金额万` double DEFAULT NULL,
  `2026年Q2-漏斗外金额万（不含线索）` double DEFAULT NULL,
  `2026年Q3-漏斗内金额万` double DEFAULT NULL,
  `2026年Q3-漏斗外金额万（不含线索）` double DEFAULT NULL,
  `2026年Q4-漏斗内金额万` double DEFAULT NULL,
  `2026年Q4-漏斗外金额万（不含线索）` double DEFAULT NULL,
  `26年产出大于等于30万` double DEFAULT NULL,
  `同期大于等于30万` double DEFAULT NULL,
  `重客新老客户` varchar(255) DEFAULT NULL,
  `25年重客新老客户` varchar(255) DEFAULT NULL,
  `确保金额（万）` double DEFAULT NULL,
  `优势金额（万）` double DEFAULT NULL,
  `可能+金额（万）` double DEFAULT NULL,
  `无线产品事业部-产品线订单金额（万）` double DEFAULT NULL,
  `交换产品事业部-产品线订单金额（万）` double DEFAULT NULL,
  `路由产品事业部-产品线订单金额（万）` double DEFAULT NULL,
  `数据中心网络事业群-产品线订单金额（万）` double DEFAULT NULL,
  `云桌面产品事业部-产品线订单金额（万）` double DEFAULT NULL,
  `安全产品事业部-产品线订单金额（万）` double DEFAULT NULL,
  `SID产品事业部-产品线订单金额（万）` double DEFAULT NULL,
  `身份管理产品事业部-产品线订单金额（万）` double DEFAULT NULL,
  `EDN事业部-产品线订单金额（万）` double DEFAULT NULL,
  `睿智事业部-产品线订单金额（万）` double DEFAULT NULL,
  `其他-产品线订单金额（万）` double DEFAULT NULL,
  `服务产品事业部-产品线订单金额（万）` double DEFAULT NULL,
  `26年产品线订单总金额（万）` double DEFAULT NULL,
  `产出大于30万产品线条数` double DEFAULT NULL,
  `time` timestamp NULL DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC COMMENT='重客产出清单';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `ods_crm_lead_data_day`
--

DROP TABLE IF EXISTS `ods_crm_lead_data_day`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `ods_crm_lead_data_day` (
  `线索编号` text,
  `月份` text,
  `年度` text,
  `联系电话` text,
  `线索来源细分` text,
  `CRM编号` text,
  `线索当前负责人` text,
  `省份` text,
  `预估下单金额（元）` double DEFAULT NULL,
  `产品线` text,
  `城市` text,
  `大区` text,
  `活动分类` text,
  `活动类别` text,
  `活动名称` text,
  `活动申请编号` text,
  `客户单位` text,
  `客户类别` text,
  `客户姓名` text,
  `线索分级` text,
  `线索分类` text,
  `线索来源类型` text,
  `线索来源大类` text,
  `邮箱` text,
  `有效线索反馈结果` text,
  `职务` text,
  `线索获得日期` date DEFAULT NULL,
  `行业` text,
  `无效原因` text,
  `线索当前所在节点` text,
  `线索状态` text,
  `挂起线索标记` text,
  `线索录入人` text,
  `自行跟进标记` text,
  `内销反馈时长` double DEFAULT NULL,
  `内销负责人` text,
  `线索闭环流程` text,
  `备注` text,
  `项目时间` date DEFAULT NULL,
  `销售机会名称` text,
  `内销反馈时间` date DEFAULT NULL,
  `线索三级来源` text,
  `线索闭环负责人` text,
  `内销岗位匹配` text,
  `行业IMC` text,
  `有线无线IMC` text,
  `云桌面IMC` text,
  `安全IMC` text,
  `睿智IMC` text,
  `无线IMC` text,
  `跨行业IMC` text,
  `交换机运营1` text,
  `交换机运营2` text,
  `路由器运营` text,
  `无线运营` text,
  `云桌面运营` text,
  `安全运营` text,
  `睿智运营` text,
  `身份管理运营` text,
  `CRM跟进状态` text,
  `线索最终状态` text,
  `线索关闭原因` text,
  `最终公司名称` text,
  `一级来源` text,
  `最新修改日期` date DEFAULT NULL,
  `线索重复个数` double DEFAULT NULL,
  `CRM编号重复标识` text,
  `业务机会重复标识` text,
  `业务机会转化` text,
  `创建日期-转化` date DEFAULT NULL,
  `预计下单日期-转化` date DEFAULT NULL,
  `预计开标日期-转化` date DEFAULT NULL,
  `是否进入漏斗(只用于报表展示)` text,
  `丢单/取消日期` text,
  `取消/丢单` text,
  `丢单/取消原因说明（新）` text,
  `预测类别(*)` text,
  `业务机会所有人名称` text,
  `业务类型` text,
  `商机来源` text,
  `重客` text,
  `线索作用` text,
  `预估金额-CRM调整` double DEFAULT NULL,
  `线索实际下单金额-更新` double DEFAULT NULL,
  `来源类型-去重` text,
  `最新活动记录时间-转化` date DEFAULT NULL,
  `客户名` text,
  `是否彩光项目` text,
  `未来窗来源类型` text,
  `区域负责人` text,
  `销管BP姓名` text,
  `对应销售一级部门` text,
  `活动形式-更新` text,
  `主要目标对象` text,
  `活动分类-更新` text,
  `业务机会名称` text,
  `商机区域` text,
  `零散下单金额` double DEFAULT NULL,
  `是否无线项目` text,
  `赢率` text,
  `是否EDN项目` text,
  `行业-EBG` text,
  `线索来源类型-EBG` text,
  `云桌面商机标识` text,
  `新老客户` text,
  `属性` text,
  `订单金额` double DEFAULT NULL,
  `订单-产品线名称` text,
  `是否EBG彩光项目` text,
  `总部与区域` text,
  `线索客户类型` text,
  `是否云桌面VDI线索` text,
  `time` timestamp NULL DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC COMMENT='线索合并-全部，来自智梅的BI数据源';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `ods_crm_opportunity_data_day`
--

DROP TABLE IF EXISTS `ods_crm_opportunity_data_day`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `ods_crm_opportunity_data_day` (
  `业务机会编码_new` text,
  `是否彩光项目` text,
  `是否无线项目` text,
  `是否EDN项目` text,
  `云桌面商机标识` text,
  `出货金额` double DEFAULT NULL,
  `金额` double DEFAULT NULL,
  `业务机会实际下单金额（元）` double DEFAULT NULL,
  `预计下单金额（自定义）` double DEFAULT NULL,
  `FIELD32` text,
  `部门` text,
  `产品名称` text,
  `产品型号` text,
  `承诺` text,
  `创建日期` text,
  `大区` text,
  `当前是否生效` text,
  `丢单/取消日期` text,
  `丢单/取消原因说明` text,
  `否投融资/ICT项目` text,
  `客户采购阶段` text,
  `客户档案ID` text,
  `客户名` text,
  `年月日` text,
  `区域` text,
  `是否需要备货` text,
  `是否智能建筑（弱电）项目` text,
  `首级集成商类型` text,
  `首级集成商名称` text,
  `售前工程师` text,
  `售前人员总结` text,
  `细分市场` text,
  `线索编号` text,
  `项目整体预算（元）` text,
  `项目状态标记` text,
  `销售产品代码` text,
  `销售人员工作计划及总结2020（业务机会）` text,
  `要求发货日期` text,
  `要求发货月份` text,
  `业务机会编码` text,
  `业务机会名称` text,
  `业务机会所有人名称` text,
  `业务机会填写人ID` text,
  `应用场合` text,
  `与锐捷有关的预算（元）` text,
  `预测类别(*)` text,
  `预计开标日期` text,
  `预计推进至漏斗内的时间` text,
  `预计下单日期` text,
  `主管批注` text,
  `主推解决方案` text,
  `业务单元` text,
  `当前是否生效1` text,
  `客户进入阶段` text,
  `是否“进千企”客户` text,
  `客户分类说明` text,
  `产品数量` double DEFAULT NULL,
  `是否为下半月承诺` text,
  `项目主导/协作` text,
  `关联主导商机` text,
  `业务单元-新` text,
  `是否成功设计极简光` text,
  `客户规模` double DEFAULT NULL,
  `客户预计投资计划(万元)` double DEFAULT NULL,
  `行业归属-新` text,
  `可能涉及的服务产品` text,
  `是否大屏项目` text,
  `不含镁光` text,
  `项目报备二级渠道` text,
  `设备使用方行业名称` text,
  `设备最终使用方` text,
  `销往国家/地区` text,
  `是否我司协助客户上报预算/规划` text,
  `上报预算涉及的我司金额` text,
  `涉及的产品类别` text,
  `是否进入漏斗(只用于报表展示)` text,
  `是否进入漏斗` text,
  `取消/丢单` text,
  `丢单/取消原因说明（新）` text,
  `商机来源` text,
  `重客` text,
  `业务类型` text,
  `客户属性` text,
  `最新活动记录时间` text,
  `最新修改人` text,
  `是否关联线索` text,
  `最新修改日` text,
  `数据来源` text,
  `项目预期金额` double DEFAULT NULL,
  `预计下单日期-转化` date DEFAULT NULL,
  `创建日期-转化` date DEFAULT NULL,
  `预计开标日期-转化` date DEFAULT NULL,
  `最新活动记录时间-转化` date DEFAULT NULL,
  `项目报备服务商` text,
  `净折扣目标(%)` text,
  `场景归属` text,
  `场景/架构名称` text,
  `业务机会编码_NEW1` text,
  `审批状态` text,
  `赢率` text,
  `审批状态1` text,
  `是否活动中` text,
  `阶段更新时间` text,
  `项目报备服务商名称` text,
  `市场活动` text,
  `本次销售自盘填写` text,
  `本次盘点信息` text,
  `上次盘点信息` text,
  `上次销售自盘记录` text,
  `产品类别` text,
  `EDN商机标识` text,
  `订单-产品线名称` text,
  `订单创建日期` date DEFAULT NULL,
  `订单金额` double DEFAULT NULL,
  `是否EBG彩光项目` text,
  `新老客户` text,
  `属性` text,
  `time` timestamp NULL DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC COMMENT='CRM业务数据-整理-编号去重，来自智梅的BI数据源';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `ods_crm_opportunity_day`
--

DROP TABLE IF EXISTS `ods_crm_opportunity_day`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `ods_crm_opportunity_day` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键ID',
  `customer_name` varchar(255) DEFAULT NULL COMMENT '客户名称',
  `opp_name` varchar(500) DEFAULT NULL COMMENT '业务机会名称',
  `opp_code` varchar(64) DEFAULT NULL COMMENT '业务机会编码',
  `create_date` date DEFAULT NULL COMMENT '创建日期',
  `is_funnel` varchar(16) DEFAULT NULL COMMENT '是否进入漏斗',
  `forecast_type` varchar(32) DEFAULT NULL COMMENT '预测类别',
  `amount_10k` decimal(20,4) DEFAULT NULL COMMENT '金额(万元)',
  `expect_bid_date` date DEFAULT NULL COMMENT '预计开标日期',
  `expect_order_date` date DEFAULT NULL COMMENT '预计下单日期',
  `win_rate` decimal(5,2) DEFAULT NULL COMMENT '赢率(%)',
  `actual_order_amount_10k` decimal(20,4) DEFAULT NULL COMMENT '实际下单金额(万元)',
  `is_cancel_lost` varchar(16) DEFAULT NULL COMMENT '是否取消/丢单',
  `cancel_reason` text COMMENT '丢单/取消原因',
  `industry` varchar(64) DEFAULT NULL COMMENT '行业归属',
  `owner_name` varchar(64) DEFAULT NULL COMMENT '业务机会所有人',
  `region` varchar(64) DEFAULT NULL COMMENT '大区',
  `area` varchar(64) DEFAULT NULL COMMENT '区域',
  `cancel_date` date DEFAULT NULL COMMENT '丢单/取消日期',
  `customer_stage` varchar(64) DEFAULT NULL COMMENT '客户进入阶段',
  `product_category` varchar(128) DEFAULT NULL COMMENT '产品类别',
  `is_colorlight_project` tinyint DEFAULT NULL COMMENT '是否彩光项目',
  `is_wireless_project` tinyint DEFAULT NULL COMMENT '是否无线项目',
  `is_edn_project` tinyint DEFAULT NULL COMMENT '是否EDN项目',
  `is_cloud_desktop_project` tinyint DEFAULT NULL COMMENT '是否云桌面项目',
  `business_type` varchar(64) DEFAULT NULL COMMENT '业务类型',
  `opp_source` varchar(128) DEFAULT NULL COMMENT '商机来源',
  `marketing_activity` varchar(255) DEFAULT NULL COMMENT '市场活动',
  `data_source` varchar(64) DEFAULT NULL COMMENT '数据来源',
  `report_provider_name` varchar(255) DEFAULT NULL COMMENT '项目报备服务商名称',
  `last_activity_time` datetime DEFAULT NULL COMMENT '最新活动记录时间',
  `win_rate_1` decimal(5,2) DEFAULT NULL COMMENT '赢率2(%)',
  `is_active` tinyint DEFAULT NULL COMMENT '是否活动中',
  `order_create_date` date DEFAULT NULL COMMENT '订单创建日期',
  `order_product_line` varchar(128) DEFAULT NULL COMMENT '订单产品线名称',
  `order_amount_10k` decimal(20,4) DEFAULT NULL COMMENT '订单金额(万元)',
  `etl_time` datetime DEFAULT CURRENT_TIMESTAMP COMMENT 'ETL加载时间',
  PRIMARY KEY (`id`),
  KEY `idx_opp_custname` (`customer_name`)
) ENGINE=InnoDB AUTO_INCREMENT=52962 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='CRM业务机会数据日表';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `ods_key_customer`
--

DROP TABLE IF EXISTS `ods_key_customer`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `ods_key_customer` (
  `id` bigint unsigned NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `category` varchar(255) DEFAULT NULL COMMENT '分类',
  `key_customer_name` varchar(500) DEFAULT NULL COMMENT '重客名称',
  `key_customer_code` varchar(100) DEFAULT NULL COMMENT '重客编码',
  `customer_name` varchar(500) DEFAULT NULL COMMENT '名称（客户名称）',
  `employee_id` varchar(100) DEFAULT NULL COMMENT '工号',
  `customer_type_old_new` varchar(100) DEFAULT NULL COMMENT '重客新老客户',
  `customer_type_25_old_new` varchar(100) DEFAULT NULL COMMENT '25年重客新老客户',
  `industry_category` varchar(255) DEFAULT NULL COMMENT '客户行业整理',
  `associated_customer_name` varchar(500) DEFAULT NULL COMMENT '客户名',
  `associated_customer_code` varchar(100) DEFAULT NULL COMMENT '重客关联客户编码-整理',
  `department_level3` varchar(255) DEFAULT NULL COMMENT '三级部门名称',
  `department_level3_alt` varchar(255) DEFAULT NULL COMMENT '三级部门名称1',
  `pre_sales_expert` varchar(255) DEFAULT NULL COMMENT '售前重客专家',
  `attribute` varchar(100) DEFAULT NULL COMMENT '属性',
  `is_key_customer` varchar(10) DEFAULT NULL COMMENT '重客',
  `sales_volume_category` varchar(100) DEFAULT NULL COMMENT '重客销量统计分类',
  `is_valid` varchar(50) DEFAULT NULL COMMENT '是否有效',
  `net_sales_2026` decimal(18,2) DEFAULT NULL COMMENT '2026-净销售额万',
  `net_sales_2025_same_period` decimal(18,2) DEFAULT NULL COMMENT '2025-25年同期净销售额',
  `net_sales_2025` decimal(18,2) DEFAULT NULL COMMENT '2025-净销售额万',
  `net_sales_2024` decimal(18,2) DEFAULT NULL COMMENT '2024-净销售额万',
  `net_sales_2023` decimal(18,2) DEFAULT NULL COMMENT '2023-净销售额万',
  `net_sales_2022` decimal(18,2) DEFAULT NULL COMMENT '2022-净销售额万',
  `funnel_inner_amount` decimal(18,2) DEFAULT NULL COMMENT '漏斗内金额万',
  `confirmed_amount` decimal(18,2) DEFAULT NULL COMMENT '确保金额（万）',
  `advantage_amount` decimal(18,2) DEFAULT NULL COMMENT '优势金额（万）',
  `possible_amount` decimal(18,2) DEFAULT NULL COMMENT '可能+金额（万）',
  `funnel_outer_amount` decimal(18,2) DEFAULT NULL COMMENT '漏斗外金额万（不含线索）',
  `net_sales_2025_q1` decimal(18,2) DEFAULT NULL COMMENT '2025年Q1-净销售额万',
  `net_sales_2025_q2` decimal(18,2) DEFAULT NULL COMMENT '2025年Q2-净销售额万',
  `net_sales_2025_q3` decimal(18,2) DEFAULT NULL COMMENT '2025年Q3-净销售额万',
  `net_sales_2025_q4` decimal(18,2) DEFAULT NULL COMMENT '2025年Q4-净销售额万',
  `net_sales_2026_q1` decimal(18,2) DEFAULT NULL COMMENT '2026年Q1-净销售额万',
  `net_sales_2026_q2` decimal(18,2) DEFAULT NULL COMMENT '2026年Q2-净销售额万',
  `funnel_inner_2026_q2` decimal(18,2) DEFAULT NULL COMMENT '2026年Q2-漏斗内金额万',
  `funnel_outer_2026_q2` decimal(18,2) DEFAULT NULL COMMENT '2026年Q2-漏斗外金额万（不含线索）',
  `funnel_inner_2026_q3` decimal(18,2) DEFAULT NULL COMMENT '2026年Q3-漏斗内金额万',
  `funnel_outer_2026_q3` decimal(18,2) DEFAULT NULL COMMENT '2026年Q3-漏斗外金额万（不含线索）',
  `funnel_inner_2026_q4` decimal(18,2) DEFAULT NULL COMMENT '2026年Q4-漏斗内金额万',
  `funnel_outer_2026_q4` decimal(18,2) DEFAULT NULL COMMENT '2026年Q4-漏斗外金额万（不含线索）',
  `opportunity_count_lead_stage` int DEFAULT NULL COMMENT '业务机会数-线索阶段',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_key_customer_name` (`key_customer_name`),
  KEY `idx_category` (`category`),
  KEY `idx_industry` (`industry_category`)
) ENGINE=InnoDB AUTO_INCREMENT=3021 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `ods_linkflow_contacts_day`
--

DROP TABLE IF EXISTS `ods_linkflow_contacts_day`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `ods_linkflow_contacts_day` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键ID',
  `contact_id` bigint DEFAULT NULL COMMENT '联系人ID',
  `anonymous_id` varchar(128) DEFAULT NULL COMMENT '匿名访客ID',
  `name` varchar(255) DEFAULT NULL COMMENT '联系人姓名',
  `nickname` varchar(255) DEFAULT NULL COMMENT '联系人昵称',
  `gender` varchar(64) DEFAULT NULL COMMENT '性别',
  `date_of_birthday` varchar(64) DEFAULT NULL COMMENT '生日',
  `avatar` varchar(1024) DEFAULT NULL COMMENT '头像地址',
  `mobile_phone` varchar(64) DEFAULT NULL COMMENT '手机号',
  `home_phone` varchar(64) DEFAULT NULL COMMENT '家庭电话',
  `email` varchar(255) DEFAULT NULL COMMENT '邮箱',
  `country` varchar(128) DEFAULT NULL COMMENT '国家',
  `state_name` varchar(128) DEFAULT NULL COMMENT '省份或州',
  `street` varchar(255) DEFAULT NULL COMMENT '街道地址',
  `city` varchar(128) DEFAULT NULL COMMENT '城市',
  `postal_code` varchar(64) DEFAULT NULL COMMENT '邮编',
  `comments` longtext COMMENT '备注',
  `user_name` varchar(255) DEFAULT NULL COMMENT '用户名',
  `title` varchar(255) DEFAULT NULL COMMENT '职位',
  `website` varchar(1024) DEFAULT NULL COMMENT '网站',
  `company` varchar(255) DEFAULT NULL COMMENT '公司',
  `industry` varchar(255) DEFAULT NULL COMMENT '行业',
  `department` varchar(255) DEFAULT NULL COMMENT '部门',
  `id_card` varchar(128) DEFAULT NULL COMMENT '证件号',
  `utm_json` longtext COMMENT 'UTM信息JSON',
  `props_json` longtext COMMENT '扩展属性JSON',
  `is_anonymous` tinyint DEFAULT NULL COMMENT '是否匿名联系人',
  `date_created` datetime DEFAULT NULL COMMENT '创建时间',
  `last_updated` datetime DEFAULT NULL COMMENT '更新时间',
  `raw_json` longtext COMMENT '原始返回JSON',
  `etl_time` datetime DEFAULT NULL COMMENT 'ETL入库时间',
  PRIMARY KEY (`id`),
  KEY `idx_lf_cid` (`contact_id`),
  KEY `idx_lf_mobile` (`mobile_phone`)
) ENGINE=InnoDB AUTO_INCREMENT=78328 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Linkflow联系人原始数据日表';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `ods_linkflow_events_day`
--

DROP TABLE IF EXISTS `ods_linkflow_events_day`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `ods_linkflow_events_day` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键ID',
  `contact_id` bigint DEFAULT NULL COMMENT '联系人ID',
  `event_name` varchar(255) DEFAULT NULL COMMENT '事件名称',
  `event_id` bigint DEFAULT NULL COMMENT '事件ID',
  `extra_id` bigint DEFAULT NULL COMMENT '事件游标ID',
  `ver` int DEFAULT NULL COMMENT '事件版本号',
  `channel_id` bigint DEFAULT NULL COMMENT '渠道ID',
  `event_date_ms` bigint DEFAULT NULL COMMENT '事件发生时间戳毫秒值',
  `trigger_flow` tinyint DEFAULT NULL COMMENT '是否触发流程',
  `date_created` datetime DEFAULT NULL COMMENT '创建时间',
  `last_updated` datetime DEFAULT NULL COMMENT '更新时间',
  `utm_json` longtext COMMENT 'UTM信息JSON',
  `props_json` longtext COMMENT '扩展属性JSON',
  `raw_json` longtext COMMENT '原始返回JSON',
  `etl_time` datetime DEFAULT NULL COMMENT 'ETL入库时间',
  PRIMARY KEY (`id`),
  KEY `idx_lfe_cid` (`contact_id`),
  KEY `idx_lfe_etl` (`etl_time`)
) ENGINE=InnoDB AUTO_INCREMENT=20214482 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Linkflow联系人事件原始数据日表';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `ods_marketing_lead_day`
--

DROP TABLE IF EXISTS `ods_marketing_lead_day`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `ods_marketing_lead_day` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键ID',
  `lead_code` varchar(128) DEFAULT NULL COMMENT '线索编号',
  `lead_obtain_date` date DEFAULT NULL COMMENT '线索获得日期',
  `lead_source_type` varchar(128) DEFAULT NULL COMMENT '线索来源类型',
  `lead_source_detail` varchar(255) DEFAULT NULL COMMENT '线索来源细分',
  `lead_source_level3` varchar(255) DEFAULT NULL COMMENT '线索三级来源',
  `valid_lead_feedback` varchar(128) DEFAULT NULL COMMENT '有效线索反馈结果',
  `opp_conversion` varchar(128) DEFAULT NULL COMMENT '业务机会转化状态',
  `crm_code` varchar(128) DEFAULT NULL COMMENT 'CRM编号',
  `is_funnel_report` varchar(32) DEFAULT NULL COMMENT '是否进入漏斗(报表)',
  `forecast_type` varchar(64) DEFAULT NULL COMMENT '预测类别',
  `expect_opp_amount_10k` decimal(20,4) DEFAULT NULL COMMENT '业务机会预估金额(万元)',
  `actual_order_amount_10k` decimal(20,4) DEFAULT NULL COMMENT '实际下单金额(万元)',
  `is_cancel_lost` varchar(32) DEFAULT NULL COMMENT '是否取消/丢单',
  `cancel_reason` text COMMENT '丢单/取消原因',
  `opp_customer_name` varchar(500) DEFAULT NULL COMMENT '业务机会客户名',
  `opp_owner_name` varchar(128) DEFAULT NULL COMMENT '业务机会所有人',
  `crm_dup_flag` varchar(64) DEFAULT NULL COMMENT 'CRM编号重复标识',
  `invalid_reason` varchar(1000) DEFAULT NULL COMMENT '无效原因',
  `lead_close_reason` varchar(1000) DEFAULT NULL COMMENT '线索关闭原因',
  `lead_function` varchar(128) DEFAULT NULL COMMENT '线索作用',
  `province` varchar(64) DEFAULT NULL COMMENT '省份',
  `current_owner_name` varchar(128) DEFAULT NULL COMMENT '线索当前负责人',
  `industry` varchar(128) DEFAULT NULL COMMENT '行业',
  `product_line` varchar(255) DEFAULT NULL COMMENT '产品线',
  `is_key_customer` varchar(32) DEFAULT NULL COMMENT '是否重点客户',
  `customer_company` varchar(500) DEFAULT NULL COMMENT '客户单位',
  `customer_name` varchar(255) DEFAULT NULL COMMENT '客户姓名',
  `contact_phone` varchar(64) DEFAULT NULL COMMENT '联系电话',
  `email` varchar(255) DEFAULT NULL COMMENT '邮箱',
  `final_company_name` varchar(500) DEFAULT NULL COMMENT '最终公司名称',
  `domestic_sales_owner` varchar(128) DEFAULT NULL COMMENT '内销负责人',
  `domestic_feedback_hours` int DEFAULT NULL COMMENT '内销反馈时长(小时)',
  `last_modify_date` date DEFAULT NULL COMMENT '最新修改日期',
  `lead_creator` varchar(128) DEFAULT NULL COMMENT '线索录入人',
  `remark` text COMMENT '备注',
  `future_window_source_type` varchar(128) DEFAULT NULL COMMENT '未来窗来源类型',
  `activity_apply_code` varchar(128) DEFAULT NULL COMMENT '活动申请编号',
  `is_colorlight_project` tinyint DEFAULT NULL COMMENT '是否彩光项目',
  `is_wireless_project` tinyint DEFAULT NULL COMMENT '是否无线项目',
  `is_edn_project` tinyint DEFAULT NULL COMMENT '是否EDN项目',
  `is_cloud_desktop_project` tinyint DEFAULT NULL COMMENT '是否云桌面项目',
  `etl_time` datetime DEFAULT CURRENT_TIMESTAMP COMMENT 'ETL加载时间',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=36181 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='营销线索明细日表';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `ods_ruijie_website_user_day`
--

DROP TABLE IF EXISTS `ods_ruijie_website_user_day`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `ods_ruijie_website_user_day` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键ID',
  `mobile_phone` varchar(64) DEFAULT NULL COMMENT '手机号',
  `user_id` varchar(128) DEFAULT NULL COMMENT '用户ID',
  `user_name` varchar(255) DEFAULT NULL COMMENT '用户名',
  `email` varchar(255) DEFAULT NULL COMMENT '邮箱',
  `user_type` varchar(128) DEFAULT NULL COMMENT '用户类型',
  `user_status` varchar(128) DEFAULT NULL COMMENT '用户状态',
  `company_name` varchar(255) DEFAULT NULL COMMENT '公司名称',
  `register_time` datetime DEFAULT NULL COMMENT '注册时间',
  `industry` varchar(255) DEFAULT NULL COMMENT '行业',
  `city` varchar(128) DEFAULT NULL COMMENT '城市',
  `etl_time` datetime DEFAULT NULL COMMENT 'ETL入库时间',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=135981 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='锐捷官网用户原始数据日表';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `ods_tianrun_customer_profile_day`
--

DROP TABLE IF EXISTS `ods_tianrun_customer_profile_day`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `ods_tianrun_customer_profile_day` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键ID',
  `source_visitor_id` varchar(128) DEFAULT NULL COMMENT '本次查询使用的访客ID',
  `primary_visitor_id` varchar(128) DEFAULT NULL COMMENT '客户资料中的主访客ID',
  `customer_id` bigint DEFAULT NULL COMMENT '客户资料ID',
  `customer_name` varchar(255) DEFAULT NULL COMMENT '客户名称',
  `sex` varchar(64) DEFAULT NULL COMMENT '客户性别',
  `tel_json` longtext COMMENT '客户号码JSON',
  `email` varchar(255) DEFAULT NULL COMMENT '邮箱',
  `address` varchar(1024) DEFAULT NULL COMMENT '地址',
  `level` varchar(255) DEFAULT NULL COMMENT '客户等级',
  `share_type` varchar(64) DEFAULT NULL COMMENT '归属类型',
  `share_name` varchar(255) DEFAULT NULL COMMENT '客户归属',
  `remark` longtext COMMENT '备注',
  `source` varchar(255) DEFAULT NULL COMMENT '客户来源',
  `creator_type` varchar(64) DEFAULT NULL COMMENT '创建人类型',
  `creator_id` bigint DEFAULT NULL COMMENT '创建人ID',
  `modifier_type` varchar(64) DEFAULT NULL COMMENT '更新人类型',
  `modifier_id` bigint DEFAULT NULL COMMENT '更新人ID',
  `last_contact_time` varchar(64) DEFAULT NULL COMMENT '最后一次联系时间',
  `last_contact_type` int DEFAULT NULL COMMENT '最后一次联系类型',
  `customize_json` longtext COMMENT '自定义字段JSON',
  `create_time` varchar(64) DEFAULT NULL COMMENT '创建时间',
  `update_time` varchar(64) DEFAULT NULL COMMENT '更新时间',
  `visitor_ids_json` longtext COMMENT '访客ID列表JSON',
  `creator_name` varchar(255) DEFAULT NULL COMMENT '创建人名称',
  `modifier_name` varchar(255) DEFAULT NULL COMMENT '更新人名称',
  `ib_bridged_number` int DEFAULT NULL COMMENT '呼入接通次数',
  `ob_bridged_number` int DEFAULT NULL COMMENT '呼出接通次数',
  `ob_number` int DEFAULT NULL COMMENT '呼出次数',
  `assign_time` varchar(64) DEFAULT NULL COMMENT '分配时间',
  `external_id` varchar(255) DEFAULT NULL COMMENT '外部企业客户ID',
  `ib_number` int DEFAULT NULL COMMENT '呼入次数',
  `retrieve_flag` int DEFAULT NULL COMMENT '是否为回收客户',
  `retrieve_time` varchar(64) DEFAULT NULL COMMENT '回收时间',
  `queue_without_attribution_json` longtext COMMENT '无归属授权员工组JSON',
  `phase_id` int DEFAULT NULL COMMENT '客户阶段ID',
  `phase_reason_id` int DEFAULT NULL COMMENT '阶段原因ID',
  `promote_source` varchar(255) DEFAULT NULL COMMENT '推广来源',
  `repeat_promote_count` int DEFAULT NULL COMMENT '重复推广次数',
  `last_repeat_promote_time` varchar(64) DEFAULT NULL COMMENT '最近一次重复推广时间',
  `label_ids_json` longtext COMMENT '客户标签ID JSON',
  `enterprise_customer_id` bigint DEFAULT NULL COMMENT '企业客户ID',
  `first_contact_time` varchar(64) DEFAULT NULL COMMENT '首次联系时间',
  `first_cc_contact_time` varchar(64) DEFAULT NULL COMMENT '首次电话联系时间',
  `first_chat_contact_time` varchar(64) DEFAULT NULL COMMENT '首次客服联系时间',
  `last_cc_contact_time` varchar(64) DEFAULT NULL COMMENT '最近一次电话联系时间',
  `last_chat_contact_time` varchar(64) DEFAULT NULL COMMENT '最近一次客服联系时间',
  `chat_number` int DEFAULT NULL COMMENT '客服联系次数',
  `raw_json` longtext COMMENT '原始返回JSON',
  `etl_time` datetime DEFAULT NULL COMMENT 'ETL入库时间',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=376682 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='天润客户资料回灌表';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `ods_tianrun_session_day`
--

DROP TABLE IF EXISTS `ods_tianrun_session_day`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `ods_tianrun_session_day` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键ID',
  `main_unique_id` varchar(128) DEFAULT NULL COMMENT '在线客服会话ID',
  `app_name` varchar(255) DEFAULT NULL COMMENT '接入号名称',
  `start_time_sec` bigint DEFAULT NULL COMMENT '会话开始时间戳秒',
  `end_time_sec` bigint DEFAULT NULL COMMENT '会话结束时间戳秒',
  `is_valid` varchar(64) DEFAULT NULL COMMENT '人工有效性',
  `first_qno` varchar(128) DEFAULT NULL COMMENT '首次进线队列号',
  `first_qname` varchar(255) DEFAULT NULL COMMENT '首次进线队列名称',
  `first_cno` varchar(128) DEFAULT NULL COMMENT '首次接待座席号',
  `first_cname` varchar(255) DEFAULT NULL COMMENT '首次接待座席名称',
  `has_comment` tinyint DEFAULT NULL COMMENT '是否留言',
  `has_agent_ticket` tinyint DEFAULT NULL COMMENT '是否存在座席创建工单',
  `open_type_name` varchar(255) DEFAULT NULL COMMENT '会话发起方式解释',
  `contact_type_name` varchar(255) DEFAULT NULL COMMENT '渠道类型',
  `receive_type_name` varchar(255) DEFAULT NULL COMMENT '接待类型名称',
  `close_reason_name` varchar(255) DEFAULT NULL COMMENT '结束原因',
  `close_status_name` varchar(255) DEFAULT NULL COMMENT '结束状态',
  `repeat_visit_name` varchar(255) DEFAULT NULL COMMENT '重复进线',
  `is_robot_valid_name` varchar(255) DEFAULT NULL COMMENT '机器人有效性',
  `is_valid_name` varchar(255) DEFAULT NULL COMMENT '人工有效性描述',
  `total_duration` bigint DEFAULT NULL COMMENT '会话时长秒',
  `queue_duration` bigint DEFAULT NULL COMMENT '排队时长秒',
  `total_duration_pretty` varchar(64) DEFAULT NULL COMMENT '会话时长格式化',
  `queue_duration_pretty` varchar(64) DEFAULT NULL COMMENT '排队时长格式化',
  `visitor_id` varchar(128) DEFAULT NULL COMMENT '访客ID',
  `visitor_name` varchar(255) DEFAULT NULL COMMENT '访客姓名',
  `visitor_mobile_phone` varchar(128) DEFAULT NULL COMMENT '访客手机号',
  `visitor_email` varchar(255) DEFAULT NULL COMMENT '访客邮箱',
  `customer_name` varchar(255) DEFAULT NULL COMMENT '客户名称',
  `ip` varchar(128) DEFAULT NULL COMMENT 'IP地址',
  `province` varchar(128) DEFAULT NULL COMMENT '省份',
  `city` varchar(128) DEFAULT NULL COMMENT '城市',
  `phone_type_name` varchar(255) DEFAULT NULL COMMENT '手机类型解释',
  `device_type` varchar(128) DEFAULT NULL COMMENT '设备类型',
  `browser` varchar(255) DEFAULT NULL COMMENT '浏览器型号',
  `operating_system` varchar(255) DEFAULT NULL COMMENT '操作系统',
  `search_word` varchar(1024) DEFAULT NULL COMMENT '搜索词',
  `market_keyword` varchar(1024) DEFAULT NULL COMMENT '关键词',
  `first_visit_page_url` longtext COMMENT '着陆页',
  `initiation_page_url` longtext COMMENT '会话发起页',
  `referer_url` longtext COMMENT '来源页',
  `search_engine_name` varchar(255) DEFAULT NULL COMMENT '搜索引擎',
  `utm_medium` varchar(255) DEFAULT NULL COMMENT '推广媒介',
  `utm_plan` varchar(255) DEFAULT NULL COMMENT '推广计划',
  `utm_unit` varchar(255) DEFAULT NULL COMMENT '推广单元',
  `utm_account` varchar(255) DEFAULT NULL COMMENT '推广账户',
  `utm_source` varchar(255) DEFAULT NULL COMMENT '推广来源',
  `session_tags_json` longtext COMMENT '会话标签JSON',
  `visitor_extra_info_json` longtext COMMENT '访客自定义参数JSON',
  `raw_json` longtext COMMENT '原始返回JSON',
  `etl_time` datetime DEFAULT NULL COMMENT 'ETL入库时间',
  PRIMARY KEY (`id`),
  KEY `idx_tr_vid` (`visitor_id`),
  KEY `idx_tr_custname` (`customer_name`)
) ENGINE=InnoDB AUTO_INCREMENT=926271 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='天润在线客服会话记录日表';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `ods_tianrun_session_detail_day`
--

DROP TABLE IF EXISTS `ods_tianrun_session_detail_day`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `ods_tianrun_session_detail_day` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键ID',
  `main_unique_id` varchar(128) DEFAULT NULL COMMENT '在线客服会话ID',
  `detail_unique_id` varchar(128) DEFAULT NULL COMMENT '从会话唯一ID',
  `visitor_id` varchar(128) DEFAULT NULL COMMENT '访客ID',
  `visitor_name` varchar(255) DEFAULT NULL COMMENT '访客姓名',
  `visitor_mobile_phone` varchar(128) DEFAULT NULL COMMENT '访客手机号',
  `visitor_email` varchar(255) DEFAULT NULL COMMENT '访客邮箱',
  `qno` varchar(128) DEFAULT NULL COMMENT '队列号',
  `qname` varchar(255) DEFAULT NULL COMMENT '队列名称',
  `cno` varchar(128) DEFAULT NULL COMMENT '坐席号',
  `cname` varchar(255) DEFAULT NULL COMMENT '座席名称',
  `robot_name` varchar(255) DEFAULT NULL COMMENT '机器人名称',
  `is_valid` tinyint DEFAULT NULL COMMENT '从会话是否有效',
  `client_msg_count` int DEFAULT NULL COMMENT '座席消息数',
  `visitor_msg_count` int DEFAULT NULL COMMENT '访客消息数',
  `robot_msg_count` int DEFAULT NULL COMMENT '机器人消息数',
  `start_time_sec` bigint DEFAULT NULL COMMENT '从会话开始时间戳秒',
  `end_time_sec` bigint DEFAULT NULL COMMENT '从会话结束时间戳秒',
  `type_name` varchar(255) DEFAULT NULL COMMENT '从会话类型名称',
  `detail_source_name` varchar(255) DEFAULT NULL COMMENT '从会话来源',
  `transfer_out_type_name` varchar(255) DEFAULT NULL COMMENT '转出成功类型',
  `transfer_in_type_name` varchar(255) DEFAULT NULL COMMENT '转入成功类型',
  `last_msg_sender_type_name` varchar(255) DEFAULT NULL COMMENT '最后发言人',
  `indicators_name` varchar(255) DEFAULT NULL COMMENT '考核指标',
  `duration_pretty` varchar(64) DEFAULT NULL COMMENT '从会话时长格式化',
  `receive_duration_pretty` varchar(64) DEFAULT NULL COMMENT '从会话接待时长格式化',
  `first_response_duration_pretty` varchar(64) DEFAULT NULL COMMENT '首响时长格式化',
  `max_visitor_wait_duration_pretty` varchar(64) DEFAULT NULL COMMENT '访客最大等待时长格式化',
  `bridge_process_duration_pretty` varchar(64) DEFAULT NULL COMMENT '接入处理时长格式化',
  `is_one_time_solution_pretty` varchar(64) DEFAULT NULL COMMENT '是否一次性解决',
  `investigation_star` int DEFAULT NULL COMMENT '满意度评价',
  `investigation_solve_name` varchar(255) DEFAULT NULL COMMENT '满意度解决状态解释',
  `investigation_remark` longtext COMMENT '满意度备注',
  `investigation_submit_time_sec` bigint DEFAULT NULL COMMENT '满意度评价时间戳秒',
  `investigation_invite_types_name` varchar(255) DEFAULT NULL COMMENT '满意度发起方式',
  `indicators_json` longtext COMMENT '考核指标JSON',
  `robot_tags_json` longtext COMMENT '机器人标签JSON',
  `task_engine_tags_json` longtext COMMENT '机器人任务引擎标签JSON',
  `robot_user_tags_json` longtext COMMENT '机器人用户标签JSON',
  `raw_json` longtext COMMENT '原始返回JSON',
  `etl_time` datetime DEFAULT NULL COMMENT 'ETL入库时间',
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=985632 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='天润在线客服座席机器人会话记录日表';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `ods_zhique_behavior_list_day`
--

DROP TABLE IF EXISTS `ods_zhique_behavior_list_day`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `ods_zhique_behavior_list_day` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键ID',
  `behavior_id` bigint DEFAULT NULL COMMENT '行为记录ID',
  `org_id` varchar(128) DEFAULT NULL COMMENT '组织ID',
  `contact_name` varchar(255) DEFAULT NULL COMMENT '姓名',
  `mobile_phone` varchar(64) DEFAULT NULL COMMENT '手机号',
  `email` varchar(255) DEFAULT NULL COMMENT '邮箱',
  `company_name` varchar(255) DEFAULT NULL COMMENT '公司',
  `group_ids` varchar(1024) DEFAULT NULL COMMENT '分组ID',
  `group_names` varchar(4096) DEFAULT NULL COMMENT '分组名称',
  `tag_names` varchar(1024) DEFAULT NULL COMMENT '标签',
  `industry` varchar(255) DEFAULT NULL COMMENT '行业',
  `customer_type` varchar(255) DEFAULT NULL COMMENT '客户类型',
  `behavior_path` varchar(1024) DEFAULT NULL COMMENT '行为路径',
  `behavior_type` varchar(255) DEFAULT NULL COMMENT '行为类型',
  `behavior_name` varchar(255) DEFAULT NULL COMMENT '行为名称',
  `behavior_count` int DEFAULT NULL COMMENT '行为数量',
  `behavior_time` datetime DEFAULT NULL COMMENT '行为时间',
  `created_at` datetime DEFAULT NULL COMMENT '创建时间',
  `updated_at` datetime DEFAULT NULL COMMENT '更新时间',
  `deleted_at` datetime DEFAULT NULL COMMENT '删除时间',
  `is_deleted` tinyint DEFAULT NULL COMMENT '是否删除',
  `etl_time` datetime DEFAULT NULL COMMENT 'ETL入库时间',
  PRIMARY KEY (`id`),
  KEY `idx_zqb_mobile` (`mobile_phone`)
) ENGINE=InnoDB AUTO_INCREMENT=405414 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='致趣用户行为原始数据日表';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `ods_zhique_contact_day`
--

DROP TABLE IF EXISTS `ods_zhique_contact_day`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `ods_zhique_contact_day` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键ID',
  `related_company` varchar(255) DEFAULT NULL COMMENT '关联公司名称',
  `industry` varchar(64) DEFAULT NULL COMMENT '行业',
  `ruijie_region` varchar(64) DEFAULT NULL COMMENT '锐捷区域',
  `attribute` varchar(32) DEFAULT NULL COMMENT '属性',
  `is_new_customer` varchar(32) DEFAULT NULL COMMENT '新老客户标识',
  `contact_name` varchar(64) DEFAULT NULL COMMENT '联系人姓名',
  `mobile` varchar(32) DEFAULT NULL COMMENT '手机号',
  `email` varchar(128) DEFAULT NULL COMMENT '邮箱',
  `department` varchar(128) DEFAULT NULL COMMENT '部门',
  `position` varchar(128) DEFAULT NULL COMMENT '职务',
  `online_reach_method` varchar(64) DEFAULT NULL COMMENT '线上可触达方式',
  `must_follow_tags` varchar(1000) DEFAULT NULL COMMENT '必跟客户标签汇总',
  `etl_time` datetime DEFAULT CURRENT_TIMESTAMP COMMENT 'ETL加载时间',
  PRIMARY KEY (`id`),
  KEY `idx_zqc_related` (`related_company`),
  KEY `idx_zqc_mobile` (`mobile`)
) ENGINE=InnoDB AUTO_INCREMENT=2402 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='企业彩光ICP客户-致趣联系人明细日表';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `ods_zhique_contact_detail_day`
--

DROP TABLE IF EXISTS `ods_zhique_contact_detail_day`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `ods_zhique_contact_detail_day` (
  `关联公司` text,
  `手机号` text,
  `邮箱` text,
  `姓名` text,
  `职务` text,
  `角色-按职务` text,
  `客户匹配状态` text,
  `必跟客户-汇总` text,
  `25年起彩光触达次数` double DEFAULT NULL,
  `25年起彩光关键互动次数` double DEFAULT NULL,
  `25年起彩光需求线索数` double DEFAULT NULL,
  `行业归属` text,
  `锐捷区域` text,
  `二级部门` text,
  `三级部门` text,
  `名称` text,
  `CRM单位数` double DEFAULT NULL,
  `彩光采购阶段-官网` text,
  `彩光采购阶段` text,
  `彩光ICP客户标识` text,
  `行业-EBG` text,
  `线上可触达方式` text,
  `公司` text,
  `部门` text,
  `用户身份` text,
  `25年无线起触达次数` double DEFAULT NULL,
  `25年起无线关键互动次数` double DEFAULT NULL,
  `25年起EDN触达次数` double DEFAULT NULL,
  `25年起EDN关键互动次数` double DEFAULT NULL,
  `25年起云桌面触达次数` double DEFAULT NULL,
  `25年起云桌面关键互动次数` double DEFAULT NULL,
  `25年起无线需求线索数` double DEFAULT NULL,
  `25年起EDN需求线索数` double DEFAULT NULL,
  `25年起云桌面需求线索数` double DEFAULT NULL,
  `EDN采购阶段` text,
  `无线采购阶段` text,
  `云桌面采购阶段` text,
  `无线ICP客户标识` text,
  `EDN-ICP客户标识` text,
  `云桌面ICP客户标识` text,
  `ICP客户标识-汇总` text,
  `行业-汇总` text,
  `线上客户状态` text,
  `最后内容触达时间` date DEFAULT NULL,
  `关键互动次数` double DEFAULT NULL,
  `属性` text,
  `客户单位致趣状态` text,
  `25年起专特触达次数` double DEFAULT NULL,
  `25年起专特需求线索数` double DEFAULT NULL,
  `专特采购阶段` text,
  `25年起专特关键互动次数` double DEFAULT NULL,
  `专特客户标识` text,
  `新老客户` text,
  `官网内容标签-汇总` text,
  `地址` text,
  `官网最后访问时间` date DEFAULT NULL,
  `最新拜访时间-整理` date DEFAULT NULL,
  `25年起参与过彩光线上活动次数` double DEFAULT NULL,
  `25年起参与彩光线上活动且正向回应次数` double DEFAULT NULL,
  `25年起参与过EDN线上活动次数` double DEFAULT NULL,
  `25年起参与EDN线上活动且正向回应次数` double DEFAULT NULL,
  `25年起参与过无线线上活动次数` double DEFAULT NULL,
  `25年起参与无线线上活动且正向回应次数` double DEFAULT NULL,
  `25年起参与过云桌面线上活动次数` double DEFAULT NULL,
  `25年起参与云桌面线上活动且正向回应次数` double DEFAULT NULL,
  `最后参与活动时间` date DEFAULT NULL,
  `是否有需求-汇总` text,
  `25年起参与过专特线上活动次数` double DEFAULT NULL,
  `25年起参与专特线上活动且正向回应次数` double DEFAULT NULL,
  `线上活动最近参与时间` date DEFAULT NULL,
  `线上活动名称-汇总` text,
  `线下活动最近参与时间` date DEFAULT NULL,
  `线下活动名称-汇总` text,
  `活动激活状态` text,
  `官网激活状态` text,
  `销售激活状态` text,
  `time` timestamp NULL DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci ROW_FORMAT=DYNAMIC COMMENT='致趣联系人明细-整理';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `review_candidate`
--

DROP TABLE IF EXISTS `review_candidate`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `review_candidate` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `review_type` varchar(50) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'company_merge' COMMENT 'company_merge, contact_merge, data_quality',
  `candidate_a_id` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'First candidate ID',
  `candidate_a_name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'First candidate name',
  `candidate_b_id` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'Second candidate ID',
  `candidate_b_name` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'Second candidate name',
  `match_score` decimal(5,2) DEFAULT '0.00' COMMENT 'Overall match score',
  `rule_score` decimal(5,2) DEFAULT '0.00' COMMENT 'Rule-based score',
  `evidence_score` decimal(5,2) DEFAULT '0.00' COMMENT 'Evidence-based score',
  `llm_score` decimal(5,2) DEFAULT '0.00' COMMENT 'LLM similarity score',
  `status` varchar(20) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'pending' COMMENT 'pending, auto_merged, rejected, need_review',
  `evidence` json DEFAULT NULL COMMENT 'Match evidence details',
  `reviewed_by` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'Reviewer username',
  `reviewed_at` datetime DEFAULT NULL COMMENT 'Review timestamp',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_review_type` (`review_type`),
  KEY `idx_status` (`status`),
  KEY `idx_match_score` (`match_score`)
) ENGINE=InnoDB AUTO_INCREMENT=961 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Deduplication review candidates';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `sync_linkflow_state_day`
--

DROP TABLE IF EXISTS `sync_linkflow_state_day`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `sync_linkflow_state_day` (
  `write_target` varchar(32) NOT NULL COMMENT '写入目标: doris|tidb|audit_mysql|dual',
  `contacts_last_max_id` bigint DEFAULT NULL COMMENT '联系人游标',
  `events_last_max_extra_id` bigint DEFAULT NULL COMMENT '事件游标',
  `tianrun_customer_profile_last_count` bigint DEFAULT NULL COMMENT '天润客户资料最近一次同步条数',
  `tianrun_customer_profile_last_sync_time` varchar(64) DEFAULT NULL COMMENT '天润客户资料最近一次同步时间',
  `zhique_window_start` varchar(64) DEFAULT NULL COMMENT '致趣窗口开始时间',
  `zhique_window_end` varchar(64) DEFAULT NULL COMMENT '致趣窗口结束时间',
  `zhique_page_num` int DEFAULT NULL COMMENT '致趣当前页码',
  `website_window_start` varchar(32) DEFAULT NULL COMMENT '官网窗口开始日期',
  `website_window_end` varchar(32) DEFAULT NULL COMMENT '官网窗口结束日期',
  `website_page_num` int DEFAULT NULL COMMENT '官网当前页码',
  `tianrun_session_window_start` varchar(64) DEFAULT NULL COMMENT '天润会话窗口开始时间',
  `tianrun_session_window_end` varchar(64) DEFAULT NULL COMMENT '天润会话窗口结束时间',
  `tianrun_session_page_num` int DEFAULT NULL COMMENT '天润会话当前页码',
  `tianrun_session_detail_window_start` varchar(64) DEFAULT NULL COMMENT '天润明细窗口开始时间',
  `tianrun_session_detail_window_end` varchar(64) DEFAULT NULL COMMENT '天润明细窗口结束时间',
  `tianrun_session_detail_page_num` int DEFAULT NULL COMMENT '天润明细当前页码',
  `state_json` longtext COMMENT '完整状态JSON',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`write_target`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='同步程序最新状态表';
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `tmp_icp_customers`
--

DROP TABLE IF EXISTS `tmp_icp_customers`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `tmp_icp_customers` (
  `customer_name` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '关联公司名称',
  KEY `idx_icp_custname` (`customer_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping routines for database 'app_cdp'
--
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-07-15 16:15:06
