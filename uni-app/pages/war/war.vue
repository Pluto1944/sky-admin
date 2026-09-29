<template>
  <view class="page-container">
    <TopBar title="战斗" :buttons="topButtons" @onTopTab="onTopTab" />

    <view v-if="activeTopTab === 'clan-war'" class="war-pane">
      <view class="war-toolbar">
        <view class="toolbar-title-wrap">
          <text class="toolbar-title">当前部落战</text>
          <text class="toolbar-count">{{ filteredClans.length }}/{{ clans.length }}</text>
        </view>
        <text class="filter-trigger" @tap="openFilter">⏬筛选</text>
      </view>

      <view v-if="loading" class="state-box"><text class="state-text">加载当前部落战...</text></view>
      <view v-else-if="loadError && !clans.length" class="state-box">
        <text class="error-text">{{ loadError }}</text>
        <text class="retry-btn" @tap="fetchCurrentWars">点击重试</text>
      </view>
      <scroll-view v-else scroll-y class="war-list-scroll">
        <view class="war-list-inner">
          <view v-if="updatedAt" class="update-time">数据更新于 {{ formatTime(updatedAt) }}</view>
          <view v-if="isFiltered" class="filter-summary">
            <text>{{ filterLabel }}</text>
            <text class="clear-filter" @tap="resetFilters">重置</text>
          </view>
          <view v-if="!filteredClans.length" class="empty-list">没有符合条件的部落</view>

          <view v-for="clan in filteredClans" :key="clan.clan_tag" class="war-card" @tap="openDetail(clan)">
            <view class="card-header">
              <text class="category-badge" :class="'category-' + clan.category">{{ categoryLabel(clan.category) }}</text>
              <text class="clan-name">{{ clan.clan_name }}</text>
              <text class="clan-tag">{{ clan.clan_tag }}</text>
              <text class="status-badge" :class="'status-' + clan.status">{{ statusLabel(clan.status) }}</text>
            </view>

            <view v-if="clan.status === 'error'" class="simple-state error-state">同步失败：{{ clan.error || '无法获取当前部落战' }}</view>
            <view v-else-if="clan.status === 'sync_pending'" class="simple-state">数据正在同步，请稍后重试</view>
            <view v-else-if="clan.status === 'not_in_war'" class="simple-state">当前无部落战</view>
            <view v-else-if="clan.status === 'cwl'" class="simple-state cwl-state" @tap.stop="onTopTab('league')">当前正在进行联赛，点击前往“联赛 → 战斗日”</view>
            <view v-else class="war-summary">
              <view class="opponent-row">
                <text class="opponent-label">对手</text>
                <text class="opponent-name">{{ clan.opponent ? clan.opponent.name : '-' }}</text>
                <text class="opponent-tag">{{ clan.opponent ? clan.opponent.tag : '' }}</text>
                <text class="result-label" :class="resultClass(clan.result)">{{ resultLabel(clan.result) }}</text>
              </view>
              <view class="score-row">
                <view class="side-score own-score">
                  <text class="side-name">我方</text><text class="stars">{{ clan.clan.stars }}⭐</text>
                  <text>{{ clan.clan.attacks }}/{{ clan.clan.total_attacks }}刀</text><text>{{ formatPercent(clan.clan.destruction_percentage) }}</text>
                </view>
                <text class="versus">VS</text>
                <view class="side-score opponent-score">
                  <text class="side-name">对方</text><text class="stars">{{ clan.opponent.stars }}⭐</text>
                  <text>{{ clan.opponent.attacks }}/{{ clan.opponent.total_attacks }}刀</text><text>{{ formatPercent(clan.opponent.destruction_percentage) }}</text>
                </view>
              </view>
              <view class="card-footer">
                <text class="countdown">{{ countdownLabel(clan) }}</text>
                <view class="card-actions" @tap.stop>
                  <text class="detail-link" @tap="openDetail(clan)">详情 ›</text>
                  <button class="share-btn" open-type="share" :data-clan-tag="clan.clan_tag" :data-clan-name="clan.clan_name">分享</button>
                </view>
              </view>
            </view>
          </view>
          <view class="bottom-space"></view>
        </view>
      </scroll-view>
    </view>

    <view v-else class="content-area">
      <view class="inner-tab-bar">
        <view v-for="tab in leagueTabs" :key="tab.key" class="inner-tab-item" :class="{ active: activeLeagueTab === tab.key }" @tap="switchLeagueTab(tab.key)">{{ tab.label }}</view>
      </view>
      <view class="placeholder-box">
        <text class="placeholder-icon">🏆</text>
        <text class="placeholder-text">{{ activeLeagueTab === 'war-day' ? '战斗日' : '联赛总览' }}</text>
      </view>
    </view>

    <view v-if="filterVisible" class="filter-mask" @tap="closeFilter">
      <view class="filter-panel" @tap.stop>
        <view class="filter-title">筛选当前部落战</view>
        <text class="filter-group-title">部落分类（可多选）</text>
        <view class="filter-options">
          <view v-for="category in categories" :key="category.key" class="filter-option" @tap="toggleDraftCategory(category.key)">
            <text class="filter-check" :class="{ checked: draftCategories.indexOf(category.key) >= 0 }">{{ draftCategories.indexOf(category.key) >= 0 ? '✓' : '' }}</text>
            <text>{{ category.label }}</text>
          </view>
        </view>
        <text class="filter-group-title">战争状态</text>
        <view class="status-filter-options">
          <text v-for="option in statusOptions" :key="option.key" class="status-filter-option" :class="{ active: draftStatus === option.key }" @tap="draftStatus = option.key">{{ option.label }}</text>
        </view>
        <text class="filter-group-title">具体部落（可多选）</text>
        <scroll-view scroll-y class="clan-options">
          <view v-for="clan in clans" :key="clan.clan_tag" class="filter-option clan-option" @tap="toggleDraftClan(clan.clan_tag)">
            <text class="filter-check" :class="{ checked: draftClans.indexOf(clan.clan_tag) >= 0 }">{{ draftClans.indexOf(clan.clan_tag) >= 0 ? '✓' : '' }}</text>
            <text>{{ clan.clan_name }}（{{ clan.clan_tag }}）</text>
          </view>
        </scroll-view>
        <view class="filter-actions">
          <text class="filter-action reset-action" @tap="resetDraftFilters">全选</text>
          <text class="filter-action cancel-action" @tap="closeFilter">取消</text>
          <text class="filter-action confirm-action" @tap="applyFilters">确定</text>
        </view>
      </view>
    </view>
  </view>
