import { createApp } from 'vue'
import { createPinia } from 'pinia'
import router from './router'
import App from './App.vue'
import './styles/main.css'

const savedTheme = localStorage.getItem('cdp-theme')
document.documentElement.dataset.theme = savedTheme === 'dark' ? 'dark' : 'light'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')
