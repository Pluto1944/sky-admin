<template>
  <view class="page">
    <TopBar title="审计日志" :show-back="true" back-fallback="/pages/settings/platform-management" />
    <scroll-view scroll-y class="content">
      <view class="summary-card">
        <view>
          <text class="summary-title">平台操作记录</text>
          <text class="summary-sub">最近 {{ audits.length }} 条 · 当前显示 {{ filteredAudits.length }} 条</text>
        </view>
        <text class="summary-badge">只读</text>
      </view>

      <view class="search-box">
        <input v-model="search" class="search-input" placeholder="搜索操作、对象类型或对象 ID" placeholder-style="color:#59637a" />
        <text v-if="search" class="search-clear" @tap="search = ''">清除</text>
      </view>

      <view v-if="busy" class="state">正在加载...</view>
      <view v-else-if="!filteredAudits.length" class="state">{{ search ? '没有匹配的审计记录' : '暂无平台操作记录' }}</view>
      <view v-else class="audit-list">
        <view v-for="(item, index) in filteredAudits" :key="index" class="audit-card">
          <view class="audit-head">
            <text class="audit-action">{{ item.action }}</text>
            <text class="audit-time">{{ shortDate(item.created_at) }}</text>
          </view>
          <text class="audit-entity">{{ item.entity_type }}<text v-if="item.entity_id !== null && item.entity_id !== undefined"> · ID {{ item.entity_id }}</text></text>
        </view>
      </view>
      <view class="bottom-space"></view>
    </scroll-view>
  </view>
</template>

<script>
import TopBar from '@/components/TopBar.vue'
import { getPlatformAlliances } from '@/utils/api.js'

export default {
  components: { TopBar },
  data() {
    return {
      busy: false,
      search: '',
      audits: []
    }
  },
  computed: {
    filteredAudits() {
      const keyword = this.search.trim().toLowerCase()
      if (!keyword) return this.audits
      return this.audits.filter(item => {
        return `${item.action || ''} ${item.entity_type || ''} ${item.entity_id || ''}`.toLowerCase().indexOf(keyword) >= 0
      })
    }
  },
  async onShow() {
    await this.loadData()
  },
  methods: {
    async loadData() {
      if (this.busy) return
      this.busy = true
      try {
        const result = await getPlatformAlliances()
        this.audits = result.audit || []
      } catch (err) {
        uni.showModal({ title: '审计日志不可用', content: err.message || '请稍后重试', showCancel: false })
      } finally {
        this.busy = false
      }
    },
    shortDate(value) {
      return value ? String(value).replace('T', ' ').slice(0, 16) : '—'
    }
  }
}
</script>

<style>
.page { height: 100vh; display: flex; flex-direction: column; color: #dce1ed; background: #0f0f23; }.content { flex: 1; min-height: 0; padding: 24rpx; box-sizing: border-box; }
.summary-card { display: flex; align-items: center; justify-content: space-between; padding: 24rpx; border: 1rpx solid #292945; border-radius: 14rpx; background: #18182d; }.summary-title, .summary-sub, .audit-action, .audit-entity { display: block; }.summary-title { color: #f1f3f8; font-size: 30rpx; font-weight: 700; }.summary-sub { margin-top: 7rpx; color: #727d93; font-size: 21rpx; }.summary-badge { padding: 8rpx 12rpx; border-radius: 8rpx; color: #b9a1d4; background: #30283d; font-size: 20rpx; }
.search-box { height: 84rpx; margin-top: 20rpx; display: flex; align-items: center; padding: 0 20rpx; box-sizing: border-box; border: 1rpx solid #30304d; border-radius: 10rpx; background: #111126; }.search-input { flex: 1; min-width: 0; color: #fff; font-size: 23rpx; }.search-clear { flex-shrink: 0; margin-left: 14rpx; color: #74a9df; font-size: 21rpx; }
.audit-list { margin-top: 16rpx; }.audit-card { margin-bottom: 12rpx; padding: 20rpx 22rpx; border: 1rpx solid #292945; border-radius: 12rpx; background: #18182d; }.audit-head { display: flex; align-items: flex-start; }.audit-action { flex: 1; min-width: 0; overflow-wrap: anywhere; color: #dce1ed; font-size: 22rpx; line-height: 1.45; }.audit-time { flex-shrink: 0; margin-left: 18rpx; color: #626d83; font-size: 19rpx; }.audit-entity { margin-top: 10rpx; color: #778198; font-size: 20rpx; }.state { padding: 150rpx 24rpx; color: #68738a; font-size: 24rpx; text-align: center; }.bottom-space { height: 80rpx; }
</style>
