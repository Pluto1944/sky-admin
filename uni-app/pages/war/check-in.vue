<template>
  <view class="check-in-container">
    <view class="inner-tab-bar">
      <view class="inner-tab" :class="{ active: activeView === 'arrival' }" @tap="setActiveView('arrival')">集结检查</view>
      <view class="inner-tab" :class="{ active: activeView === 'attack' }" @tap="setActiveView('attack')">出刀提醒</view>
    </view>

    <view v-if="activeView === 'arrival'" class="placeholder-pane">
      <text class="placeholder-text">集结提醒</text>
    </view>

    <view v-else class="attack-pane">
      <view v-if="loading" class="state-box"><text class="state-text">加载出刀提醒...</text></view>
      <view v-else-if="loadError && !teams.length" class="state-box">
        <text class="error-text">{{ loadError }}</text>
        <text class="retry-btn" @tap="fetchData">点击重试</text>
      </view>
      <scroll-view v-else scroll-y class="content-scroll">
        <view class="content-inner">
          <view class="summary-card">
            <view class="summary-heading">
              <text class="summary-title">当前战斗日</text>
              <text class="summary-period">{{ periodLabel }}</text>
            </view>
            <view class="summary-metrics">
              <view class="summary-metric"><text class="metric-number">{{ summary.active_team_count || 0 }}</text><text class="metric-label">战斗中</text></view>
              <view class="summary-metric"><text class="metric-number warning-number">{{ summary.pending_attack_count || 0 }}</text><text class="metric-label">未出刀</text></view>
              <view class="summary-metric"><text class="metric-number">{{ summary.preparation_team_count || 0 }}</text><text class="metric-label">准备中</text></view>
              <view class="summary-metric"><text class="metric-number">{{ summary.team_count || 0 }}</text><text class="metric-label">全部队伍</text></view>
            </view>
            <text v-if="updatedAt" class="updated-at">数据更新于 {{ formatTime(updatedAt) }}</text>
          </view>

          <view v-if="loadError" class="cache-warning">{{ loadError }}（已保留当前页面数据）</view>
          <view v-if="!activeTeams.length" class="empty-card">
            <text class="empty-title">当前暂无战斗日队伍</text>
            <text class="empty-hint">{{ nonActiveSummary }}</text>
          </view>

          <view v-for="team in activeTeams" :key="team.clan_tag" class="team-card">
            <view class="team-header">
              <view class="team-identity">
                <text class="category-badge" :class="'category-' + team.category">{{ categoryLabel(team.category) }}</text>
                <text class="team-name">{{ team.team_name || team.team_alias }}</text>
                <text class="team-alias">{{ team.team_alias }}</text>
              </view>
              <text class="countdown" :class="urgencyClass(team.end_time)">{{ countdownLabel(team.end_time) }}</text>
            </view>

            <view class="match-row">
              <text>第{{ team.round || '-' }}场</text>
              <text class="opponent">VS {{ team.opponent ? team.opponent.name : '-' }}</text>
              <text class="attack-progress">{{ team.attacked_count || 0 }}/{{ team.team_size || 0 }}已出刀</text>
            </view>
            <view v-if="team.error" class="team-warning">{{ team.error }}（已保留最近数据）</view>

            <view v-if="team.pending_count" class="pending-section">
              <view class="pending-title-row">
                <text class="pending-title">未出刀成员</text>
                <text class="pending-count">{{ team.pending_count }}人</text>
              </view>
              <view v-for="member in team.pending_members" :key="member.player_tag" class="member-row">
                <text class="member-position">{{ member.position }}</text>
                <text class="member-name">{{ member.name }}</text>
                <text class="member-th">TH{{ member.town_hall_level || '-' }}</text>
                <text class="member-tag">{{ member.player_tag }}</text>
              </view>
            </view>
            <view v-else class="all-attacked">全员已出刀</view>
          </view>

          <view v-if="teams.length" class="status-footer">{{ nonActiveSummary }}</view>
          <view class="bottom-space"></view>
        </view>
      </scroll-view>
    </view>
  </view>
</template>

<script>
import { getCwlCheckIn } from '@/utils/api.js'

const CACHE_REFRESH_INTERVAL_MS = 60 * 1000

