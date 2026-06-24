<template>
  <div class="ai-chat">
    <div class="main-layout">
      <!-- 左侧/主区域：对话区域 -->
      <div class="chat-panel" :class="{ 'with-panel': showDataPanel }">
        <div class="chat-header">
          <div class="header-content">
            <div>
              <h1>🤖 AI 智能查询</h1>
              <p>用自然语言描述您想查找的客户，我会帮您筛选</p>
            </div>
            <button @click="clearHistory" class="clear-btn" title="清空对话历史">
              🗑️ 清空历史
            </button>
          </div>
        </div>

        <div ref="messagesContainer" class="messages-area">
          <ChatThread 
            :messages="messages" 
            :loading="isLoading" 
            :active-result-id="currentResult?.query"
            :is-panel-open="showDataPanel"
            @show-result="handleShowResult"
          />
        </div>

        <!-- Input Area -->
        <div class="input-area">
          <div class="input-wrapper">
            <textarea
              v-model="inputQuery"
              placeholder="例如：帮我找广东地区医疗行业高意向的客户，互动3次以上..."
              :disabled="isLoading"
              @keydown.enter.prevent="handleSubmit"
              rows="3"
            ></textarea>
            <button
              @click="handleSubmit"
              :disabled="isLoading || !inputQuery.trim()"
              class="send-btn"
            >
              {{ isLoading ? '处理中...' : '发送' }}
            </button>
          </div>
          <div class="input-hints">
            <span>提示：</span>
            <button @click="setExample('医疗行业广东客户')">🏥 医疗行业广东客户</button>
            <button @click="setExample('高意向企业客户')">💼 高意向企业客户</button>
            <button @click="setExample('官网渠道互动5次以上')">🌐 官网渠道互动5次以上</button>
          </div>
        </div>
      </div>

      <!-- 右侧：数据详情面板（可展开/收起） -->
      <transition name="slide-panel">
        <div v-if="showDataPanel && currentResult" class="data-panel">
          <div class="data-panel-header">
            <h3>📊 数据详情</h3>
            <div class="panel-actions">
              <span class="table-name">{{ getTableName(currentResult.target_table) }}</span>
              <button @click="handleExportCurrent" class="export-btn-small">📥 导出</button>
              <button @click="closeDataPanel" class="close-btn" title="关闭面板">×</button>
            </div>
          </div>

          <div class="data-table-container">
            <!-- 主表结果 -->
            <div v-if="currentResult.customers && currentResult.customers.items && currentResult.customers.items.length > 0">
              <DataTable
                :items="paginatedCustomers"
                :total="currentResult.customers.items.length"
                :page="resultPage"
                :page-size="pageSize"
                :show-export="false"
                @page-change="handlePageChange"
                @row-click="handleRowClick"
              />
            </div>

            <!-- 其他表结果 -->
            <div v-if="currentResult.data && currentResult.data.items && currentResult.data.items.length > 0">
              <DataTable
                :items="paginatedData"
                :total="currentResult.data.items.length"
                :page="dataPage"
                :page-size="pageSize"
                :show-export="false"
                @page-change="handlePageChangeData"
                @row-click="handleRowClick"
              />
            </div>
          </div>
        </div>
      </transition>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import ChatThread from '../components/ai/ChatThread.vue'
import DataTable from '../components/ai/DataTable.vue'

const router = useRouter()

interface Message {
  role: 'user' | 'assistant'
  text: string
  entities?: Record<string, any>
  result?: ChatResult
}

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

const STORAGE_KEY = 'ai_chat_history'
const MAX_HISTORY = 10
const PAGE_SIZE = 20

const messages = ref<Message[]>([])
const inputQuery = ref('')
const isLoading = ref(false)
const currentResult = ref<ChatResult | null>(null)
const currentMessageIndex = ref(-1)
const messagesContainer = ref<HTMLElement | null>(null)
const resultPage = ref(1)
const dataPage = ref(1)
const pageSize = ref(PAGE_SIZE)
const showDataPanel = ref(false)  // 是否显示右侧数据面板

