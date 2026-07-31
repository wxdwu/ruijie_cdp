<script setup>
import AppSidebar from './components/layout/AppSidebar.vue'
import AppTopbar from './components/layout/AppTopbar.vue'
import ToastContainer from './components/common/ToastContainer.vue'
</script>

<template>
  <div class="flex h-screen overflow-hidden">
    <AppSidebar />
    <div class="flex flex-1 flex-col overflow-hidden">
      <AppTopbar />
      <main id="app-main-scroll" class="flex-1 overflow-auto p-6">
        <router-view v-slot="{ Component, route }">
          <KeepAlive include="CampaignBoard">
            <component :is="Component" v-if="route.meta.keepAlive" />
          </KeepAlive>
          <component :is="Component" v-if="!route.meta.keepAlive" />
        </router-view>
      </main>
    </div>
  </div>
  <ToastContainer />
</template>
