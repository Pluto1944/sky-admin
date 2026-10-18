<template>
  <view class="page">
    <TopBar title="管理所有联盟" :show-back="true" back-fallback="/pages/settings/platform-management" />
    <scroll-view scroll-y class="content">
      <view class="summary-card">
        <view>
          <text class="summary-title">联盟列表</text>
          <text class="summary-sub">当前显示 {{ alliances.length }} 个联盟</text>
        </view>
        <text class="summary-badge">超级管理</text>
      </view>

      <view class="search-row">
        <input
          v-model="search"
          class="search-input"
          confirm-type="search"
          placeholder="搜索联盟名称或联盟标识"
          placeholder-style="color:#59637a"
          @confirm="loadAlliances"
        />
        <text v-if="search" class="search-clear" @tap="clearSearch">清除</text>
        <button class="search-btn" :loading="busy" @tap="loadAlliances">查询</button>
      </view>

      <view v-if="busy && !alliances.length" class="state">加载联盟...</view>
      <view v-else-if="!alliances.length" class="state">没有匹配的联盟</view>
      <view v-for="item in alliances" :key="item.id" class="alliance-card" @tap="openAlliance(item)">
        <view class="title-row">
          <view class="grow">
            <text class="alliance-name">{{ item.name }}</text>
            <text class="alliance-key">{{ item.alliance_key }} · 联盟 ID {{ item.id }}</text>
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
        <text v-if="item.expires_at" class="expires">权益至 {{ shortDate(item.expires_at) }}</text>
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
      alliances: []
    }
  },
  onLoad(options) {
    if (options && options.search) this.search = decodeURIComponent(options.search)
  },
  async onShow() {
    await this.loadAlliances()
  },
  methods: {
    async loadAlliances() {
      if (this.busy) return
      this.busy = true
      try {
        const result = await getPlatformAlliances(this.search.trim())
        this.alliances = result.alliances || []
      } catch (err) {
        uni.showModal({ title: '联盟列表不可用', content: err.message || '请稍后重试', showCancel: false })
      } finally {
        this.busy = false
      }
    },
    clearSearch() {
      this.search = ''
      this.loadAlliances()
    },
    openAlliance(item) {
      uni.navigateTo({ url: `/pages/settings/platform-alliance-detail?id=${item.id}` })
    },
    statusLabel(value) {
      return ({ active: '正常', suspended: '已停用', archived: '已删除' }[value] || value)
    },
    planLabel(value) {
      return ({ free: '免费版', standard: '普通会员', premium: '高级会员', paid: '历史付费版', internal: '内部版' }[value] || value)
    },
    shortDate(value) {
      return value ? String(value).replace('T', ' ').slice(0, 16) : ''
    }
  }
}
</script>

<style>
.page { height: 100vh; display: flex; flex-direction: column; color: #dce1ed; background: #0f0f23; }.content { flex: 1; min-height: 0; padding: 24rpx; box-sizing: border-box; }
.summary-card { display: flex; align-items: center; justify-content: space-between; padding: 24rpx; border: 1rpx solid #292945; border-radius: 14rpx; background: #18182d; }.summary-title, .summary-sub, .alliance-name, .alliance-key, .expires { display: block; }.summary-title { color: #f1f3f8; font-size: 30rpx; font-weight: 700; }.summary-sub { margin-top: 7rpx; color: #727d93; font-size: 21rpx; }.summary-badge { padding: 8rpx 12rpx; border-radius: 8rpx; color: #c9a766; background: #302c35; font-size: 20rpx; }
.search-row { height: 88rpx; margin: 20rpx 0 18rpx; display: flex; align-items: center; padding-left: 20rpx; box-sizing: border-box; border: 1rpx solid #30304d; border-radius: 10rpx; background: #111126; }.search-input { flex: 1; min-width: 0; color: #fff; font-size: 23rpx; }.search-clear { flex-shrink: 0; padding: 20rpx 14rpx; color: #718db2; font-size: 20rpx; }.search-btn { width: 116rpx; height: 86rpx; flex-shrink: 0; margin: 0; border: 0; border-radius: 0 9rpx 9rpx 0; color: #84b8eb; background: #202b42; font-size: 22rpx; line-height: 86rpx; }.search-btn::after { border: 0; }
.alliance-card { margin-bottom: 16rpx; padding: 22rpx; border: 1rpx solid #292945; border-radius: 14rpx; background: #18182d; box-sizing: border-box; }.alliance-card:active { background: #202038; }.title-row { display: flex; align-items: center; }.grow { flex: 1; min-width: 0; }.alliance-name, .alliance-key { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.alliance-name { color: #edf0f7; font-size: 27rpx; font-weight: 650; }.alliance-key { margin-top: 5rpx; color: #626d83; font-size: 19rpx; }.status { flex-shrink: 0; margin-left: 10rpx; font-size: 21rpx; }.status-active { color: #54b9a6; }.status-suspended { color: #d29a5f; }.status-archived { color: #737b8e; }.arrow { margin-left: 14rpx; color: #69748c; font-size: 38rpx; }
.metrics-row { margin-top: 18rpx; display: flex; justify-content: space-between; color: #8d96aa; font-size: 20rpx; }.expires { margin-top: 10rpx; color: #778198; font-size: 21rpx; line-height: 1.6; }.state { padding: 120rpx 20rpx; color: #68738a; font-size: 24rpx; text-align: center; }.bottom-space { height: 80rpx; }
</style>