</template>

<script>
import TopBar from '@/components/TopBar.vue'
import { getCurrentWars } from '@/utils/api.js'

const STATUS_ORDER = { in_war: 0, preparation: 1, war_ended: 2, cwl: 3, not_in_war: 4, sync_pending: 5, error: 6 }
const CACHE_REFRESH_INTERVAL_MS = 60 * 1000

export default {
  components: { TopBar },
  data() {
    return {
      topButtons: [
        { key: 'clan-war', icon: '⚔️', text: '部落战', action: 'onTopTab' },
        { key: 'league', icon: '🏆', text: '联赛', action: 'onTopTab' }
      ],
      activeTopTab: 'clan-war',
      leagueTabs: [{ key: 'war-day', label: '战斗日' }, { key: 'league-overview', label: '联赛总览' }],
      activeLeagueTab: 'war-day',
      loading: true,
      loadError: '',
      clans: [],
      categories: [],
      updatedAt: '',
      selectedCategories: [],
      selectedClans: [],
      statusFilter: 'all',
      filterInitialized: false,
      filterVisible: false,
      draftCategories: [],
      draftClans: [],
      draftStatus: 'all',
      nowMs: Date.now(),
      clockTimer: null,
      refreshTimer: null,
      statusOptions: [
        { key: 'all', label: '全部' }, { key: 'in_war', label: '战斗日' },
        { key: 'preparation', label: '准备日' }, { key: 'war_ended', label: '已结束' },
        { key: 'cwl', label: '联赛中' }, { key: 'not_in_war', label: '无战争' },
        { key: 'sync_pending', label: '待同步' }, { key: 'error', label: '同步失败' }
      ]
    }
  },
  computed: {
    filteredClans() {
      return this.clans
        .filter(clan => this.selectedCategories.indexOf(clan.category) >= 0)
        .filter(clan => this.selectedClans.indexOf(clan.clan_tag) >= 0)
        .filter(clan => this.statusFilter === 'all' || clan.status === this.statusFilter)
        .slice()
        .sort((a, b) => {
          const statusDiff = (STATUS_ORDER[a.status] == null ? 99 : STATUS_ORDER[a.status]) - (STATUS_ORDER[b.status] == null ? 99 : STATUS_ORDER[b.status])
          return statusDiff || (a.config_order || 0) - (b.config_order || 0)
        })
    },
    isFiltered() {
      return this.selectedCategories.length !== this.categories.length || this.selectedClans.length !== this.clans.length || this.statusFilter !== 'all'
    },
    filterLabel() {
      const labels = []
      if (this.selectedCategories.length !== this.categories.length) labels.push(`分类 ${this.selectedCategories.length}项`)
      if (this.selectedClans.length !== this.clans.length) labels.push(`部落 ${this.selectedClans.length}个`)
      if (this.statusFilter !== 'all') labels.push(this.statusLabel(this.statusFilter))
      return labels.length ? `当前：${labels.join(' · ')}` : '全部部落'
    }
  },
  onLoad() { this.fetchCurrentWars() },
  onShow() {
    this.startTimers()
    if (this.clans.length) this.fetchCurrentWars()
  },
  onHide() { this.stopTimers() },
  onUnload() { this.stopTimers() },
  onShareAppMessage(options) {
    const dataset = options && options.target && options.target.dataset
    if (dataset && dataset.clanTag) {
      return { title: `苍穹联赛助手｜${dataset.clanName || '当前部落战'}`, path: `/pages/war/current-detail?clan_tag=${encodeURIComponent(dataset.clanTag)}` }
    }
    return { title: '苍穹联赛助手｜当前部落战', path: '/pages/war/war' }
  },
  onShareTimeline() { return { title: '苍穹联赛助手｜当前部落战' } },
  methods: {
    onTopTab(tab) {
      this.activeTopTab = tab
      this.filterVisible = false
      if (tab === 'league') this.activeLeagueTab = 'war-day'
    },
    switchLeagueTab(tab) { this.activeLeagueTab = tab },
    async fetchCurrentWars() {
      if (!this.clans.length) this.loading = true
      this.loadError = ''
      try {
        const res = await getCurrentWars()
        this.clans = res.clans || []
        this.categories = res.categories || []
        this.updatedAt = res.updated_at || ''
        if (!this.filterInitialized) {
          this.selectedCategories = this.categories.map(item => item.key)
          this.selectedClans = this.clans.map(item => item.clan_tag)
          this.filterInitialized = true
        }
      } catch (e) {
        this.loadError = e.message || '当前部落战加载失败'
        if (this.clans.length) uni.showToast({ title: this.loadError, icon: 'none' })
      } finally { this.loading = false }
    },
    startTimers() {
      this.stopTimers()
      this.nowMs = Date.now()
      this.clockTimer = setInterval(() => { this.nowMs = Date.now() }, 1000)
      this.refreshTimer = setInterval(() => { this.fetchCurrentWars() }, CACHE_REFRESH_INTERVAL_MS)
    },
    stopTimers() {
      if (this.clockTimer) clearInterval(this.clockTimer)
      if (this.refreshTimer) clearInterval(this.refreshTimer)
      this.clockTimer = null
      this.refreshTimer = null
    },
    openFilter() {
      this.draftCategories = this.selectedCategories.slice()
      this.draftClans = this.selectedClans.slice()
      this.draftStatus = this.statusFilter
      this.filterVisible = true
    },
    closeFilter() { this.filterVisible = false },
    toggleDraftCategory(key) {
      const index = this.draftCategories.indexOf(key)
      if (index >= 0) this.draftCategories.splice(index, 1)
      else this.draftCategories.push(key)
    },
    toggleDraftClan(tag) {
      const index = this.draftClans.indexOf(tag)
      if (index >= 0) this.draftClans.splice(index, 1)
      else this.draftClans.push(tag)
    },
    resetDraftFilters() {
      this.draftCategories = this.categories.map(item => item.key)
      this.draftClans = this.clans.map(item => item.clan_tag)
      this.draftStatus = 'all'
    },
    resetFilters() {
      this.selectedCategories = this.categories.map(item => item.key)
      this.selectedClans = this.clans.map(item => item.clan_tag)
      this.statusFilter = 'all'
    },
    applyFilters() {
      this.selectedCategories = this.draftCategories.slice()
      this.selectedClans = this.draftClans.slice()
      this.statusFilter = this.draftStatus
      this.filterVisible = false
    },
    openDetail(clan) {
      if (['not_in_war', 'sync_pending', 'error'].indexOf(clan.status) >= 0) return
      uni.navigateTo({ url: `/pages/war/current-detail?clan_tag=${encodeURIComponent(clan.clan_tag)}` })
    },
    categoryLabel(key) {
      const item = this.categories.find(category => category.key === key)
      return item ? item.label : key
    },
    statusLabel(status) {
      return ({ in_war: '战斗日', preparation: '准备日', war_ended: '已结束', not_in_war: '无战争', cwl: '联赛中', sync_pending: '待同步', error: '同步失败' })[status] || status
    },
    resultLabel(result) {
      return ({ leading: '当前领先', losing: '当前落后', tied: '当前平局', victory: '胜利', defeat: '失败', pending: '尚未开战' })[result] || '-'
    },
    resultClass(result) {
      if (['leading', 'victory'].indexOf(result) >= 0) return 'result-win'
      if (['losing', 'defeat'].indexOf(result) >= 0) return 'result-loss'
      return 'result-tied'
    },
    formatPercent(value) { return `${Number(value || 0).toFixed(2)}%` },
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
      if (!date) return value || '-'
      const month = String(date.getMonth() + 1).padStart(2, '0')
      const day = String(date.getDate()).padStart(2, '0')
      const hour = String(date.getHours()).padStart(2, '0')
      const minute = String(date.getMinutes()).padStart(2, '0')
      return `${month}-${day} ${hour}:${minute}`
    },
    countdownLabel(clan) {
      if (clan.status === 'war_ended') return `结束于 ${this.formatTime(clan.end_time)}`
      const preparation = clan.status === 'preparation'
      const target = this.parseTime(preparation ? clan.start_time : clan.end_time)
      if (!target) return '-'
      const seconds = Math.max(0, Math.floor((target.getTime() - this.nowMs) / 1000))
      const days = Math.floor(seconds / 86400)
      const hours = Math.floor((seconds % 86400) / 3600)
      const minutes = Math.floor((seconds % 3600) / 60)
      return `${preparation ? '距离开战' : '距离结束'} ${days ? days + '天 ' : ''}${hours}小时${minutes}分钟`
    }
  }
}
</script>

