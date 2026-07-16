// ── 环境变量优先，config.js 兜底 ──────────────────────────────────────────
// 每个配置项优先取 Vite 环境变量（由 .env.{mode} 注入），找不到则用此处的默认值。
// 用法：import { BASE_URL, SQLBOT_SDK_URL, SQLBOT_EMBEDDED_ID } from '../config.js'

// 接口基准地址
export const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

// SQLBot 嵌入式 SDK 脚本地址
export const SQLBOT_SDK_URL =
  import.meta.env.VITE_SQLBOT_SDK_URL ??
  'http://117.50.190.52:8020/xpack_static/sqlbot-embedded-dynamic.umd.js'

// SQLBot 嵌入式部件 ID
export const SQLBOT_EMBEDDED_ID =
  import.meta.env.VITE_SQLBOT_EMBEDDED_ID ?? '7483341968974548992'
