<template>
  <div class="ai-chat">
    <div class="chat-container">
      <!-- Chat Area -->
      <div class="chat-area">
        <div class="chat-header">
          <h1>🤖 AI 智能查询</h1>
          <p>用自然语言描述您想查找的客户，我会帮您筛选</p>
        </div>

        <div ref="messagesContainer" class="messages-area">
          <ChatThread :messages="messages" :loading="isLoading" />
        </div>

        <!-- Query Result Table -->
        <div v-if="currentResult" class="result-area">
          <QueryResultTable
            :items="currentResult.customers.items"
            :total="currentResult.customers.total"
            :page="currentResult.customers.page"
            :page-size="currentResult.customers.page_size"
            :show-export="true"
            @export="handleExport"
            @page-change="handlePageChange"
            @row-click="handleRowClick"
          />
        </div>
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
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick } from 'vue'
import ChatThread from '../components/ai/ChatThread.vue'
import QueryResultTable from '../components/ai/QueryResultTable.vue'

interface Message {
  role: 'user' | 'assistant'
  text: string
  entities?: Record<string, any>
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
}

const messages = ref<Message[]>([])
const inputQuery = ref('')
const isLoading = ref(false)
const currentResult = ref<ChatResult | null>(null)
const messagesContainer = ref<HTMLElement | null>(null)

async function handleSubmit() {
  const query = inputQuery.value.trim()
  if (!query || isLoading.value) return

  // Add user message
  messages.value.push({
    role: 'user',
    text: query,
  })

  inputQuery.value = ''
  isLoading.value = true

  // Scroll to bottom
  await nextTick()
  scrollToBottom()

  try {
    // Call chat API
    const response = await fetch('/api/ai/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ query }),
    })

    if (!response.ok) {
      throw new Error('API request failed')
    }

    const result: ChatResult = await response.json()
    currentResult.value = result

    // Add assistant message
    messages.value.push({
      role: 'assistant',
      text: result.response,
      entities: result.entities,
    })
  } catch (error) {
    messages.value.push({
      role: 'assistant',
      text: '抱歉，处理您的请求时出现了错误，请稍后重试。',
    })
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
    const response = await fetch('/api/ai/chat/export', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        query: currentResult.value.query,
        entities: currentResult.value.entities,
      }),
    })

    if (!response.ok) {
      throw new Error('Export failed')
    }

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

function handlePageChange(page: number) {
  // For simplicity, we're just showing first page in this demo
  // In a real app, you'd call the API with the page number
  console.log('Page change:', page)
}

function handleRowClick(item: any) {
  // Navigate to customer detail or show detail modal
  console.log('Row clicked:', item)
  alert(`选中客户: ${item.customer_name}`)
}

function setExample(text: string) {
  inputQuery.value = text
}

function scrollToBottom() {
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  }
}
</script>

<style scoped>
.ai-chat {
  min-height: 100vh;
  background: var(--background);
  color: var(--text);
}

.chat-container {
  max-width: 900px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  height: 100vh;
}

.chat-area {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}

.chat-header {
  text-align: center;
  padding: 24px 0;
  border-bottom: 1px solid var(--border);
  margin-bottom: 24px;
}

.chat-header h1 {
  font-size: 28px;
  font-weight: 700;
  margin-bottom: 8px;
  background: linear-gradient(135deg, var(--primary) 0%, #8b5cf6 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.chat-header p {
  color: var(--muted);
  font-size: 14px;
}

.messages-area {
  max-height: calc(100vh - 400px);
  overflow-y: auto;
  padding-right: 8px;
}

.messages-area::-webkit-scrollbar {
  width: 6px;
}

.messages-area::-webkit-scrollbar-track {
  background: transparent;
}

.messages-area::-webkit-scrollbar-thumb {
  background: var(--border);
  border-radius: 3px;
}

.result-area {
  margin-top: 24px;
}

.input-area {
  padding: 20px;
  border-top: 1px solid var(--border);
  background: var(--surface);
}

.input-wrapper {
  display: flex;
  gap: 12px;
  margin-bottom: 12px;
}

textarea {
  flex: 1;
  padding: 12px 16px;
  background: var(--background);
  border: 1px solid var(--border);
  border-radius: 12px;
  color: var(--text);
  font-size: 15px;
  font-family: inherit;
  resize: none;
  transition: border-color 0.2s, box-shadow 0.2s;
}

textarea:focus {
  outline: none;
  border-color: var(--primary);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
}

textarea::placeholder {
  color: var(--muted);
}

textarea:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.send-btn {
  padding: 0 24px;
  background: var(--primary);
  color: white;
  border: none;
  border-radius: 12px;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.2s;
  white-space: nowrap;
}

.send-btn:hover:not(:disabled) {
  background: var(--primary-dark);
}

.send-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.input-hints {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.input-hints > span {
  font-size: 12px;
  color: var(--muted);
  font-weight: 500;
}

.input-hints button {
  padding: 6px 12px;
  background: var(--background);
  border: 1px solid var(--border);
  border-radius: 16px;
  color: var(--text);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
}

.input-hints button:hover {
  background: var(--primary);
  color: white;
  border-color: var(--primary);
}
</style>
