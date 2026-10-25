<template>
  <view class="detail-page">
    <view v-if="loading" class="page-state">正在加载...</view>
    <view v-else-if="error" class="page-state">
      <text class="state-error">{{ error }}</text>
      <button class="small-button" @tap="load">重新加载</button>
    </view>
    <view v-else>
      <view class="section-heading">
        <text class="section-index">01</text>
        <view><text class="section-name">基本信息</text><text class="section-desc">COC 官方部落基本资料</text></view>
      </view>

      <view class="clan-profile-card own-profile-card">
        <view class="profile-head own-profile-head">
          <view class="profile-copy">
            <text class="profile-name">{{ clan.clan_name }}</text>
            <text class="profile-tag">{{ clan.clan_tag }}</text>
          </view>
          <text class="profile-badge status-badge" :class="{ disabled: clan.status !== 'active' }">{{ clan.status === 'active' ? '启用' : '停用' }}</text>
        </view>
        <view v-if="hasProfile" class="profile-announcement">
          <text class="card-title">部落公告</text>
          <text class="description">{{ profile.description || '该部落暂未设置公告' }}</text>
        </view>
        <view v-else class="profile-empty">
          <text class="empty-title">暂无可用的官方部落资料</text>
          <text class="empty-desc">缓存状态：{{ profileStatusLabel }}</text>
          <text v-if="profileError" class="empty-error">{{ profileError }}</text>
        </view>
        <view v-if="hasProfile" class="profile-metrics profile-metrics--four">
          <view class="profile-metric"><text class="profile-metric-value">{{ memberCount }}</text><text class="profile-metric-label">成员人数</text></view>
          <view class="profile-metric"><text class="profile-metric-value">{{ profile.clan_level || '-' }}</text><text class="profile-metric-label">部落等级</text></view>
          <view class="profile-metric"><text class="profile-metric-value compact">{{ locationName }}</text><text class="profile-metric-label">位置</text></view>
          <view class="profile-metric"><text class="profile-metric-value compact">{{ joinTypeLabel(profile.join_type) }}</text><text class="profile-metric-label">加入方式</text></view>
        </view>
        <text class="profile-cache-time">基本资料更新：{{ formatTime(profileUpdatedAt) }}</text>
      </view>

      <view class="section-heading farm-heading">
        <text class="section-index farm">02</text>
        <view><text class="section-name">互刷信息</text><text class="section-desc">积分、本轮匹配对手与预定胜负</text></view>
      </view>

      <view class="score-card">
        <view><text class="score-label">当前互刷积分</text><text class="score-value">{{ clan.score }}</text></view>
        <view class="score-meta"><text>{{ clan.status === 'active' ? '当前可参与新场次' : '当前已停止参与新场次' }}</text><text>最近启用 {{ formatTime(clan.enabled_at) }}</text></view>
      </view>

      <view class="section-card farm-card">
        <view class="card-head"><text class="card-title">本轮互刷匹配</text><text class="subtle-badge farm-status">{{ roundStatusLabel }}</text></view>
        <view v-if="farmRound" class="info-row"><text class="info-label">开始搜战时间</text><text class="info-value">{{ formatTime(farmRound.scheduled_at_beijing) }}</text></view>
        <view class="info-row"><text class="info-label">登记状态</text><text class="info-value">{{ registrationStatusLabel }}</text></view>
        <view class="info-row opponent-row">
          <text class="info-label">互刷对手</text>
          <view v-if="farmOpponent" class="right-copy"><text class="info-value">{{ farmOpponent.name }}</text><text class="info-subvalue">{{ farmOpponent.tag }}</text></view>
          <text v-else class="info-value muted">{{ farmOpponentEmptyText }}</text>
        </view>
        <view class="info-row"><text class="info-label">本轮胜负</text><text class="result-value" :class="farmRegistration && farmRegistration.result">{{ farmResultLabel }}</text></view>
        <text v-if="farmRegistration && farmRegistration.last_error" class="farm-error">{{ farmRegistration.last_error }}</text>
      </view>

      <view class="section-heading opponent-heading">
        <text class="section-index opponent">03</text>
        <view><text class="section-name">对手部落</text><text class="section-desc">当前互刷对手的官方基本资料</text></view>
      </view>

      <view v-if="!opponent" class="empty-card">
        <text class="empty-title">尚未确定对手部落</text>
        <text class="empty-desc">完成本轮登记后会显示对手公告和基本信息</text>
      </view>
      <block v-else>
        <view class="clan-profile-card opponent-profile-card">
          <view class="profile-head opponent-profile-head">
            <view class="profile-copy">
              <text class="profile-name">{{ opponentName }}</text>
              <text class="profile-tag">{{ opponentTag }}</text>
            </view>
            <text class="profile-badge opponent-source">{{ opponentSourceLabel }}</text>
          </view>
          <view class="profile-announcement">
            <text class="card-title">部落公告</text>
            <text class="description">{{ opponentAnnouncement }}</text>
          </view>
          <view v-if="hasOpponentProfile" class="profile-metrics profile-metrics--three">
            <view class="profile-metric"><text class="profile-metric-value">{{ opponentMemberCount }}</text><text class="profile-metric-label">成员人数</text></view>
            <view class="profile-metric"><text class="profile-metric-value">{{ opponentProfile.clan_level || '-' }}</text><text class="profile-metric-label">部落等级</text></view>
            <view class="profile-metric"><text class="profile-metric-value compact">{{ opponentLocation }}</text><text class="profile-metric-label">位置</text></view>
          </view>
          <text class="profile-cache-time">对手资料更新：{{ formatTime(opponent.profile_updated_at) }}</text>
        </view>
      </block>

      <view class="bottom-space"></view>
    </view>
  </view>
