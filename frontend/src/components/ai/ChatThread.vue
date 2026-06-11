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
        <div class="message-text">{{ message.text }}</div>
        <EntityChips
          v-if="message.role === 'assistant' && message.entities"
          :entities="message.entities"
          class="message-entities"
        />
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
import EntityChips from './EntityChips.vue'

interface Message {
  role: 'user' | 'assistant'
  text: string
  entities?: Record<string, any>
}

defineProps<{
  messages: Message[]
  loading?: boolean
}>()
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
  white-space: pre-wrap;
}

.message.user .message-text {
  background: var(--primary);
  color: white;
  border-bottom-right-radius: 4px;
}

.message.assistant .message-text {
  background: var(--surface);
  color: var(--text);
  border-bottom-left-radius: 4px;
}

.message-entities {
  margin-top: 4px;
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