<style>
.page-container { height: 100vh; display: flex; flex-direction: column; background: #0f0f23; }
.war-pane, .content-area { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.war-toolbar { flex-shrink: 0; height: 72rpx; padding: 0 24rpx; display: flex; align-items: center; justify-content: space-between; background: #141428; border-bottom: 1rpx solid #2a2a4a; }
.toolbar-title-wrap { display: flex; align-items: center; }.toolbar-title { color: #d8dce8; font-size: 28rpx; font-weight: 600; }.toolbar-count { margin-left: 12rpx; color: #66708a; font-size: 22rpx; }.filter-trigger { padding: 12rpx; color: #aab4c8; font-size: 25rpx; }
.state-box { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; }.state-text { color: #8890a0; font-size: 28rpx; }.error-text { margin: 0 32rpx 20rpx; color: #e17055; font-size: 26rpx; text-align: center; }.retry-btn { color: #5fa8ff; font-size: 26rpx; }
.war-list-scroll { flex: 1; height: 0; }.war-list-inner { padding: 18rpx 24rpx 0; }.update-time { margin-bottom: 14rpx; color: #596178; font-size: 22rpx; text-align: center; }.filter-summary { display: flex; align-items: center; justify-content: center; margin-bottom: 16rpx; padding: 12rpx; color: #9aa0b0; font-size: 22rpx; background: #15152a; border-radius: 8rpx; }.clear-filter { margin-left: 18rpx; color: #5fa8ff; }.empty-list { padding: 100rpx 0; color: #66708a; font-size: 26rpx; text-align: center; }
.war-card { margin-bottom: 20rpx; overflow: hidden; border: 1rpx solid #2a2a4a; border-radius: 14rpx; background: #18182d; box-sizing: border-box; }.card-header { min-height: 68rpx; padding: 14rpx 18rpx; display: flex; align-items: center; box-sizing: border-box; border-bottom: 1rpx solid #282844; }.category-badge { flex-shrink: 0; margin-right: 10rpx; padding: 3rpx 9rpx; border-radius: 6rpx; color: #9fc9ff; background: rgba(74,144,217,.18); font-size: 20rpx; }.category-farm { color: #7fd8a8; background: rgba(0,184,148,.15); }.category-flat { color: #d9b8ff; background: rgba(162,111,212,.16); }.clan-name { min-width: 0; overflow: hidden; color: #f0f0f5; font-size: 28rpx; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }.clan-tag { flex-shrink: 0; margin-left: 8rpx; color: #66708a; font-size: 20rpx; }.status-badge { flex-shrink: 0; margin-left: auto; padding-left: 12rpx; color: #8890a0; font-size: 22rpx; }.status-in_war { color: #ff7675; }.status-preparation { color: #fdcb6e; }.status-war_ended { color: #74b9ff; }.status-error { color: #e17055; }
.simple-state { padding: 28rpx 20rpx; color: #7d8498; font-size: 25rpx; text-align: center; }.error-state { color: #e17055; }.cwl-state { color: #74b9ff; }
.war-summary { padding: 18rpx; }.opponent-row { display: flex; align-items: center; }.opponent-label { margin-right: 10rpx; color: #66708a; font-size: 22rpx; }.opponent-name { max-width: 280rpx; overflow: hidden; color: #d8dce8; font-size: 26rpx; text-overflow: ellipsis; white-space: nowrap; }.opponent-tag { margin-left: 8rpx; color: #596178; font-size: 20rpx; }.result-label { margin-left: auto; font-size: 23rpx; font-weight: 600; }.result-win { color: #00b894; }.result-loss { color: #e17055; }.result-tied { color: #fdcb6e; }
.score-row { margin-top: 18rpx; display: flex; align-items: center; }.side-score { flex: 1; display: flex; align-items: center; color: #9aa0b0; font-size: 22rpx; }.side-score text { margin-right: 10rpx; }.opponent-score { justify-content: flex-end; }.opponent-score text { margin-right: 0; margin-left: 10rpx; }.side-name { color: #66708a; }.stars { color: #f0f0f5; font-weight: 600; }.versus { margin: 0 12rpx; color: #4a90d9; font-size: 22rpx; font-weight: 600; }
.card-footer { margin-top: 18rpx; padding-top: 14rpx; display: flex; align-items: center; border-top: 1rpx solid #252540; }.countdown { color: #747c91; font-size: 22rpx; }.card-actions { margin-left: auto; display: flex; align-items: center; }.detail-link { padding: 8rpx 12rpx; color: #5fa8ff; font-size: 23rpx; }.share-btn { margin: 0 0 0 8rpx; padding: 8rpx 12rpx; border: 0; border-radius: 6rpx; color: #aab4c8; background: #252540; font-size: 23rpx; line-height: 1.4; }.share-btn::after { border: 0; }.bottom-space { height: 120rpx; }
.filter-mask { position: fixed; z-index: 1000; top: 0; right: 0; bottom: 0; left: 0; display: flex; align-items: flex-end; background: rgba(0,0,0,.6); }.filter-panel { width: 100%; max-height: 82vh; padding: 26rpx 30rpx 34rpx; box-sizing: border-box; border-radius: 24rpx 24rpx 0 0; background: #1a1a2e; }.filter-title { margin-bottom: 20rpx; color: #fff; font-size: 31rpx; font-weight: 600; text-align: center; }.filter-group-title { display: block; margin: 16rpx 0 10rpx; color: #8890a0; font-size: 23rpx; }.filter-options { display: flex; flex-wrap: wrap; }.filter-option { min-height: 62rpx; margin-right: 26rpx; display: flex; align-items: center; color: #d0d0dc; font-size: 25rpx; }.filter-check { width: 34rpx; height: 34rpx; margin-right: 9rpx; display: flex; align-items: center; justify-content: center; box-sizing: border-box; border: 2rpx solid #66708a; border-radius: 5rpx; color: #fff; }.filter-check.checked { border-color: #4a90d9; background: #4a90d9; }.status-filter-options { display: flex; flex-wrap: wrap; }.status-filter-option { margin: 0 12rpx 12rpx 0; padding: 10rpx 17rpx; border-radius: 8rpx; color: #9097aa; background: #252540; font-size: 23rpx; }.status-filter-option.active { color: #fff; background: #4a90d9; }.clan-options { max-height: 320rpx; border-top: 1rpx solid #2a2a4a; border-bottom: 1rpx solid #2a2a4a; }.clan-option { margin-right: 0; padding: 0 6rpx; border-bottom: 1rpx solid #252540; }.filter-actions { margin-top: 22rpx; display: flex; justify-content: flex-end; }.filter-action { min-width: 110rpx; margin-left: 14rpx; padding: 14rpx 20rpx; border-radius: 7rpx; text-align: center; font-size: 25rpx; }.reset-action { color: #74b9ff; }.cancel-action { color: #aab4c8; background: #252540; }.confirm-action { color: #fff; background: #4a90d9; }
.inner-tab-bar { display: flex; flex-shrink: 0; height: 72rpx; background: #141428; border-bottom: 1rpx solid #1a1a2e; }.inner-tab-item { flex: 1; display: flex; align-items: center; justify-content: center; color: #7d8498; font-size: 27rpx; }.inner-tab-item.active { color: #5fa8ff; font-weight: 600; border-bottom: 4rpx solid #4a90d9; }.placeholder-box { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; }.placeholder-icon { margin-bottom: 22rpx; font-size: 72rpx; }.placeholder-text { color: #d8dce8; font-size: 34rpx; }
</style>
