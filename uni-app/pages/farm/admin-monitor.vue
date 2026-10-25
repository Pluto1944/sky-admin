<template>
  <view class="monitor-page">
    <view v-if="loading" class="page-state">正在加载监控数据...</view>
    <view v-else-if="error" class="page-state">
      <text class="state-error">{{ error }}</text>
      <button class="small-button" @tap="load">重新加载</button>
    </view>
    <view v-else>
      <view class="round-card">
        <view class="round-head">
          <view>
            <text class="eyebrow">当前互刷场次</text>
            <text class="round-time">{{ formatTime(overview.round.scheduled_at_beijing) }}</text>
          </view>
          <text class="round-badge">{{ roundStatus(overview.round.status) }}</text>
        </view>
        <view class="round-foot">
          <text>数据更新 {{ formatUpdated(overview.updated_at) }}</text>
          <text>{{ overview.war.total }} 个部落</text>
        </view>
        <button
          v-if="overview.can_refresh"
          class="refresh-button"
          :disabled="refreshing"
          :loading="refreshing"
          @tap="refreshMonitor"
        >{{ refreshing ? '正在加入检查队列' : '刷新异常部落' }}</button>
      </view>

      <view class="metric-card" @tap="openList('war_detected')">
        <view class="metric-head">
          <view>
            <text class="metric-title">战争检测</text>
            <text class="metric-desc">已从 COC 官方数据检测到当前战争</text>
          </view>
          <view class="metric-value"><text>{{ overview.war.detected }}</text><text>/{{ overview.war.total }}</text></view>
        </view>
        <view class="metric-stats">
          <view @tap.stop="openList('war_detected')"><text>{{ overview.war.detected }}</text><text>已检测</text></view>
          <view @tap.stop="openList('war_not_detected')"><text>{{ overview.war.not_detected }}</text><text>暂未检测到</text></view>
          <view @tap.stop="openList('war_unchecked')"><text>{{ overview.war.unchecked }}</text><text>未检查</text></view>
          <view @tap.stop="openList('war_error')"><text>{{ overview.war.error }}</text><text>异常</text></view>
        </view>
      </view>

      <view class="metric-card" @tap="openList('unregistered')">
        <view class="metric-head">
          <view>
            <text class="metric-title">登记进度</text>
            <text class="metric-desc">当前场次已完成最终登记的部落</text>
          </view>
          <view class="metric-value"><text>{{ overview.registration.rate }}%</text></view>
        </view>
        <view class="progress-track"><view class="progress-fill" :style="{ width: overview.registration.rate + '%' }"></view></view>
        <view class="metric-line">
          <text>已登记 {{ overview.registration.registered }}</text>
          <text>未登记 {{ overview.registration.pending }}</text>
        </view>
      </view>

      <view class="metric-card" @tap="openList('match_failed')">
        <view class="metric-head">
          <view>
            <text class="metric-title">匹配情况</text>
            <text class="metric-desc">成功率仅统计已经形成最终结果的部落</text>
          </view>
          <view class="metric-value"><text>{{ overview.matching.rate }}%</text></view>
        </view>
        <view class="metric-stats three">
          <view @tap.stop="openList('match_success')"><text>{{ overview.matching.success }}</text><text>成功部落</text></view>
          <view @tap.stop="openList('match_failed')"><text>{{ overview.matching.failed }}</text><text>匹配失败</text></view>
          <view @tap.stop="openList('unregistered')"><text>{{ overview.matching.pending }}</text><text>尚未完成</text></view>
        </view>
        <text class="pair-note">内部匹配 {{ overview.matching.success_pairs }} 对</text>
      </view>

      <view class="metric-card" @tap="openList('win')">
        <view class="metric-head">
          <view>
            <text class="metric-title">预定胜负</text>
            <text class="metric-desc">内部匹配的预定结果与未形成结果的部落</text>
          </view>
          <text class="metric-arrow">›</text>
        </view>
        <view class="metric-stats four">
          <view @tap.stop="openList('win')"><text class="win">{{ overview.results.win }}</text><text>胜</text></view>
          <view @tap.stop="openList('loss')"><text class="loss">{{ overview.results.loss }}</text><text>负</text></view>
          <view @tap.stop="openList('match_failed')"><text class="warn">{{ overview.results.match_failed }}</text><text>匹配失败</text></view>
          <view @tap.stop="openList('unregistered')"><text>{{ overview.results.pending }}</text><text>待定</text></view>
        </view>
      </view>

      <view class="section-title">需要处理</view>
      <view class="list-card">
        <view v-for="item in attentionItems" :key="item.filter" class="list-row" @tap="openList(item.filter)">
          <text>{{ item.label }}</text>
          <view><text :class="{ danger: item.count > 0 }">{{ item.count }}</text><text class="arrow">›</text></view>
        </view>
      </view>

      <view class="section-title">账号登记进度</view>
      <view class="list-card">
        <view v-for="account in overview.accounts" :key="account.account_id" class="account-row" @tap="openAccount(account)">
          <view class="account-copy">
            <text class="account-name">{{ account.account_name }}</text>
            <text class="account-email">{{ account.account_username }}</text>
          </view>
          <view class="account-progress">
            <text :class="{ complete: account.registered === account.total }">{{ account.registered }}/{{ account.total }}</text>
            <text class="arrow">›</text>
          </view>
        </view>
      </view>
      <view class="bottom-space"></view>
    </view>
  </view>
