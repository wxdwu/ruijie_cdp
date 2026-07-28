-- 客户列表筛选：白名单 / 黑名单（正则规则表）—— 已废弃，仅供历史参考。
-- 自 2026-07-26 起，白/黑名单规则改为直接写在 Python 模块中
--   （app/services/common/company_whitelist.py、app/services/common/company_blacklist.py），
--   不再从数据库读取，因此无需创建/写入下表。
-- 运行时由 customer_service._apply_customer_filters 直接引用上述 Python 常量。

CREATE TABLE IF NOT EXISTS company_whitelist (
  id         INT          AUTO_INCREMENT PRIMARY KEY,
  pattern    VARCHAR(512) NOT NULL COMMENT 'MySQL REGEXP 正则，命中即视为合法客户并保留',
  note       VARCHAR(255) DEFAULT NULL,
  created_at DATETIME     DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='客户白名单（合法公司名正则）';

CREATE TABLE IF NOT EXISTS company_blacklist (
  id         INT          AUTO_INCREMENT PRIMARY KEY,
  pattern    VARCHAR(512) NOT NULL COMMENT 'MySQL REGEXP 正则，命中且无数据(保命条件)即剔除',
  note       VARCHAR(255) DEFAULT NULL,
  created_at DATETIME     DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='客户黑名单（非法/脏数据正则）';

-- 示例：从数据库层追加特例（按需取消注释执行）
-- INSERT INTO company_whitelist (pattern, note) VALUES ('^某特殊品牌$', '硬编码补充的合法特例');
-- INSERT INTO company_blacklist (pattern, note) VALUES ('^明显非法词$', '明显非法特例');
