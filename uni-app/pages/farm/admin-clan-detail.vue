<template>
  <view class="detail-page">
    <view v-if="loading" class="page-state">正在加载...</view>
    <view v-else-if="error" class="page-state">
      <text class="state-error">{{ error }}</text>
      <button class="small-button" @tap="load">重新加载</button>
    </view>
    <view v-else>
      <view class="hero-card">
        <view class="hero-copy">
          <text class="clan-name">{{ clan.clan_name }}</text>
          <text class="clan-tag">{{ clan.clan_tag }}</text>
        </view>
        <text class="status-badge" :class="{ disabled: clan.status !== 'active' }">{{ clan.status === 'active' ? '启用' : '停用' }}</text>
      </view>

      <view class="section-heading">
        <text class="section-index">01</text>
        <view><text class="section-name">基本信息</text><text class="section-desc">COC 官方部落资料与当前部落战</text></view>
      </view>

      <view v-if="!hasProfile" class="empty-card">
        <text class="empty-title">暂无可用的官方部落资料</text>
        <text class="empty-desc">缓存状态：{{ profileStatusLabel }}</text>
        <text v-if="profileError" class="empty-error">{{ profileError }}</text>
      </view>
      <block v-else>
        <view class="section-card announcement-card">
          <text class="card-title">部落公告</text>
          <text class="description">{{ profile.description || '该部落暂未设置公告' }}</text>
        </view>
        <view class="metric-grid">
          <view class="metric-item"><text class="metric-value">{{ memberCount }}</text><text class="metric-label">成员人数</text></view>
          <view class="metric-item"><text class="metric-value">{{ profile.clan_level || '-' }}</text><text class="metric-label">部落等级</text></view>
          <view class="metric-item"><text class="metric-value small">{{ locationName }}</text><text class="metric-label">位置</text></view>
          <view class="metric-item"><text class="metric-value small">{{ joinTypeLabel(profile.join_type) }}</text><text class="metric-label">加入方式</text></view>
        </view>
      </block>

      <view class="section-card war-card">
        <view class="card-head"><text class="card-title">当前部落战</text><text class="subtle-badge">{{ currentWarStatusLabel }}</text></view>
        <view v-if="currentWarOpponent" class="opponent-block">
          <view><text class="opponent-label">对手部落</text><text class="opponent-name">{{ currentWarOpponent.name || '未知名称' }}</text><text class="opponent-tag">{{ currentWarOpponent.tag || '标签未知' }}</text></view>
          <view class="war-side"><text v-if="currentWar.team_size" class="war-size">{{ currentWar.team_size }} 人战</text><text class="war-result">{{ officialWarResultLabel }}</text></view>
        </view>
        <view v-else class="empty-line">{{ currentWarEmptyText }}</view>
        <text class="cache-time">官方战争资料更新：{{ formatTime(currentWarUpdatedAt) }}</text>
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

      <view class="cache-note">
        <text>基本资料来源：COC 官方缓存</text>
        <text>更新时间：{{ formatTime(profileUpdatedAt) }}</text>
      </view>
      <view class="bottom-space"></view>
    </view>
  </view>
</template>

<script>
import { getFarmClanDetail } from '@/utils/api.js'

