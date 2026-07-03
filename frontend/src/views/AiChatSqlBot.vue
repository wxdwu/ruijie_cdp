<template>
  <div class="ai-chat-sqlbot">
    <!-- SQLBot 挂载点 -->
    <div class="copilot"></div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'

let sqlbot_embedded_timer: number | null = null

onMounted(() => {
  console.log('[SQLBot] 开始加载 SQLBot SDK...')
  
  // 动态加载 SQLBot SDK
  const script = document.createElement('script')
  script.defer = true
  script.async = true
  // script.src = 'http://117.50.145.93:8010/xpack_static/sqlbot-embedded-dynamic.umd.js'
  //script.src = 'http://192.168.159.22:18000/xpack_static/sqlbot-embedded-dynamic.umd.js'
  script.src = 'http://192.168.159.22:28000/xpack_static/sqlbot-embedded-dynamic.umd.js'
  
  // 添加加载成功回调
  script.onload = () => {
    console.log('[SQLBot] SDK 脚本加载成功')
  }
  
  // 添加加载失败回调
  script.onerror = () => {
    console.error('[SQLBot] SDK 脚本加载失败，请检查：')
    console.error('  1. SQLBot 服务是否运行在 192.168.159.22:28000')
    // console.error('  1. SQLBot 服务是否运行在 http://117.50.145.93:8010')
    console.error('  2. 浏览器是否阻止了 HTTP 资源（混合内容）')
    console.error('  3. 网络连接是否正常')
  }
  
  document.head.appendChild(script)

  // 轮询等待 SDK 加载完成，然后挂载
  let retryCount = 0
  sqlbot_embedded_timer = window.setInterval(() => {
    retryCount++
    console.log(`[SQLBot] 等待 SDK 加载... (第 ${retryCount} 次检查)`)
    
    if ((window as any).sqlbot_embedded_handler?.mounted) {
      console.log('[SQLBot] SDK 已就绪，开始挂载...')
      try {
        ;(window as any).sqlbot_embedded_handler.mounted('.copilot', {
          //embeddedId: '7478264506984960000',
          //embeddedId: '7475721140279709696',
          embeddedId: '7478717292528799744',
        })
        console.log('[SQLBot] 挂载成功！')
        if (sqlbot_embedded_timer) clearInterval(sqlbot_embedded_timer)
      } catch (error) {
        console.error('[SQLBot] 挂载失败：', error)
      }
    }
    
    // 超过 30 秒停止轮询
    if (retryCount > 30) {
      console.error('[SQLBot] SDK 加载超时，请刷新页面重试')
      if (sqlbot_embedded_timer) clearInterval(sqlbot_embedded_timer)
    }
  }, 1000)
})

onUnmounted(() => {
  if (sqlbot_embedded_timer) clearInterval(sqlbot_embedded_timer)
})
</script>

<style scoped>
.ai-chat-sqlbot {
  height: 100vh;
  background: var(--background);
  overflow: hidden;
}

.copilot {
  width: 100%;
  height: 100%;
}
</style>
