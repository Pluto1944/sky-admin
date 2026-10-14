<template>
  <view class="page">
    <TopBar title="联盟操作记录" :show-back="true" :back-fallback="backFallback" />
    <scroll-view scroll-y class="content">
      <view v-if="loading" class="state">正在加载...</view>
      <template v-else-if="detail">
        <view class="summary-card">
          <text class="summary-title">{{ detail.alliance.name }}</text>
          <text class="summary-sub">最近 {{ detail.audit.length }} 条联盟审计记录</text>
        </view>
        <view class="section-title">操作记录</view>
        <view v-if="detail.audit.length" class="audit-list">
          <view v-for="(item, index) in detail.audit" :key="index" class="audit-card">
            <view class="audit-head"><text class="action">{{ item.action }}</text><text class="time">{{ shortDate(item.created_at) }}</text></view>
            <text class="meta">{{ item.entity_type }}<text v-if="item.entity_id"> · {{ item.entity_id }}</text></text>
            <text v-if="detailText(item.details_json)" class="details">{{ detailText(item.details_json) }}</text>
          </view>
        </view>
        <view v-else class="state compact">暂无联盟操作记录</view>
      </template>
      <view class="bottom-space"></view>
    </scroll-view>
  </view>
</template>

<script>
import TopBar from '@/components/TopBar.vue'
import { getPlatformAlliance } from '@/utils/api.js'

export default {
  components: { TopBar },
  data() { return { allianceId: null, loading: true, detail: null } },
  computed: { backFallback() { return `/pages/settings/platform-alliance-detail?id=${this.allianceId}` } },
  onLoad(options) { this.allianceId = Number(options && options.id) || null },
  async onShow() {
    if (!this.allianceId) return
    this.loading = true
    try { this.detail = await getPlatformAlliance(this.allianceId) }
    catch (err) { uni.showModal({ title: '记录加载失败', content: err.message || '请稍后重试', showCancel: false }) }
    finally { this.loading = false }
  },
  methods: {
    shortDate(value) { return value ? String(value).replace('T', ' ').slice(0, 16) : '' },
    detailText(value) {
      if (!value) return ''
      try {
        const parsed = typeof value === 'string' ? JSON.parse(value) : value
        return Object.keys(parsed).map(key => `${key}: ${parsed[key]}`).join(' · ')
      } catch (err) { return String(value) }
    }
  }
}
</script>

<style>
.page { height: 100vh; display: flex; flex-direction: column; color: #dce1ed; background: #0f0f23; }.content { flex: 1; min-height: 0; padding: 24rpx; box-sizing: border-box; }.state { padding: 180rpx 24rpx; color: #717b91; text-align: center; }.state.compact { padding: 80rpx 24rpx; }.summary-card, .audit-card { padding: 24rpx; border: 1rpx solid #292945; border-radius: 14rpx; background: #18182d; }.summary-title, .summary-sub, .meta, .details { display: block; }.summary-title { color: #f2f3f8; font-size: 30rpx; font-weight: 700; }.summary-sub { margin-top: 8rpx; color: #737d92; font-size: 21rpx; }.section-title { margin: 30rpx 8rpx 14rpx; color: #7f8aa2; font-size: 23rpx; }.audit-card { margin-bottom: 16rpx; }.audit-head { display: flex; align-items: center; justify-content: space-between; gap: 16rpx; }.action { flex: 1; min-width: 0; color: #e5e8f0; font-size: 24rpx; font-weight: 600; }.time { flex-shrink: 0; color: #626c83; font-size: 19rpx; }.meta { margin-top: 9rpx; color: #7c859a; font-size: 21rpx; }.details { margin-top: 12rpx; padding-top: 12rpx; border-top: 1rpx solid #292945; color: #68738a; font-size: 19rpx; line-height: 1.55; word-break: break-all; }.bottom-space { height: 80rpx; }
</style>
