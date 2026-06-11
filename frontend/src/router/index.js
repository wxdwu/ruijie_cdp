import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', redirect: '/customers' },
  {
    path: '/customers',
    name: 'CustomerList',
    component: () => import('../views/CustomerList.vue'),
  },
  {
    path: '/customers/:id',
    name: 'CustomerDetail',
    component: () => import('../views/CustomerDetail.vue'),
    props: true,
  },
  {
    path: '/campaign',
    name: 'CampaignBoard',
    component: () => import('../views/CampaignBoard.vue'),
  },
  {
    path: '/ai-chat',
    name: 'AiChat',
    component: () => import('../views/AiChat.vue'),
  },
  {
    path: '/review',
    name: 'ReviewQueue',
    component: () => import('../views/ReviewQueue.vue'),
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
