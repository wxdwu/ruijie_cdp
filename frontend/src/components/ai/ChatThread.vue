<template>
  <div class="chat-thread">
    <div
      v-for="(message, index) in messages"
      :key="index"
      :class="['message', message.role]"
    >
      <div class="message-avatar">
        <span v-if="message.role === 'user'">👤</span>
        <span v-else>🤖</span>
      </div>
      <div class="message-content">
        <div class="message-text" v-html="renderMarkdown(message.text)"></div>
        <EntityChips
          v-if="message.role === 'assistant' && message.entities"
          :entities="message.entities"
          class="message-entities"
        />
        
        <!-- 显示查询结果（仅当有数据时显示蓝色框） -->
        <div v-if="message.role === 'assistant' && message.result && hasDataResult(message)" class="message-result">
          <!-- 主表结果 -->
          <div 
            v-if="message.result.customers && message.result.customers.items && message.result.customers.items.length > 0" 
            class="result-summary clickable"
            :class="{ active: isPanelOpen && activeResultId === message.result?.query }"
            @click="$emit('show-result', message.result)"
          >
            <span class="result-count">📊 找到 {{ getResultCount(message.result, 'customers') }} 条数据</span>
            <span class="expand-hint">{{ isPanelOpen && activeResultId === message.result?.query ? '✓ 已显示' : '点击查看详情 ▶' }}</span>
          </div>
          
          <!-- 其他表结果 -->
          <div 
            v-if="message.result.data && message.result.data.items && message.result.data.items.length > 0" 
            class="result-summary clickable"
            :class="{ active: isPanelOpen && activeResultId === message.result?.query }"
            @click="$emit('show-result', message.result)"
          >
            <span class="result-count">📊 找到 {{ getResultCount(message.result, 'data') }} 条数据</span>
            <span class="expand-hint">{{ isPanelOpen && activeResultId === message.result?.query ? '✓ 已显示' : '点击查看详情 ▶' }}</span>
          </div>
        </div>
      </div>
    </div>
    <div v-if="loading" class="message assistant">
      <div class="message-avatar">🤖</div>
      <div class="message-content">
        <div class="typing-indicator">
          <span></span>
          <span></span>
          <span></span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'
import EntityChips from './EntityChips.vue'

interface ChatResult {
  query: string
  entities: Record<string, any>
  response: string
  customers: {
    items: any[]
    total: number
    page: number
    page_size: number
  }
  target_table?: string
  data?: {
    items: any[]
    total: number
    page: number
    page_size: number
  }
}

interface Message {
  role: 'user' | 'assistant'
  text: string
  entities?: Record<string, any>
  result?: ChatResult
}

const props = defineProps<{
  messages: Message[]
  loading?: boolean
  activeResultId?: string
  isPanelOpen?: boolean
}>()

// 定义事件
defineEmits<{
  (e: 'show-result', result: ChatResult): void
}>()

// 初始化 markdown-it
const md = new MarkdownIt({
  html: false,  // 不允许 HTML 标签
  breaks: true,  // 将换行符转换为 <br>
  linkify: true,  // 自动识别链接
})

// 渲染 markdown 函数
function renderMarkdown(text: string): string {
  if (!text) return ''
  const html = md.render(text)
  return DOMPurify.sanitize(html)
}

// 获取结果的实际数量（使用 items.length 而不是 total）
function getResultCount(result: ChatResult, type: 'customers' | 'data'): number {
  if (type === 'customers') {
    return result.customers?.items?.length || 0
  } else {
    return result.data?.items?.length || 0
  }
}

// 判断消息是否有有效的数据结果（用于决定是否显示筛选标签）
function hasDataResult(message: Message): boolean {
  const r = message.result
  if (!r) return false
  const customerCount = r.customers?.items?.length || 0
  const dataCount = r.data?.items?.length || 0
  return customerCount > 0 || dataCount > 0
}
</script>

<style scoped>
.chat-thread {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 16px 0;
}

.message {
  display: flex;
  gap: 12px;
  max-width: 90%;
}

.message.user {
  align-self: flex-end;
  flex-direction: row-reverse;
}

.message.assistant {
  align-self: flex-start;
}

.message-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  flex-shrink: 0;
}

.message.user .message-avatar {
  background: var(--primary);
}

.message.assistant .message-avatar {
  background: var(--surface);
}

.message-content {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.message-text {
  padding: 12px 16px;
  border-radius: 12px;
  line-height: 1.6;
  background: var(--surface);
  color: var(--text);
  border-bottom-left-radius: 4px;
}

.message.user .message-text {
  background: var(--primary);
  color: white;
  border-bottom-right-radius: 4px;
}

/* Markdown 渲染样式 */
.message-text :deep(p) {
  margin: 0 0 8px 0;
}

.message-text :deep(p:last-child) {
  margin-bottom: 0;
}

.message-text :deep(strong) {
  font-weight: 700;
  color: inherit;
}

.message-text :deep(em) {
  font-style: italic;
}

.message-text :deep(ul), .message-text :deep(ol) {
  margin: 8px 0;
  padding-left: 20px;
}

.message-text :deep(li) {
  margin: 4px 0;
}

.message-text :deep(code) {
  background: rgba(0, 0, 0, 0.05);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.9em;
}

.message-text :deep(pre) {
  background: rgba(0, 0, 0, 0.05);
  padding: 12px;
  border-radius: 8px;
  overflow-x: auto;
  margin: 8px 0;
}

.message-text :deep(pre code) {
  background: none;
  padding: 0;
}

.message-text :deep(blockquote) {
  border-left: 3px solid var(--primary);
  padding-left: 12px;
  margin: 8px 0;
  color: var(--muted);
}

.message-text :deep(a) {
  color: var(--primary);
  text-decoration: underline;
}

.message-entities {
  margin-top: 4px;
}

.message-result {
  margin-top: 12px;
  padding: 12px;
  background: var(--background);
  border-radius: 8px;
  border: 1px solid var(--border);
}

.result-summary {
  display: flex;
  align-items: center;
  gap: 8px;
}

.result-summary.clickable {
  cursor: pointer;
  padding: 8px 4px;
  border-radius: 6px;
  transition: all 0.2s ease;
}

.result-summary.clickable:hover,
.result-summary.active {
  background: rgba(59, 130, 246, 0.1);
}

.result-summary.active {
  border-color: var(--primary);
}

.result-summary.active .result-count {
  color: var(--primary);
}

.result-count {
  font-size: 14px;
  font-weight: 600;
  color: var(--primary);
}

.expand-hint {
  font-size: 12px;
  color: var(--muted);
  opacity: 0.7;
  transition: opacity 0.2s;
}

.result-summary.clickable:hover .expand-hint {
  opacity: 1;
}

.typing-indicator {
  display: flex;
  gap: 4px;
  padding: 12px 16px;
  background: var(--surface);
  border-radius: 12px;
  border-bottom-left-radius: 4px;
}

.typing-indicator span {
  width: 8px;
  height: 8px;
  background: var(--muted);
  border-radius: 50%;
  animation: bounce 1.4s infinite ease-in-out;
}

.typing-indicator span:nth-child(1) {
  animation-delay: -0.32s;
}

.typing-indicator span:nth-child(2) {
  animation-delay: -0.16s;
}

@keyframes bounce {
  0%, 80%, 100% {
    transform: scale(0.8);
    opacity: 0.5;
  }
  40% {
    transform: scale(1);
    opacity: 1;
  }
}
</style>
