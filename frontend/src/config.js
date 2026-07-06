// ─────────────────────────────────────────────────────────────────────────────
// 前端请求地址统一配置
// 切换后端环境时，只需修改下方的 ACTIVE_PRESET，无需改动任何业务请求代码。
// 所有请求（axios 实例与散落的 fetch 调用）均引用此处导出的 BASE_URL。
// ─────────────────────────────────────────────────────────────────────────────

// 预设的后端服务地址（不含 /api 路由段）
const API_PRESETS = {
  // 远程后端
  remote: 'http://192.168.159.22:28080',
  // 本地开发后端
  local: 'http://localhost:8000',
}

// 当前启用的预设：'remote' | 'local'
const ACTIVE_PRESET = 'local'

// 统一导出的请求根地址
export const BASE_URL = API_PRESETS[ACTIVE_PRESET]
