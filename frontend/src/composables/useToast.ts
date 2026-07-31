// 轻量全局消息提示（toast） composable
// 仅用于前端交互反馈，不涉及任何业务逻辑。
import { reactive } from "vue"

export type ToastType = "success" | "error" | "warning" | "info"

export interface ToastItem {
  id: number
  type: ToastType
  title: string
  detail?: string
  duration: number
}

// 模块级单例状态，所有组件共享同一队列
const state = reactive<{ list: ToastItem[] }>({ list: [] })
let seq = 0

function remove(id: number): void {
  const idx = state.list.findIndex((t) => t.id === id)
  if (idx !== -1) state.list.splice(idx, 1)
}

function push(type: ToastType, title: string, detail?: string, duration = 4000): number {
  const id = ++seq
  state.list.push({ id, type, title, detail, duration })
  // 自动关闭交由 ToastContainer 根据进度条动画结束（animationend）驱动，
  // 以便支持“鼠标悬停暂停关闭”的主流交互，这里不再自管定时器。
  return id
}

export function useToast() {
  return {
    success: (title: string, detail?: string) => push("success", title, detail),
    error: (title: string, detail?: string) => push("error", title, detail, 6000),
    warning: (title: string, detail?: string) => push("warning", title, detail),
    info: (title: string, detail?: string) => push("info", title, detail),
    remove,
  }
}

export function useToastState() {
  return state
}

// 从 fetch 的 Response 中提取可读的错误原因，兼容 FastAPI 的 {detail} 及其它格式
export async function extractError(response: Response): Promise<string> {
  let text = ""
  try {
    const data = await response.json()
    text =
      data.detail ||
      data.message ||
      data.error ||
      data.msg ||
      JSON.stringify(data)
  } catch {
    try {
      text = await response.text()
    } catch {
      text = ""
    }
  }
  if (!text) text = `请求失败（HTTP ${response.status}）`
  return String(text)
}
