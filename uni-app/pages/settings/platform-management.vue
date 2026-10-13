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
          <text class="name">平台设置与审计</text>
          <text class="sub">免费开放、同步队列、重复认证和操作记录</text>
        </view>
        <text class="arrow">›</text>
      </view>

      <view class="section-title">创建联盟</view>
      <view class="card">
        <text class="sub">平台入口不受个人创建数量限制；新联盟默认使用免费套餐。</text>
        <input v-model="platformAllianceName" class="input standalone-input" maxlength="30" placeholder="联盟名称" placeholder-style="color:#59637a" />
        <button class="primary-btn create-btn" :loading="createBusy" :disabled="createBusy || !platformAllianceName.trim()" @tap="createAlliance">创建联盟</button>
      </view>

      <view class="section-title">联盟列表</view>
      <view class="search-row">
        <input v-model="search" class="input" confirm-type="search" placeholder="联盟名称或标识" placeholder-style="color:#59637a" @confirm="loadDashboard" />
        <button class="search-btn" :loading="busy" @tap="loadDashboard">查询</button>
      </view>
      <view v-if="busy && !alliances.length" class="state">加载联盟...</view>
      <view v-else-if="!alliances.length" class="state">没有匹配的联盟</view>
      <view v-for="item in alliances" :key="item.id" class="alliance-card" @tap="openAlliance(item)">
        <view class="title-row">
          <view class="grow">
            <text class="alliance-name">{{ item.name }}</text>
            <text class="alliance-key">{{ item.alliance_key }}</text>
          </view>
          <text :class="['status', 'status-' + item.status]">{{ statusLabel(item.status) }}</text>
          <text class="arrow">›</text>
        </view>
        <view class="metrics-row">
          <text>{{ planLabel(item.plan_code) }}</text>
          <text>{{ item.clan_count }} 部落</text>
          <text>{{ item.member_count }} 成员</text>
          <text>{{ item.verified_count || 0 }} 已认证</text>
        </view>
        <text v-if="item.expires_at" class="sub expires">权益至 {{ shortDate(item.expires_at) }}</text>
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
      search: '',
      alliances: [],
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
        const result = await getPlatformAlliances(this.search.trim())
        this.alliances = result.alliances || []
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
    openAlliance(item) { uni.navigateTo({ url: `/pages/settings/platform-alliance-detail?id=${item.id}` }) },
    openPlatformSettings() { uni.navigateTo({ url: '/pages/settings/platform-settings' }) },
    statusLabel(value) { return ({ active: '正常', suspended: '已停用', archived: '已删除' }[value] || value) },
    planLabel(value) { return ({ free: '免费版', paid: '付费版', internal: '内部版' }[value] || value) },
    shortDate(value) { return value ? String(value).replace('T', ' ').slice(0, 16) : '' }
  }
}
</script>

<style>
.page { height: 100vh; display: flex; flex-direction: column; color: #dce1ed; background: #0f0f23; }
.content { flex: 1; min-height: 0; padding: 24rpx; box-sizing: border-box; }
.summary-grid { display: flex; overflow: hidden; border: 1rpx solid #292945; border-radius: 14rpx; background: #18182d; }
.summary-item { width: 25%; padding: 22rpx 8rpx; box-sizing: border-box; border-right: 1rpx solid #292945; text-align: center; }.summary-item:last-child { border-right: 0; }
.summary-number, .summary-label { display: block; }.summary-number { color: #edf2fa; font-size: 31rpx; font-weight: 700; }.summary-label { margin-top: 7rpx; color: #78839a; font-size: 20rpx; }
.navigation-card, .alliance-card, .card { margin-top: 18rpx; padding: 22rpx; border: 1rpx solid #292945; border-radius: 14rpx; background: #18182d; box-sizing: border-box; }
.navigation-card, .title-row, .search-row { display: flex; align-items: center; }.navigation-card:active, .alliance-card:active { background: #202038; }
.navigation-icon { width: 58rpx; height: 58rpx; margin-right: 16rpx; display: flex; align-items: center; justify-content: center; border-radius: 14rpx; color: #7eb8f6; background: #202940; font-size: 28rpx; }
.grow { flex: 1; min-width: 0; }.name { display: block; color: #e8ebf3; font-size: 26rpx; font-weight: 600; }.sub { display: block; color: #778198; font-size: 21rpx; line-height: 1.6; }.arrow { margin-left: 14rpx; color: #69748c; font-size: 38rpx; }
.section-title { margin: 30rpx 8rpx 14rpx; color: #7f8aa2; font-size: 23rpx; }
.input { flex: 1; height: 88rpx; padding: 0 22rpx; box-sizing: border-box; border: 1rpx solid #30304d; border-radius: 10rpx; color: #fff; background: #111126; font-size: 25rpx; line-height: 88rpx; }.standalone-input { margin-top: 20rpx; }
.primary-btn, .search-btn { border: 0; border-radius: 10rpx; font-size: 24rpx; }.primary-btn::after, .search-btn::after { border: 0; }.create-btn { height: 88rpx; margin-top: 16rpx; color: #fff; background: #315f9a; line-height: 88rpx; }
.search-row { margin-bottom: 18rpx; }.search-btn { width: 120rpx; margin-left: 12rpx; color: #7eb8f6; background: #202b42; line-height: 2.55; }
.alliance-card { margin-top: 0; margin-bottom: 16rpx; }.alliance-name, .alliance-key { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.alliance-name { color: #edf0f7; font-size: 27rpx; font-weight: 650; }.alliance-key { margin-top: 5rpx; color: #626d83; font-size: 19rpx; }
.status { margin-left: 10rpx; font-size: 21rpx; }.status-active { color: #54b9a6; }.status-suspended { color: #d29a5f; }.status-archived { color: #737b8e; }
.metrics-row { margin-top: 18rpx; display: flex; justify-content: space-between; color: #8d96aa; font-size: 20rpx; }.expires { margin-top: 10rpx; }
.state { padding: 100rpx 20rpx; color: #68738a; font-size: 24rpx; text-align: center; }.bottom-space { height: 80rpx; }
</style>