</template>

<script>
import { getFarmMonitorOverview, refreshFarmMonitor } from '@/utils/api.js'

export default {
  data() {
    return {
      loading: true,
      error: '',
      refreshing: false,
      overview: {
        round: {}, updated_at: null,
        war: { total: 0, detected: 0, not_detected: 0, unchecked: 0, error: 0 },
        registration: { total: 0, registered: 0, pending: 0, rate: 0 },
        matching: { success: 0, failed: 0, pending: 0, success_pairs: 0, rate: 0 },
        results: { win: 0, loss: 0, match_failed: 0, revoked: 0, pending: 0 },
        attention: {}, accounts: [], can_refresh: false
      }
    }
  },
  computed: {
    attentionItems() {
      const data = this.overview.attention || {}
      return [
        { label: '未登记部落', count: data.unregistered || 0, filter: 'unregistered' },
        { label: '暂未检测到战争', count: data.war_not_detected || 0, filter: 'war_not_detected' },
        { label: '尚未检查', count: data.war_unchecked || 0, filter: 'war_unchecked' },
        { label: '战争数据异常', count: data.war_error || 0, filter: 'war_error' },
        { label: '场次时间不匹配', count: data.war_mismatch || 0, filter: 'war_mismatch' },
        { label: '登记数据获取失败', count: data.fetch_failed || 0, filter: 'fetch_failed' },
        { label: '匹配失败', count: data.match_failed || 0, filter: 'match_failed' }
      ]
    }
  },
  onShow() { this.load() },
  onPullDownRefresh() { this.load().finally(() => uni.stopPullDownRefresh()) },
  methods: {
    async load() {
      try {
        this.overview = await getFarmMonitorOverview()
        this.error = ''
      } catch (e) {
        this.error = e.message || '加载监控数据失败'
      } finally {
        this.loading = false
      }
    },
    roundStatus(status) {
      return ({ scheduled: '待开放', open: '可登记', partially_registered: '登记中', completed: '已完成' })[status] || status
    },
    formatTime(value) {
      if (!value) return '-'
      const date = new Date(value)
      const pad = number => String(number).padStart(2, '0')
      return `${date.getMonth() + 1}月${date.getDate()}日 ${pad(date.getHours())}:${pad(date.getMinutes())}`
    },
    formatUpdated(value) {
      if (!value) return '尚未检查'
      const date = new Date(value)
      const pad = number => String(number).padStart(2, '0')
      return `${pad(date.getHours())}:${pad(date.getMinutes())}`
    },
    openList(filter) {
      uni.navigateTo({ url: `/pages/farm/admin-monitor-clans?status_filter=${encodeURIComponent(filter)}` })
    },
    openAccount(account) {
      uni.navigateTo({ url: `/pages/farm/admin-monitor-clans?status_filter=all&account_id=${encodeURIComponent(account.account_id)}` })
    },
    async refreshMonitor() {
      if (this.refreshing) return
      this.refreshing = true
      try {
        const result = await refreshFarmMonitor(this.overview.round.id)
        uni.showToast({ title: `已加入 ${result.queued} 个部落`, icon: 'none' })
        await this.load()
      } catch (e) {
        uni.showModal({ title: '刷新失败', content: e.message || '请稍后重试', showCancel: false })
      } finally {
        this.refreshing = false
      }
    }
  }
}
</script>