export default {
  name: 'CwlCheckIn',
  props: {
    initialView: { type: String, default: 'attack' }
  },
  data() {
    return {
      activeView: 'attack',
      loading: true,
      loadError: '',
      period: '',
      updatedAt: '',
      summary: {},
      teams: [],
      nowMs: Date.now(),
      clockTimer: null,
      refreshTimer: null
    }
  },
  computed: {
    activeTeams() { return this.teams.filter(team => team.status === 'in_war') },
    periodLabel() { return this.period ? `${this.period.slice(0, 4)}年${Number(this.period.slice(5))}月` : '-' },
    statusCounts() {
      return this.teams.reduce((result, team) => {
        result[team.status] = (result[team.status] || 0) + 1
        return result
      }, {})
    },
    nonActiveSummary() {
      const parts = []
      if (this.statusCounts.preparation) parts.push(`准备中 ${this.statusCounts.preparation}队`)
      if (this.statusCounts.waiting) parts.push(`等待开启 ${this.statusCounts.waiting}队`)
      if (this.statusCounts.ended) parts.push(`已结束 ${this.statusCounts.ended}队`)
      if (this.statusCounts.error) parts.push(`数据异常 ${this.statusCounts.error}队`)
      return parts.length ? parts.join(' · ') : '暂无其他队伍状态'
    }
  },
  mounted() {
    this.activeView = this.initialView === 'arrival' ? 'arrival' : 'attack'
    this.fetchData()
    this.startTimers()
  },
  beforeDestroy() { this.stopTimers() },
  methods: {
    setActiveView(view) {
      this.activeView = view
      this.$emit('view-change', view)
    },
    async fetchData() {
      if (!this.teams.length) this.loading = true
      this.loadError = ''
      try {
        const res = await getCwlCheckIn()
        this.period = res.period || ''
        this.updatedAt = res.updated_at || ''
        this.summary = res.summary || {}
        this.teams = res.teams || []
      } catch (e) {
        this.loadError = e.message || '出刀提醒加载失败'
      } finally { this.loading = false }
    },
    startTimers() {
      this.stopTimers()
      this.nowMs = Date.now()
      this.clockTimer = setInterval(() => { this.nowMs = Date.now() }, 1000)
      this.refreshTimer = setInterval(() => { this.fetchData() }, CACHE_REFRESH_INTERVAL_MS)
    },
    stopTimers() {
      if (this.clockTimer) clearInterval(this.clockTimer)
      if (this.refreshTimer) clearInterval(this.refreshTimer)
      this.clockTimer = null
      this.refreshTimer = null
    },
    parseTime(value) {
      if (!value) return null
      const text = String(value)
      const match = text.match(/^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})/)
      if (match) return new Date(`${match[1]}-${match[2]}-${match[3]}T${match[4]}:${match[5]}:${match[6]}Z`)
      const date = new Date(text.replace('+00:00', 'Z'))
      return isNaN(date.getTime()) ? null : date
    },
    formatTime(value) {
      const date = this.parseTime(value)
      if (!date) return '-'
      const pad = number => String(number).padStart(2, '0')
      return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
    },
    remainingSeconds(value) {
      const date = this.parseTime(value)
      return date ? Math.max(0, Math.floor((date.getTime() - this.nowMs) / 1000)) : null
    },
    countdownLabel(value) {
      const seconds = this.remainingSeconds(value)
      if (seconds == null) return '结束时间未知'
      if (seconds <= 0) return '即将结束'
      const hours = Math.floor(seconds / 3600)
      const minutes = Math.floor((seconds % 3600) / 60)
      return `剩余 ${hours}小时${minutes}分`
    },
    urgencyClass(value) {
      const seconds = this.remainingSeconds(value)
      if (seconds == null) return ''
      if (seconds <= 2 * 3600) return 'urgent'
      if (seconds <= 6 * 3600) return 'warning'
      return ''
    },
    categoryLabel(category) { return category === 'shell' ? '壳子' : '实战' }
  }
}
</script>