export default {
  data() {
    return {
      clanTag: '',
      clan: {},
      profile: {},
      profileStatus: 'pending',
      profileError: '',
      profileUpdatedAt: '',
      currentWar: {},
      currentWarUpdatedAt: '',
      farmRound: null,
      farmRegistration: null,
      loading: true,
      error: ''
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
    currentWarOpponent() { return this.currentWar && this.currentWar.opponent ? this.currentWar.opponent : null },
    currentWarStatusLabel() {
      const status = this.currentWar && this.currentWar.status
      return ({ preparation: '准备日', in_war: '战斗日', war_ended: '已结束', not_in_war: '未开战', cwl: '部落战联赛', error: '同步失败' })[status] || (status || '暂无数据')
    },
    currentWarEmptyText() {
      if (!this.currentWar || !Object.keys(this.currentWar).length) return '暂无当前部落战资料'
      if (this.currentWar.status === 'not_in_war') return '当前未参加普通部落战'
      if (this.currentWar.status === 'cwl') return '当前为部落战联赛，暂不展示普通战对手'
      return '暂未获取到对手部落'
    },
    officialWarResultLabel() {
      const result = this.currentWar && this.currentWar.result
      return ({ pending: '尚未开战', leading: '当前领先', losing: '当前落后', tied: '当前战平', victory: '胜利', defeat: '失败' })[result] || ''
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
    }
  },
  onLoad(options) {
    try { this.clanTag = decodeURIComponent((options && options.clan_tag) || '') } catch (e) { this.clanTag = '' }
  },
  onShow() { this.load() },
  methods: {
    namedValue(value) { return value && value.name ? value.name : '-' },
    joinTypeLabel(value) { return ({ open: '任何人可加入', inviteOnly: '需要邀请', closed: '不可加入' })[value] || value || '-' },
    formatTime(value) {
      if (!value) return '-'
      const date = new Date(value)
      if (Number.isNaN(date.getTime())) return '-'
      const pad = number => String(number).padStart(2, '0')
      return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
    },
    async load() {
      this.loading = true
      this.error = ''
      try {
        if (!this.clanTag) throw new Error('部落标签无效')
        const result = await getFarmClanDetail(this.clanTag)
        this.clan = result.clan || {}
        this.profile = result.profile || {}
        this.profileStatus = result.profile_status || 'pending'
        this.profileError = result.profile_error || ''
        this.profileUpdatedAt = result.profile_updated_at || ''
        this.currentWar = result.current_war || {}
        this.currentWarUpdatedAt = result.current_war_updated_at || ''
        this.farmRound = result.farm_round || null
        this.farmRegistration = result.farm_registration || null
      } catch (e) {
        this.error = e.message || '加载部落详情失败'
      } finally {
        this.loading = false
      }
    }
  }
}
</script>

<style>
.detail-page { min-height: 100vh; padding: 28rpx 26rpx; box-sizing: border-box; background: #0f0f23; color: #eef1f8; }.page-state { display: flex; min-height: 70vh; flex-direction: column; align-items: center; justify-content: center; gap: 24rpx; color: #7f899f; font-size: 26rpx; }.state-error, .empty-error, .farm-error { color: #cf7e82; }.small-button { padding: 0 32rpx; border: 1rpx solid #31537d; border-radius: 12rpx; background: transparent; color: #76aee6; font-size: 24rpx; }
.hero-card { display: flex; align-items: center; justify-content: space-between; padding: 28rpx; border: 1rpx solid #2a3152; border-radius: 18rpx; background: linear-gradient(135deg, #1d203b, #17182e); }.hero-copy { min-width: 0; }.clan-name, .clan-tag { display: block; }.clan-name { overflow: hidden; font-size: 34rpx; font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }.clan-tag { margin-top: 8rpx; color: #78849d; font-size: 22rpx; }.status-badge { flex-shrink: 0; margin-left: 20rpx; padding: 7rpx 15rpx; border-radius: 18rpx; background: rgba(67,170,115,.14); color: #6fc595; font-size: 21rpx; }.status-badge.disabled { background: rgba(193,107,110,.12); color: #be777b; }
.section-heading { display: flex; align-items: center; margin: 34rpx 4rpx 18rpx; }.section-index { display: flex; width: 58rpx; height: 58rpx; align-items: center; justify-content: center; margin-right: 16rpx; border-radius: 16rpx; background: #203c5d; color: #83b9ea; font-size: 20rpx; font-weight: 700; }.section-index.farm { background: #3a2f55; color: #b7a2e8; }.section-name, .section-desc { display: block; }.section-name { font-size: 28rpx; font-weight: 650; }.section-desc { margin-top: 4rpx; color: #68748b; font-size: 19rpx; }
.section-card, .empty-card, .metric-grid, .score-card { margin-bottom: 18rpx; border: 1rpx solid #2a3152; border-radius: 18rpx; background: #191a31; }.section-card { padding: 26rpx; }.card-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 18rpx; }.card-title { display: block; font-size: 26rpx; font-weight: 650; }.announcement-card .card-title { margin-bottom: 16rpx; }.description { display: block; color: #b4bdce; font-size: 23rpx; line-height: 1.7; white-space: pre-wrap; }
.metric-grid { display: flex; flex-wrap: wrap; overflow: hidden; }.metric-item { width: 50%; padding: 24rpx 12rpx; border-bottom: 1rpx solid #282e4d; box-sizing: border-box; text-align: center; }.metric-item:nth-child(odd) { border-right: 1rpx solid #282e4d; }.metric-item:nth-last-child(-n+2) { border-bottom: 0; }.metric-value, .metric-label { display: block; }.metric-value { overflow: hidden; color: #e7ebf4; font-size: 29rpx; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }.metric-value.small { padding: 4rpx 12rpx 0; font-size: 23rpx; }.metric-label { margin-top: 7rpx; color: #707b93; font-size: 19rpx; }
.subtle-badge { padding: 6rpx 13rpx; border-radius: 16rpx; background: #202944; color: #7faedd; font-size: 19rpx; }.opponent-block { display: flex; align-items: center; justify-content: space-between; padding: 20rpx; border-radius: 14rpx; background: #14162a; }.opponent-label, .opponent-name, .opponent-tag, .war-size, .war-result { display: block; }.opponent-label { color: #647089; font-size: 19rpx; }.opponent-name { margin-top: 8rpx; font-size: 27rpx; font-weight: 600; }.opponent-tag { margin-top: 5rpx; color: #747f97; font-size: 21rpx; }.war-side { flex-shrink: 0; margin-left: 20rpx; text-align: right; }.war-size { color: #8490a6; font-size: 20rpx; }.war-result { margin-top: 7rpx; color: #83b9ea; font-size: 22rpx; }.empty-line { padding: 24rpx 12rpx; border-radius: 14rpx; background: #14162a; color: #737e95; font-size: 22rpx; text-align: center; }.cache-time { display: block; margin-top: 14rpx; color: #59647a; font-size: 18rpx; }
.farm-heading { margin-top: 38rpx; }.score-card { display: flex; align-items: center; justify-content: space-between; padding: 26rpx; background: linear-gradient(135deg, #1e2542, #201b39); }.score-label, .score-value, .score-meta text { display: block; }.score-label { color: #8b96ab; font-size: 20rpx; }.score-value { margin-top: 4rpx; color: #8fc3f0; font-size: 44rpx; font-weight: 750; }.score-meta { color: #707b93; font-size: 19rpx; line-height: 1.8; text-align: right; }.farm-status { background: #2b2541; color: #b5a2e3; }.info-row { display: flex; min-height: 70rpx; align-items: center; justify-content: space-between; border-bottom: 1rpx solid #282e4d; }.info-row:last-of-type { border-bottom: 0; }.info-label { flex-shrink: 0; color: #748098; font-size: 22rpx; }.info-value { min-width: 0; margin-left: 24rpx; color: #dce1ec; font-size: 23rpx; text-align: right; }.info-value.muted { color: #6c778e; }.right-copy { min-width: 0; margin-left: 24rpx; text-align: right; }.right-copy .info-value { display: block; margin-left: 0; }.info-subvalue { display: block; margin-top: 5rpx; color: #727d95; font-size: 20rpx; }.result-value { color: #77839a; font-size: 25rpx; font-weight: 650; }.result-value.win { color: #70c395; }.result-value.loss { color: #cf7e82; }.result-value.match_failed { color: #c3a270; }.farm-error { display: block; margin-top: 18rpx; padding: 16rpx; border-radius: 10rpx; background: rgba(193,107,110,.08); font-size: 20rpx; line-height: 1.5; }
.empty-card { padding: 56rpx 24rpx; text-align: center; }.empty-title, .empty-desc, .empty-error { display: block; }.empty-title { font-size: 27rpx; }.empty-desc, .empty-error { margin-top: 10rpx; font-size: 21rpx; line-height: 1.5; }.empty-desc { color: #707b93; }.cache-note { display: flex; justify-content: space-between; padding: 6rpx 6rpx 20rpx; color: #5f6980; font-size: 18rpx; }.bottom-space { height: 40rpx; }
</style>