// 计算属性：前端分页的客户数据
const paginatedCustomers = computed(() => {
  if (!currentResult.value || !currentResult.value.customers.items) return []
  return currentResult.value.customers.items
})

// 计算属性：前端分页的其他表数据
const paginatedData = computed(() => {
  if (!currentResult.value || !currentResult.value.data || !currentResult.value.data.items) return []
  return currentResult.value.data.items
})

// 从 localStorage 加载历史对话
function loadHistory() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) {
      const history = JSON.parse(saved)
      messages.value = history
      for (let i = history.length - 1; i >= 0; i--) {
        if (history[i].role === 'assistant' && history[i].result) {
          // 不自动显示面板，只加载数据
          resultPage.value = 1
          dataPage.value = 1
          break
        }
      }
    }
  } catch (error) {
    console.error('Failed to load chat history:', error)
  }
}

// 保存对话到 localStorage
function saveHistory() {
  try {
    const recentMessages = messages.value.slice(-MAX_HISTORY * 2)
    localStorage.setItem(STORAGE_KEY, JSON.stringify(recentMessages))
  } catch (error) {
    console.error('Failed to save chat history:', error)
  }
}

// 清空历史对话
function clearHistory() {
  if (confirm('确定要清空所有对话历史吗？')) {
    messages.value = []
    currentResult.value = null
    resultPage.value = 1
    dataPage.value = 1
    showDataPanel.value = false
    localStorage.removeItem(STORAGE_KEY)
  }
}

// 处理点击"查看详情" - 切换面板显示
function handleShowResult(result: ChatResult) {
  if (currentResult.value?.query === result.query && showDataPanel.value) {
    // 如果点击的是已显示的结果，关闭面板
    closeDataPanel()
  } else {
    // 否则显示新结果
    currentResult.value = result
    showDataPanel.value = true
    resultPage.value = 1
    dataPage.value = 1
  }
}

// 关闭数据面板
function closeDataPanel() {
  showDataPanel.value = false
  // 不清空 currentResult，让左侧"已显示"状态能正确恢复为"点击查看详情"
  // currentResult 保留，但面板关闭
}

// 导出当前显示的数据
async function handleExportCurrent() {
  if (!currentResult.value) return
  if (currentResult.value.data && currentResult.value.data.items && currentResult.value.data.items.length > 0) {
    handleExportData()
  } else {
    handleExport()
  }
}

async function handleSubmit() {
  const query = inputQuery.value.trim()
  if (!query || isLoading.value) return

  messages.value.push({ role: 'user', text: query })
  inputQuery.value = ''
  isLoading.value = true
  await nextTick()
  scrollToBottom()

  try {
    const history = messages.value.slice(-10).map(msg => ({ role: msg.role, text: msg.text }))
    const response = await fetch('/api/ai/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, history: history.slice(0, -1) }),
    })

    if (!response.ok) throw new Error('API request failed')

    const result: ChatResult = await response.json()
    currentResult.value = result
    currentMessageIndex.value = messages.value.length
    resultPage.value = 1
    dataPage.value = 1

    messages.value.push({
      role: 'assistant',
      text: result.response,
      entities: result.entities,
      result: result,
    })

    saveHistory()
  } catch (error) {
    messages.value.push({ role: 'assistant', text: '抱歉，处理您的请求时出现了错误，请稍后重试。' })
    console.error('Chat error:', error)
  } finally {
    isLoading.value = false
    await nextTick()
    scrollToBottom()
  }
}