<style>
.monitor-page { min-height: 100vh; padding: 26rpx; box-sizing: border-box; background: #0f0f23; color: #edf1f8; }.page-state { display: flex; min-height: 70vh; flex-direction: column; align-items: center; justify-content: center; gap: 24rpx; color: #7e899f; font-size: 25rpx; }.state-error { color: #cf7c80; }.small-button { padding: 0 30rpx; border: 1rpx solid #31537d; border-radius: 12rpx; background: transparent; color: #77afe5; font-size: 23rpx; }
.round-card, .metric-card, .list-card { margin-bottom: 18rpx; border: 1rpx solid #292f4e; border-radius: 18rpx; background: #191a31; }.round-card, .metric-card { padding: 25rpx; }.round-head, .metric-head, .round-foot, .metric-line { display: flex; align-items: center; justify-content: space-between; }.eyebrow { display: block; color: #77839a; font-size: 20rpx; }.round-time { display: block; margin-top: 8rpx; font-size: 31rpx; font-weight: 650; }.round-badge { padding: 6rpx 14rpx; border-radius: 18rpx; background: rgba(64,137,204,.16); color: #7bb4e8; font-size: 20rpx; }.round-foot { margin-top: 22rpx; color: #758097; font-size: 21rpx; }.refresh-button { display: flex; height: 66rpx; align-items: center; justify-content: center; margin-top: 22rpx; border: 0; border-radius: 11rpx; background: #273654 !important; color: #82b7e9 !important; font-size: 23rpx; }.refresh-button::after { border: 0; }
.metric-title, .metric-desc { display: block; }.metric-title { font-size: 28rpx; font-weight: 650; }.metric-desc { margin-top: 7rpx; color: #758097; font-size: 20rpx; }.metric-value { flex-shrink: 0; margin-left: 20rpx; color: #84b8e8; font-size: 33rpx; font-weight: 700; }.metric-value text:last-child { margin-left: 4rpx; color: #68748b; font-size: 21rpx; font-weight: 400; }.metric-arrow { color: #647089; font-size: 36rpx; }.metric-stats { display: grid; grid-template-columns: repeat(4, 1fr); margin-top: 24rpx; border-top: 1rpx solid #282e4b; }.metric-stats.three { grid-template-columns: repeat(3, 1fr); }.metric-stats view { padding-top: 20rpx; text-align: center; }.metric-stats view + view { border-left: 1rpx solid #282e4b; }.metric-stats text { display: block; }.metric-stats text:first-child { color: #dce2ec; font-size: 27rpx; font-weight: 650; }.metric-stats text:last-child { margin-top: 5rpx; color: #717d94; font-size: 18rpx; }.metric-stats .win { color: #70c293; }.metric-stats .loss { color: #c77d82; }.metric-stats .warn { color: #d0a45f; }.progress-track { height: 10rpx; margin-top: 26rpx; overflow: hidden; border-radius: 8rpx; background: #292e49; }.progress-fill { height: 100%; border-radius: 8rpx; background: #3f87c8; }.metric-line { margin-top: 15rpx; color: #7e899f; font-size: 21rpx; }.pair-note { display: block; margin-top: 17rpx; color: #6f7a90; font-size: 20rpx; text-align: right; }
.section-title { padding: 18rpx 4rpx 14rpx; color: #858fa5; font-size: 23rpx; font-weight: 600; }.list-card { overflow: hidden; }.list-row, .account-row { display: flex; min-height: 80rpx; align-items: center; justify-content: space-between; padding: 0 24rpx; font-size: 23rpx; }.list-row + .list-row, .account-row + .account-row { border-top: 1rpx solid #282e4b; }.list-row view, .account-progress { display: flex; align-items: center; }.list-row .danger { color: #d0a45f; }.arrow { margin-left: 14rpx; color: #606b83; font-size: 31rpx; }.account-copy { min-width: 0; }.account-name, .account-email { display: block; }.account-name { font-size: 24rpx; }.account-email { margin-top: 5rpx; color: #6e7990; font-size: 19rpx; }.account-progress { color: #d0a45f; font-size: 22rpx; }.account-progress .complete { color: #70c293; }.bottom-space { height: 50rpx; }
</style>