</template>

<script>
import { getFarmClanDetail, requestFarmClanDetailRefresh } from '@/utils/api.js'

const OPEN_REFRESH_STATES = ['pending', 'running', 'retry_wait']
const PROFILE_POLL_INTERVAL_MS = 3000
const PROFILE_POLL_LIMIT = 6

export default {
  data() {
    return {
      clanTag: '',
      clan: {},
      profile: {},
      profileStatus: 'pending',
      profileError: '',
      profileUpdatedAt: '',
      farmRound: null,
      farmRegistration: null,
      opponent: null,
      loading: true,
      error: '',
      profileRefreshSubmitting: false,
      profilePollTimer: null,
      profilePollCount: 0,
      profilePollBaselines: {}
    }
  },
  computed: {
    hasProfile() { return Boolean(this.profile && Object.keys(this.profile).length) },
    memberCount() {
      const value = Number(this.profile.official_member_count)
      return Number.isFinite(value) ? `${value}/50` : '-'
    },
    locationName() { return this.namedValue(this.profile.location) },
    profileStatusLabel() {
      return ({ success: '已同步', stale: '缓存较旧', error: '同步失败', failed: '同步失败', pending: '等待同步' })[this.profileStatus] || this.profileStatus
    },
    roundStatusLabel() {
      if (!this.farmRound) return '暂无场次'
      return ({ scheduled: '待开放', open: '可登记', partially_registered: '登记中', completed: '已完成', cancelled: '已撤销' })[this.farmRound.status] || this.farmRound.status
    },
    registrationStatusLabel() {
      if (this.farmRound && !this.farmRegistration) return '未参加本轮'
      const status = this.farmRegistration && this.farmRegistration.registration_status
      return ({ not_registered: '未登记', registering: '登记中', not_in_war: '尚未搜到对手', war_mismatch: '场次不匹配', fetch_failed: '获取失败', internal_matched: '内部匹配成功', match_failed: '匹配失败', revoked: '已撤销' })[status] || (status || '暂无场次')
    },
    farmOpponent() {
      if (!this.farmRegistration || (!this.farmRegistration.opponent_name && !this.farmRegistration.opponent_tag)) return null
      return { name: this.farmRegistration.opponent_name || '未知名称', tag: this.farmRegistration.opponent_tag || '标签未知' }
    },
    farmOpponentEmptyText() {
      if (this.farmRound && !this.farmRegistration) return '未参加本轮'
      return this.farmRegistration ? '登记后显示' : '暂无场次'
    },
    farmResultLabel() {
      if (!this.farmRegistration) return '-'
      return ({ win: '胜', loss: '负', match_failed: '匹配失败' })[this.farmRegistration.result] || '待定'
    },
    opponentProfile() { return (this.opponent && this.opponent.profile) || {} },
    hasOpponentProfile() { return Boolean(Object.keys(this.opponentProfile).length) },
    opponentName() { return this.opponentProfile.name || (this.opponent && this.opponent.clan_name) || '未知名称' },
    opponentTag() { return this.opponentProfile.clan_tag || this.opponentProfile.tag || (this.opponent && this.opponent.clan_tag) || '标签未知' },
    opponentAnnouncement() {
      if (this.hasOpponentProfile) return this.opponentProfile.description || '该部落暂未设置公告'
      return '暂未同步到该对手部落的官方公告'
    },
    opponentMemberCount() {
      const value = Number(this.opponentProfile.official_member_count)
      return Number.isFinite(value) ? `${value}/50` : '-'
    },
    opponentLocation() { return this.namedValue(this.opponentProfile.location) },
    opponentSourceLabel() { return '互刷对手' }
  },
  onLoad(options) {
    try { this.clanTag = decodeURIComponent((options && options.clan_tag) || '') } catch (e) { this.clanTag = '' }
  },
  onShow() { this.load({ requestProfileRefresh: true }) },
  onUnload() { this.stopProfilePolling() },
  methods: {
    tagKey(value) { return String(value || '').trim().toUpperCase().replace(/O/g, '0') },
    namedValue(value) { return value && value.name ? value.name : '-' },
    joinTypeLabel(value) { return ({ open: '任何人可加入', inviteOnly: '需要邀请', closed: '不可加入' })[value] || value || '-' },
    formatTime(value) {
      if (!value) return '-'
      const date = new Date(value)
      if (Number.isNaN(date.getTime())) return '-'
      const pad = number => String(number).padStart(2, '0')
      return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
    },
    applyProfileResult(result) {
      this.profile = result.profile || {}
      this.profileStatus = result.profile_status || 'pending'
      this.profileError = result.profile_error || ''
      this.profileUpdatedAt = result.profile_updated_at || ''
      this.opponent = result.opponent || null
    },
    profileUpdatedAtFor(clanTag) {
      const key = this.tagKey(clanTag)
      if (key === this.tagKey(this.clan.clan_tag)) return this.profileUpdatedAt || ''
      if (this.opponent && key === this.tagKey(this.opponent.clan_tag)) {
        return this.opponent.profile_updated_at || ''
      }
      return ''
    },
    async load(options = {}) {
      const silent = Boolean(options.silent)
      if (!silent) {
        this.loading = true
        this.error = ''
      }
      let loaded = false
      try {
        if (!this.clanTag) throw new Error('部落标签无效')
        const result = await getFarmClanDetail(this.clanTag)
        if (!options.profilesOnly) {
          this.clan = result.clan || {}
          this.farmRound = result.farm_round || null
          this.farmRegistration = result.farm_registration || null
        }
        this.applyProfileResult(result)
        loaded = true
      } catch (e) {
        if (!silent) this.error = e.message || '加载部落详情失败'
      } finally {
        if (!silent) this.loading = false
      }
      if (loaded && options.requestProfileRefresh) this.requestProfileRefresh()
      return loaded
    },
    async requestProfileRefresh() {
      if (this.profileRefreshSubmitting || !this.clanTag) return
      this.profileRefreshSubmitting = true
      try {
        const response = await requestFarmClanDetailRefresh(this.clanTag)
        const profiles = (response.refresh && response.refresh.profiles) || []
        const pending = profiles.filter(item => OPEN_REFRESH_STATES.indexOf(item.task_status) >= 0)
        if (pending.length) this.startProfilePolling(pending)
      } catch (e) {
        // 页面已有缓存可读；后台资料刷新失败不打断详情浏览。
      } finally {
        this.profileRefreshSubmitting = false
      }
    },
    startProfilePolling(profiles) {
      this.stopProfilePolling()
      this.profilePollBaselines = profiles.reduce((result, item) => {
        result[this.tagKey(item.clan_tag)] = item.profile_updated_at || ''
        return result
      }, {})
      const poll = async () => {
        this.profilePollCount += 1
        await this.load({ silent: true, profilesOnly: true })
        const completed = Object.keys(this.profilePollBaselines).every(tag => {
          const current = this.profileUpdatedAtFor(tag)
          return Boolean(current && current !== this.profilePollBaselines[tag])
        })
        if (completed || this.profilePollCount >= PROFILE_POLL_LIMIT) {
          this.stopProfilePolling()
          return
        }
        this.profilePollTimer = setTimeout(poll, PROFILE_POLL_INTERVAL_MS)
      }
      this.profilePollTimer = setTimeout(poll, PROFILE_POLL_INTERVAL_MS)
    },
    stopProfilePolling() {
      if (this.profilePollTimer) clearTimeout(this.profilePollTimer)
      this.profilePollTimer = null
      this.profilePollCount = 0
      this.profilePollBaselines = {}
    }
  }
}
</script>