async function handleExport() {
  if (!currentResult.value) return
  try {
    const requestBody: any = {
      query: currentResult.value.query,
      entities: currentResult.value.entities,
      structured_query: currentResult.value.entities,
    }
    if (currentResult.value.target_table) requestBody.target_table = currentResult.value.target_table

    const response = await fetch('/api/ai/chat/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(requestBody),
    })
    if (!response.ok) throw new Error('Export failed')
    const blob = await response.blob()
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `ai_chat_export_${Date.now()}.xlsx`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    window.URL.revokeObjectURL(url)
  } catch (error) {
    console.error('Export error:', error)
    alert('导出失败，请重试')
  }
}

async function handleExportData() {
  if (!currentResult.value || !currentResult.value.target_table) return
  try {
    const requestBody: any = {
      query: currentResult.value.query,
      entities: currentResult.value.entities,
      structured_query: currentResult.value.entities,
      target_table: currentResult.value.target_table,
    }
    const response = await fetch('/api/ai/chat/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(requestBody),
    })
    if (!response.ok) throw new Error('Export failed')
    const blob = await response.blob()
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `ai_chat_export_${currentResult.value.target_table}_${Date.now()}.xlsx`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    window.URL.revokeObjectURL(url)
  } catch (error) {
    console.error('Export error:', error)
    alert('导出失败，请重试')
  }
}

function handlePageChange(page: number) { resultPage.value = page }
function handlePageChangeData(page: number) { dataPage.value = page }

function handleRowClick(item: any) {
  if (item.customer_id) {
    router.push(`/customers/${item.customer_id}`)
  } else if (item.id) {
    router.push(`/customers/${item.id}`)
  }
}

function setExample(text: string) { inputQuery.value = text }

function scrollToBottom() {
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  }
}

function getTableName(tableName: string | undefined): string {
  const tableNames: Record<string, string> = {
    'dws_customer_360': '客户360',
    'dws_contact_360': '联系人360',
    'dws_contact_mapping': '联系人映射',
    'dws_interaction_detail': '互动明细',
  }
  return tableName ? (tableNames[tableName] || tableName) : '数据'
}

onMounted(() => { loadHistory() })
</script>

<style scoped>
.ai-chat {
  height: 100vh;
  background: var(--background);
  color: var(--text);
  overflow: hidden;
}

/* ========== 主布局 ========== */
.main-layout {
  display: flex;
  height: 100vh;
  max-width: 100%;
}

/* ========== 对话面板 ========== */
.chat-panel {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  transition: all 0.3s ease;
}

.chat-panel:not(.with-panel) {
  max-width: 900px;
  margin: 0 auto;
}

