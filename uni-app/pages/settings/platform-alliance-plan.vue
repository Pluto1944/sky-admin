<template>
  <view class="page">
    <TopBar title="套餐权益" :show-back="true" :back-fallback="backFallback" />
    <scroll-view scroll-y class="content">
      <view v-if="loading" class="state">正在加载...</view>
      <template v-else-if="detail">
        <view class="summary-card">
          <text class="summary-title">{{ detail.alliance.name }}</text>
          <text class="summary-sub">{{ detail.alliance.alliance_key }}</text>
        </view>
        <view class="section-title">当前权益</view>
        <view class="card">
          <text class="plan-name">{{ planLabel(detail.alliance.plan_code) }}</text>
          <text class="sub">{{ grantStatusLabel(detail.alliance.grant_status) }}<text v-if="detail.alliance.expires_at"> · 权益至 {{ shortDate(detail.alliance.expires_at) }}</text></text>
          <text v-if="detail.alliance.grant_note" class="note">备注：{{ detail.alliance.grant_note }}</text>
        </view>
        <view class="section-title">调整权益</view>
        <view class="card">
          <text class="body">平台管理员可直接调整套餐。超级管理页面的部落与联赛操作仍不受套餐数量限制。</text>
          <button class="primary-btn full-btn" :loading="busy" @tap="grantPaid">开通付费版365天</button>
          <button class="secondary-btn full-btn" :loading="busy" @tap="grantFree">设为免费版</button>
        </view>
      </template>
      <view class="bottom-space"></view>
    </scroll-view>
  </view>
</template>

<script>
import TopBar from '@/components/TopBar.vue'
import { getPlatformAlliance, savePlatformPlan } from '@/utils/api.js'

export default {
  components: { TopBar },
  data() { return { allianceId: null, loading: true, busy: false, detail: null } },
  computed: { backFallback() { return `/pages/settings/platform-alliance-detail?id=${this.allianceId}` } },
  onLoad(options) { this.allianceId = Number(options && options.id) || null },
  async onShow() { if (this.allianceId) await this.loadData() },
  methods: {
    async loadData() {
      this.loading = true
      try { this.detail = await getPlatformAlliance(this.allianceId) }
      catch (err) { uni.showModal({ title: '权益加载失败', content: err.message || '请稍后重试', showCancel: false }) }
      finally { this.loading = false }
    },
    async grantPaid() {
      if (this.busy) return
      this.busy = true
      const expiry = new Date(Date.now() + 365 * 24 * 60 * 60 * 1000).toISOString()
      try { await savePlatformPlan(this.allianceId, 'paid', expiry, '后台人工开通'); await this.loadData(); uni.showToast({ title: '付费权益已开通', icon: 'success' }) }
      catch (err) { uni.showModal({ title: '开通失败', content: err.message || '请稍后重试', showCancel: false }) }
      finally { this.busy = false }
    },
    async grantFree() {
      if (this.busy) return
      this.busy = true
      try { await savePlatformPlan(this.allianceId, 'free', null, '后台调整为免费版'); await this.loadData(); uni.showToast({ title: '已设为免费版', icon: 'success' }) }
      catch (err) { uni.showModal({ title: '调整失败', content: err.message || '请先移除多余部落', showCancel: false }) }
      finally { this.busy = false }
    },
    planLabel(value) { return ({ free: '免费版', paid: '付费版', internal: '内部版' }[value] || value) },
    grantStatusLabel(value) { return ({ active: '有效', grace: '7天只读宽限期', expired: '已到期', revoked: '已撤销' }[value] || value || '兼容权益') },
    shortDate(value) { return value ? String(value).replace('T', ' ').slice(0, 16) : '' }
  }
}
</script>

<style>
.page { height: 100vh; display: flex; flex-direction: column; color: #dce1ed; background: #0f0f23; }.content { flex: 1; min-height: 0; padding: 24rpx; box-sizing: border-box; }.state { padding: 180rpx 24rpx; color: #717b91; text-align: center; }.summary-card, .card { padding: 24rpx; border: 1rpx solid #292945; border-radius: 14rpx; background: #18182d; }.summary-title, .summary-sub, .plan-name, .sub, .note, .body { display: block; }.summary-title { color: #f2f3f8; font-size: 30rpx; font-weight: 700; }.summary-sub, .sub, .note { margin-top: 8rpx; color: #737d92; font-size: 21rpx; line-height: 1.6; }.section-title { margin: 30rpx 8rpx 14rpx; color: #7f8aa2; font-size: 23rpx; }.plan-name { color: #e8ebf3; font-size: 30rpx; font-weight: 600; }.note { color: #68738a; }.body { color: #9ea7ba; font-size: 21rpx; line-height: 1.65; }.primary-btn, .secondary-btn { border: 0; border-radius: 10rpx; font-size: 24rpx; }.primary-btn { color: #fff; background: #315f9a; }.secondary-btn { color: #91b9e2; background: #202b42; }.primary-btn::after, .secondary-btn::after { border: 0; }.full-btn { width: 100%; height: 84rpx; margin-top: 18rpx; line-height: 84rpx; }.bottom-space { height: 80rpx; }
</style>