<style>
.detail-page { min-height: 100vh; padding: 28rpx 26rpx; box-sizing: border-box; background: #0f0f23; color: #eef1f8; }.page-state { display: flex; min-height: 70vh; flex-direction: column; align-items: center; justify-content: center; gap: 24rpx; color: #7f899f; font-size: 26rpx; }.state-error, .empty-error, .farm-error { color: #cf7e82; }.small-button { padding: 0 32rpx; border: 1rpx solid #31537d; border-radius: 12rpx; background: transparent; color: #76aee6; font-size: 24rpx; }
.status-badge { background: rgba(67,170,115,.14); color: #6fc595; }.status-badge.disabled { background: rgba(193,107,110,.12); color: #be777b; }
.section-heading { display: flex; align-items: center; margin: 34rpx 4rpx 18rpx; }.section-index { display: flex; width: 58rpx; height: 58rpx; align-items: center; justify-content: center; margin-right: 16rpx; border-radius: 16rpx; background: #203c5d; color: #83b9ea; font-size: 20rpx; font-weight: 700; }.section-index.farm { background: #3a2f55; color: #b7a2e8; }.section-index.opponent { background: #4a3927; color: #dbb47c; }.section-name, .section-desc { display: block; }.section-name { font-size: 28rpx; font-weight: 650; }.section-desc { margin-top: 4rpx; color: #68748b; font-size: 19rpx; }
.section-card, .empty-card, .score-card { margin-bottom: 18rpx; border: 1rpx solid #2a3152; border-radius: 18rpx; background: #191a31; }.section-card { padding: 26rpx; }.card-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 18rpx; }.card-title { display: block; font-size: 26rpx; font-weight: 650; }.description { display: block; color: #b4bdce; font-size: 23rpx; line-height: 1.7; white-space: pre-wrap; }
.subtle-badge { padding: 6rpx 13rpx; border-radius: 16rpx; background: #202944; color: #7faedd; font-size: 19rpx; }
.farm-heading { margin-top: 38rpx; }.score-card { display: flex; align-items: center; justify-content: space-between; padding: 26rpx; background: linear-gradient(135deg, #1e2542, #201b39); }.score-label, .score-value, .score-meta text { display: block; }.score-label { color: #8b96ab; font-size: 20rpx; }.score-value { margin-top: 4rpx; color: #8fc3f0; font-size: 44rpx; font-weight: 750; }.score-meta { color: #707b93; font-size: 19rpx; line-height: 1.8; text-align: right; }.farm-status { background: #2b2541; color: #b5a2e3; }.info-row { display: flex; min-height: 70rpx; align-items: center; justify-content: space-between; border-bottom: 1rpx solid #282e4d; }.info-row:last-of-type { border-bottom: 0; }.info-label { flex-shrink: 0; color: #748098; font-size: 22rpx; }.info-value { min-width: 0; margin-left: 24rpx; color: #dce1ec; font-size: 23rpx; text-align: right; }.info-value.muted { color: #6c778e; }.right-copy { min-width: 0; margin-left: 24rpx; text-align: right; }.right-copy .info-value { display: block; margin-left: 0; }.info-subvalue { display: block; margin-top: 5rpx; color: #727d95; font-size: 20rpx; }.result-value { color: #77839a; font-size: 25rpx; font-weight: 650; }.result-value.win { color: #70c395; }.result-value.loss { color: #cf7e82; }.result-value.match_failed { color: #c3a270; }.farm-error { display: block; margin-top: 18rpx; padding: 16rpx; border-radius: 10rpx; background: rgba(193,107,110,.08); font-size: 20rpx; line-height: 1.5; }
.opponent-heading { margin-top: 38rpx; }.clan-profile-card { margin-bottom: 18rpx; overflow: hidden; border: 1rpx solid #2a3152; border-radius: 18rpx; background: #191a31; }.opponent-profile-card { border-color: #3b3442; }.profile-head { display: flex; align-items: center; justify-content: space-between; padding: 26rpx; }.own-profile-head { background: linear-gradient(135deg, #1d203b, #17182e); }.opponent-profile-head { background: linear-gradient(135deg, #242037, #211c2b); }.profile-copy { min-width: 0; }.profile-name, .profile-tag { display: block; }.profile-name { overflow: hidden; font-size: 29rpx; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }.profile-tag { margin-top: 7rpx; color: #82778e; font-size: 21rpx; }.profile-badge { flex-shrink: 0; margin-left: 20rpx; padding: 6rpx 13rpx; border-radius: 16rpx; font-size: 19rpx; }.opponent-source { background: rgba(197,150,92,.12); color: #d0a66f; }.profile-announcement { padding: 24rpx 26rpx; border-top: 1rpx solid #302b40; }.profile-announcement .card-title { margin-bottom: 15rpx; }.profile-empty { padding: 42rpx 26rpx; border-top: 1rpx solid #302b40; text-align: center; }.profile-metrics { display: flex; border-top: 1rpx solid #302b40; }.profile-metric { min-width: 0; padding: 20rpx 8rpx; box-sizing: border-box; text-align: center; }.profile-metrics--three .profile-metric { flex: 1; }.profile-metrics--three .profile-metric + .profile-metric { border-left: 1rpx solid #302b40; }.profile-metrics--four { flex-wrap: wrap; }.profile-metrics--four .profile-metric { width: 50%; }.profile-metrics--four .profile-metric:nth-child(odd) { border-right: 1rpx solid #302b40; }.profile-metrics--four .profile-metric:nth-child(n+3) { border-top: 1rpx solid #302b40; }.profile-metric-value, .profile-metric-label { display: block; }.profile-metric-value { overflow: hidden; font-size: 25rpx; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }.profile-metric-value.compact { padding: 3rpx 10rpx 0; font-size: 21rpx; }.profile-metric-label { margin-top: 6rpx; color: #736c82; font-size: 18rpx; }.profile-cache-time { display: block; padding: 16rpx 26rpx 20rpx; color: #59647a; font-size: 18rpx; }
.empty-card { padding: 56rpx 24rpx; text-align: center; }.empty-title, .empty-desc, .empty-error { display: block; }.empty-title { font-size: 27rpx; }.empty-desc, .empty-error { margin-top: 10rpx; font-size: 21rpx; line-height: 1.5; }.empty-desc { color: #707b93; }.bottom-space { height: 40rpx; }
</style>