.chat-header {
  padding: 12px 24px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.header-content {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
}

.clear-btn {
  flex-shrink: 0;
  padding: 8px 16px;
  background: transparent;
  border: 1px solid var(--border);
  border-radius: 8px;
  color: var(--muted);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}

.clear-btn:hover {
  background: #fee2e2;
  border-color: #fca5a5;
  color: #dc2626;
}

.chat-header h1 {
  font-size: 20px;
  font-weight: 700;
  margin-bottom: 2px;
  background: linear-gradient(135deg, var(--primary) 0%, #8b5cf6 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.chat-header p {
  color: var(--muted);
  font-size: 13px;
  margin: 0;
}

.messages-area {
  flex: 1;
  overflow-y: auto;
  padding: 8px 20px;
}

.messages-area::-webkit-scrollbar { width: 5px; }
.messages-area::-webkit-scrollbar-track { background: transparent; }
.messages-area::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }

.input-area {
  padding: 8px 20px 10px;
  border-top: 1px solid var(--border);
  background: var(--surface);
  flex-shrink: 0;
}

.input-wrapper {
  display: flex;
  gap: 10px;
  margin-bottom: 6px;
  align-items: flex-end;
}

textarea {
  flex: 1;
  padding: 14px 18px;
  background: var(--background);
  border: 1px solid var(--border);
  border-radius: 14px;
  color: var(--text);
  font-size: 14px;
  font-family: inherit;
  resize: none;
  line-height: 1.5;
  transition: border-color 0.2s, box-shadow 0.2s;
}

textarea:focus {
  outline: none;
  border-color: var(--primary);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
}

textarea::placeholder { color: var(--muted); }
textarea:disabled { opacity: 0.6; cursor: not-allowed; }

.send-btn {
  padding: 10px 24px;
  height: 44px;
  background: linear-gradient(135deg, var(--primary) 0%, #6366f1 100%);
  color: white;
  border: none;
  border-radius: 14px;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s ease;
  white-space: nowrap;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 2px 8px rgba(59, 130, 246, 0.25);
}

.send-btn:hover:not(:disabled) {
  background: linear-gradient(135deg, var(--primary-dark) 0%, #4f46e5 100%);
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.35);
  transform: translateY(-1px);
}

.send-btn:active:not(:disabled) {
  transform: translateY(0);
  box-shadow: 0 2px 6px rgba(59, 130, 246, 0.2);
}

.send-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  transform: none;
}

.input-hints {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.input-hints > span {
  font-size: 11px;
  color: var(--muted);
  font-weight: 500;
}

.input-hints button {
  padding: 5px 12px;
  background: var(--background);
  border: 1px solid var(--border);
  border-radius: 14px;
  color: var(--text);
  font-size: 11px;
  cursor: pointer;
  transition: all 0.2s;
}

.input-hints button:hover {
  background: var(--primary);
  color: white;
  border-color: var(--primary);
}

/* ========== 右侧数据面板（可展开/收起） ========== */
.data-panel {
  width: 50%;
  min-width: 400px;
  max-width: 700px;
  display: flex;
  flex-direction: column;
  background: var(--surface, #fafbfc);
  border-left: 1px solid var(--border);
  overflow: hidden;
}

@media (prefers-color-scheme: dark) {
  .data-panel {
    background: rgba(15, 23, 42, 0.6);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
  }
}

.data-panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 24px;
  background: linear-gradient(135deg, rgba(59, 130, 246, 0.06) 0%, rgba(139, 92, 246, 0.06) 100%);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

@media (prefers-color-scheme: dark) {
  .data-panel-header {
    background: linear-gradient(135deg, rgba(59, 130, 246, 0.1) 0%, rgba(139, 92, 246, 0.08) 100%);
    border-bottom-color: rgba(255, 255, 255, 0.08);
  }
}

.data-panel-header h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
}

.panel-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.table-name {
  font-size: 11px;
  color: var(--muted);
  background: rgba(255, 255, 255, 0.7);
  padding: 3px 10px;
  border-radius: 10px;
  border: 1px solid var(--border);
}

@media (prefers-color-scheme: dark) {
  .table-name {
    background: rgba(255, 255, 255, 0.06);
    border-color: rgba(255, 255, 255, 0.1);
    color: rgba(156, 168, 194, 0.9);
  }
}

.export-btn-small {
  padding: 6px 12px;
  background: var(--primary);
  color: white;
  border: none;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.export-btn-small:hover { background: var(--primary-dark); }

.close-btn {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: 1px solid var(--border);
  border-radius: 50%;
  font-size: 18px;
  color: var(--muted);
  cursor: pointer;
  transition: all 0.2s;
}

.close-btn:hover {
  background: #fee2e2;
  border-color: #fca5a5;
  color: #dc2626;
}

/* 数据表格容器 */
.data-table-container {
  flex: 1;
  overflow-y: auto;
  padding: 0;
}

.data-table-container::-webkit-scrollbar { width: 5px; }
.data-table-container::-webkit-scrollbar-track { background: transparent; }
.data-table-container::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }

/* ========== 面板展开/收起动画 ========== */
.slide-panel-enter-active,
.slide-panel-leave-active {
  transition: all 0.3s ease;
}

.slide-panel-enter-from,
.slide-panel-leave-to {
  width: 0;
  min-width: 0;
  opacity: 0;
  border-left: none;
}
</style>