<style>
:host { width: 100%; height: 0; min-height: 0; flex: 1; display: block; }
.check-in-container { width: 100%; height: 100%; min-height: 0; display: flex; flex-direction: column; background: #0f0f23; color: #d8dce8; }
.inner-tab-bar { flex-shrink: 0; height: 72rpx; display: flex; border-bottom: 1rpx solid #1a1a2e; background: #141428; }
.inner-tab { flex: 1; display: flex; align-items: center; justify-content: center; box-sizing: border-box; color: #66708a; font-size: 28rpx; border-bottom: 4rpx solid transparent; }
.inner-tab.active { color: #5fa8ff; border-bottom-color: #4a90d9; font-weight: 600; }
.placeholder-pane, .state-box { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; }
.placeholder-text { color: #8890a0; font-size: 30rpx; }
.attack-pane { flex: 1; min-height: 0; display: flex; flex-direction: column; }.content-scroll { flex: 1; height: 0; }.content-inner { padding: 20rpx 24rpx 0; }
.state-text { color: #8890a0; font-size: 28rpx; }.error-text { margin: 0 32rpx 20rpx; color: #e17055; font-size: 26rpx; text-align: center; }.retry-btn { color: #5fa8ff; font-size: 26rpx; }
.summary-card, .team-card, .empty-card { margin-bottom: 20rpx; border: 1rpx solid #2a2a4a; border-radius: 14rpx; background: #18182d; }
.summary-card { padding: 20rpx; }.summary-heading { display: flex; align-items: center; }.summary-title { color: #fff; font-size: 29rpx; font-weight: 600; }.summary-period { margin-left: auto; color: #74b9ff; font-size: 23rpx; }
.summary-metrics { margin-top: 20rpx; display: flex; }.summary-metric { flex: 1; display: flex; flex-direction: column; align-items: center; }.metric-number { color: #f0f0f5; font-size: 34rpx; font-weight: 600; }.warning-number { color: #fdcb6e; }.metric-label { margin-top: 5rpx; color: #747c91; font-size: 21rpx; }.updated-at { display: block; margin-top: 18rpx; color: #596178; font-size: 20rpx; text-align: center; }
.cache-warning, .team-warning { padding: 12rpx 15rpx; border-radius: 8rpx; color: #fdcb6e; background: rgba(253,203,110,.1); font-size: 21rpx; line-height: 1.5; }.cache-warning { margin-bottom: 18rpx; }.team-warning { margin: 0 18rpx 16rpx; }
.empty-card { padding: 80rpx 20rpx; display: flex; flex-direction: column; align-items: center; }.empty-title { color: #aab4c8; font-size: 27rpx; }.empty-hint { margin-top: 12rpx; color: #66708a; font-size: 22rpx; }
.team-card { overflow: hidden; }.team-header { min-height: 76rpx; padding: 14rpx 18rpx; display: flex; align-items: center; box-sizing: border-box; border-bottom: 1rpx solid #282844; }.team-identity { min-width: 0; display: flex; align-items: center; }.category-badge { flex-shrink: 0; margin-right: 10rpx; padding: 3rpx 9rpx; border-radius: 6rpx; color: #9fc9ff; background: rgba(74,144,217,.18); font-size: 20rpx; }.category-shell { color: #d9b8ff; background: rgba(162,111,212,.16); }.team-name { max-width: 230rpx; overflow: hidden; color: #f0f0f5; font-size: 27rpx; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }.team-alias { flex-shrink: 0; margin-left: 8rpx; color: #66708a; font-size: 20rpx; }.countdown { margin-left: auto; flex-shrink: 0; color: #74b9ff; font-size: 22rpx; }.countdown.warning { color: #fdcb6e; }.countdown.urgent { color: #ff7675; font-weight: 600; }
.match-row { padding: 16rpx 18rpx; display: flex; align-items: center; color: #8d95a8; font-size: 22rpx; }.opponent { margin-left: 18rpx; color: #d8dce8; }.attack-progress { margin-left: auto; color: #74b9ff; }
.pending-section { margin: 0 18rpx 18rpx; overflow: hidden; border: 1rpx solid #332f42; border-radius: 9rpx; }.pending-title-row { padding: 12rpx 14rpx; display: flex; align-items: center; background: #202037; }.pending-title { color: #d8dce8; font-size: 23rpx; }.pending-count { margin-left: auto; color: #fdcb6e; font-size: 22rpx; }.member-row { min-height: 62rpx; padding: 8rpx 14rpx; display: flex; align-items: center; box-sizing: border-box; border-top: 1rpx solid #292943; }.member-position { width: 44rpx; color: #74b9ff; font-size: 22rpx; }.member-name { min-width: 0; flex: 1; overflow: hidden; color: #f0f0f5; font-size: 24rpx; text-overflow: ellipsis; white-space: nowrap; }.member-th { margin-left: 10rpx; color: #aab4c8; font-size: 21rpx; }.member-tag { margin-left: 10rpx; color: #596178; font-size: 19rpx; }.all-attacked { margin: 0 18rpx 18rpx; padding: 18rpx; border-radius: 9rpx; color: #00b894; background: rgba(0,184,148,.08); font-size: 24rpx; text-align: center; }
.status-footer { margin: 6rpx 0 20rpx; color: #66708a; font-size: 21rpx; text-align: center; }.bottom-space { height: 100rpx; }
</style>
