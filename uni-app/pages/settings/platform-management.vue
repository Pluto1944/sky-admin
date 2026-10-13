<template>
  <view class="page">
    <TopBar title="超级管理" :show-back="true" back-fallback="/pages/settings/settings" />
    <scroll-view scroll-y class="content">
      <view class="summary-grid">
        <view class="summary-item"><text class="summary-number">{{ alliances.length }}</text><text class="summary-label">联盟</text></view>
        <view class="summary-item"><text class="summary-number">{{ activeCount }}</text><text class="summary-label">正常</text></view>
        <view class="summary-item"><text class="summary-number">{{ clanCount }}</text><text class="summary-label">部落</text></view>
        <view class="summary-item"><text class="summary-number">{{ memberCount }}</text><text class="summary-label">成员</text></view>
      </view>

      <view class="navigation-card" @tap="openPlatformSettings">
        <view class="navigation-icon">⚙</view>
        <view class="grow">
          <text class="name">平台设置</text>
          <text class="sub">免费联盟开放和同步队列</text>
        </view>
        <text class="arrow">›</text>
      </view>

      <view class="navigation-card" @tap="openAllianceList">
        <view class="navigation-icon navigation-icon-alliance">盟</view>
        <view class="grow">
          <text class="name">管理所有联盟</text>
          <text class="sub">搜索联盟并进入各联盟管理详情</text>
        </view>
        <text class="arrow">›</text>
      </view>

      <view class="navigation-card" @tap="openMultiVerification">
        <view class="navigation-icon navigation-icon-verification">证</view>
        <view class="grow">
          <text class="name">联盟多认证管理</text>
          <text class="sub">{{ verificationConflicts.length }} 个部落存在多联盟认证</text>
        </view>
        <text class="arrow">›</text>
      </view>

      <view class="navigation-card" @tap="openAuditLog">
        <view class="navigation-icon navigation-icon-audit">审</view>
        <view class="grow">
          <text class="name">审计日志</text>
          <text class="sub">查看最近 {{ audits.length }} 条平台操作记录</text>
        </view>
        <text class="arrow">›</text>
      </view>

      <view class="section-title">创建联盟</view>
      <view class="card">
        <text class="sub">平台入口不受个人创建数量限制；新联盟默认使用免费套餐。</text>
        <input v-model="platformAllianceName" class="input standalone-input" maxlength="30" placeholder="联盟名称" placeholder-style="color:#59637a" />
        <button class="primary-btn create-btn" :loading="createBusy" :disabled="createBusy || !platformAllianceName.trim()" @tap="createAlliance">创建联盟</button>
      </view>

      <view class="bottom-space"></view>
    </scroll-view>
  </view>
</template>

<script>
import TopBar from '@/components/TopBar.vue'
import { createPlatformAlliance, getPlatformAlliances } from '@/utils/api.js'

export default {
  components: { TopBar },
  data() {
    return {
      busy: false,
      createBusy: false,
      alliances: [],
      verificationConflicts: [],
      audits: [],
      platformAllianceName: ''
    }
  },
  computed: {
    activeCount() { return this.alliances.filter(item => item.status === 'active').length },
    clanCount() { return this.alliances.reduce((total, item) => total + Number(item.clan_count || 0), 0) },
    memberCount() { return this.alliances.reduce((total, item) => total + Number(item.member_count || 0), 0) }
  },
  async onShow() { await this.loadDashboard() },
  methods: {
    async loadDashboard() {
      if (this.busy) return
      this.busy = true
      try {
        const result = await getPlatformAlliances()
        this.alliances = result.alliances || []
        this.verificationConflicts = result.multi_alliance_verifications || result.verification_conflicts || []
        this.audits = result.audit || []
      } catch (err) {
        uni.showModal({ title: '超级管理不可用', content: err.message || '请稍后重试', showCancel: false })
      } finally { this.busy = false }
    },
    async createAlliance() {
      if (this.createBusy || !this.platformAllianceName.trim()) return
      this.createBusy = true
      try {
        const created = await createPlatformAlliance(this.platformAllianceName.trim())
        this.platformAllianceName = ''
        await this.loadDashboard()
        uni.navigateTo({ url: `/pages/settings/platform-alliance-detail?id=${created.alliance_id}` })
      } catch (err) {
        uni.showModal({ title: '创建失败', content: err.message || '请稍后重试', showCancel: false })
      } finally { this.createBusy = false }
    },
    openAllianceList() { uni.navigateTo({ url: '/pages/settings/platform-alliance-list' }) },
    openMultiVerification() { uni.navigateTo({ url: '/pages/settings/platform-multi-verification' }) },
    openAuditLog() { uni.navigateTo({ url: '/pages/settings/platform-audit-log' }) },
    openPlatformSettings() { uni.navigateTo({ url: '/pages/settings/platform-settings' }) }
  }
}
</script>

<style>
.page { height: 100vh; display: flex; flex-direction: column; color: #dce1ed; background: #0f0f23; }
.content { flex: 1; min-height: 0; padding: 24rpx; box-sizing: border-box; }
.summary-grid { display: flex; overflow: hidden; border: 1rpx solid #292945; border-radius: 14rpx; background: #18182d; }
.summary-item { width: 25%; padding: 22rpx 8rpx; box-sizing: border-box; border-right: 1rpx solid #292945; text-align: center; }.summary-item:last-child { border-right: 0; }
.summary-number, .summary-label { display: block; }.summary-number { color: #edf2fa; font-size: 31rpx; font-weight: 700; }.summary-label { margin-top: 7rpx; color: #78839a; font-size: 20rpx; }
.navigation-card, .card { margin-top: 18rpx; padding: 22rpx; border: 1rpx solid #292945; border-radius: 14rpx; background: #18182d; box-sizing: border-box; }
.navigation-card { display: flex; align-items: center; }.navigation-card:active { background: #202038; }
.navigation-icon { width: 58rpx; height: 58rpx; margin-right: 16rpx; display: flex; align-items: center; justify-content: center; border-radius: 14rpx; color: #7eb8f6; background: #202940; font-size: 28rpx; }
.navigation-icon-alliance { color: #c9a766; background: #302c35; font-size: 23rpx; font-weight: 700; }
.navigation-icon-verification { color: #8cc7b5; background: #203432; font-size: 23rpx; font-weight: 700; }.navigation-icon-audit { color: #b9a1d4; background: #30283d; font-size: 23rpx; font-weight: 700; }
.grow { flex: 1; min-width: 0; }.name { display: block; color: #e8ebf3; font-size: 26rpx; font-weight: 600; }.sub { display: block; color: #778198; font-size: 21rpx; line-height: 1.6; }.arrow { margin-left: 14rpx; color: #69748c; font-size: 38rpx; }
.section-title { margin: 30rpx 8rpx 14rpx; color: #7f8aa2; font-size: 23rpx; }
.input { flex: 1; height: 88rpx; padding: 0 22rpx; box-sizing: border-box; border: 1rpx solid #30304d; border-radius: 10rpx; color: #fff; background: #111126; font-size: 25rpx; line-height: 88rpx; }.standalone-input { margin-top: 20rpx; }
.primary-btn { border: 0; border-radius: 10rpx; font-size: 24rpx; }.primary-btn::after { border: 0; }.create-btn { height: 88rpx; margin-top: 16rpx; color: #fff; background: #315f9a; line-height: 88rpx; }
.bottom-space { height: 80rpx; }
</style>
