<template>
  <view class="page-container">
    <TopBar title="战斗" :buttons="topButtons" @onTopTab="onTopTab" />

    <view v-if="activeTopTab === 'clan-war'" class="war-pane">
      <view class="war-toolbar">
        <view class="toolbar-title-wrap">
          <text class="toolbar-title">部落战</text>
          <text class="toolbar-count">{{ activeWarCount }}/{{ activeWarTotal }}</text>
        </view>
        <view class="toolbar-actions">
          <picker :range="warViewOptions" range-key="label" :value="warViewIndex" @change="onWarViewChange">
            <text class="period-selector war-view-selector">{{ warViewLabel }}⌄</text>
          </picker>
          <text class="filter-trigger" @tap="openFilter">⏬筛选</text>
        </view>
      </view>

      <view v-if="warView === 'current' && loading" class="state-box"><text class="state-text">加载当前部落战...</text></view>
      <view v-else-if="warView === 'current' && loadError && !clans.length" class="state-box">
        <text class="error-text">{{ loadError }}</text>
        <text class="retry-btn" @tap="fetchCurrentWars">点击重试</text>
      </view>
      <scroll-view v-else-if="warView === 'current'" scroll-y class="war-list-scroll">
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
            <view v-else-if="clan.status === 'cwl'" class="simple-state cwl-state" @tap.stop="onTopTab('league')">当前正在进行联赛，点击前往“联赛数据 → 战斗日”</view>
            <view v-else class="war-summary">
              <view v-if="clan.is_stale" class="sync-warning">本次更新失败，当前显示 {{ formatTime(clan.synced_at) }} 的缓存数据，系统将自动重试</view>
              <view class="opponent-row">
                <text class="opponent-label">对手</text>
                <text class="opponent-name">{{ clan.opponent ? clan.opponent.name : '-' }}</text>
                <text class="opponent-tag">{{ clan.opponent ? clan.opponent.tag : '' }}</text>
                <text class="result-label" :class="warPhaseResultClass(clan.status)">{{ resultLabel(clan.result) }}</text>
              </view>
              <view class="score-row">
                <view class="side-score own-score">
                  <text class="side-name">我方</text><text class="stars">{{ clan.clan.stars }}⭐</text>
                  <text class="attack-count">{{ clan.clan.attacks }}/{{ clan.clan.total_attacks }}</text><text>{{ formatPercent(clan.clan.destruction_percentage) }}</text>
                </view>
                <text class="versus">VS</text>
                <view class="side-score opponent-score">
                  <text class="side-name">对方</text><text class="stars">{{ clan.opponent.stars }}⭐</text>
                  <text class="attack-count">{{ clan.opponent.attacks }}/{{ clan.opponent.total_attacks }}</text><text>{{ formatPercent(clan.opponent.destruction_percentage) }}</text>
                </view>
              </view>
              <view class="card-footer">
                <text class="countdown">{{ countdownLabel(clan) }}</text>
                <view class="card-actions" @tap.stop>
                  <text class="detail-link" @tap="openDetail(clan)">详情 ›</text>
                  <button class="share-btn" open-type="share" data-share-type="current-war" :data-clan-tag="clan.clan_tag" :data-clan-name="clan.clan_name">分享</button>
                </view>
              </view>
            </view>
          </view>
          <view class="bottom-space"></view>
        </view>
      </scroll-view>

      <view v-if="warView === 'history' && historyLoading" class="state-box"><text class="state-text">加载最近部落战...</text></view>
      <view v-else-if="warView === 'history' && historyError && !historyWars.length" class="state-box">
        <text class="error-text">{{ historyError }}</text>
        <text class="retry-btn" @tap="fetchWarHistory">点击重试</text>
      </view>
      <scroll-view v-else-if="warView === 'history'" scroll-y class="war-list-scroll">
        <view class="war-list-inner">
          <view v-if="historyUpdatedAt" class="update-time">数据更新于 {{ formatTime(historyUpdatedAt) }}</view>
          <view v-if="selectedHistoryClan" class="history-scope">
            <text class="history-scope-name">{{ selectedHistoryClan.clan_name }}</text>
            <text class="history-scope-meta">{{ categoryLabel(selectedHistoryClan.category) }} · {{ selectedHistoryClan.clan_tag }} · 最近15场</text>
          </view>
          <view v-if="isFiltered" class="filter-summary">
            <text>{{ filterLabel }}</text><text class="clear-filter" @tap="resetFilters">重置</text>
          </view>
          <view v-if="!filteredHistoryWars.length" class="empty-list">暂无符合条件的历史部落战</view>
          <view v-for="war in filteredHistoryWars" :key="war.war_key" class="war-card history-card" @tap="openHistoryDetail(war)">
            <view class="card-header">
              <text class="category-badge" :class="'category-' + war.category">{{ categoryLabel(war.category) }}</text>
              <text class="clan-name">{{ war.clan_name }}</text>
              <text class="clan-tag">{{ war.clan_tag }}</text>
              <text class="result-label result-ended">{{ resultLabel(war.result) }}</text>
            </view>
            <view class="opponent-row history-opponent-row">
              <text class="opponent-label">对手</text><text class="opponent-name">{{ war.opponent ? war.opponent.name : '-' }}</text><text class="opponent-tag">{{ war.opponent ? war.opponent.tag : '' }}</text>
            </view>
            <view class="score-row history-score-row">
              <view class="side-score own-score"><text>{{ war.clan.stars }}⭐</text><text>{{ formatPercent(war.clan.destruction_percentage) }}</text></view>
              <text class="versus">VS</text>
              <view class="side-score opponent-score"><text>{{ war.opponent.stars }}⭐</text><text>{{ formatPercent(war.opponent.destruction_percentage) }}</text></view>
            </view>
            <view class="card-footer">
              <text class="countdown">{{ formatFullDate(war.end_time) }} · {{ war.team_size }}人战</text>
              <view class="card-actions" @tap.stop>
                <text class="detail-link" @tap="openHistoryDetail(war)">详情 ›</text>
                <button class="share-btn" open-type="share" data-share-type="war-history" :data-clan-tag="war.clan_tag" :data-clan-name="war.clan_name" :data-war-key="war.war_key">分享</button>
              </view>
            </view>
          </view>
          <view class="bottom-space"></view>
        </view>
      </scroll-view>
    </view>

    <view v-else-if="activeTopTab === 'league'" class="war-pane">
      <view class="war-toolbar">
        <view class="toolbar-title-wrap">
          <text class="toolbar-title">联赛参赛部落</text>
          <text class="toolbar-count">{{ leagueClans.length }}</text>
        </view>
        <picker v-if="leaguePeriods.length" :range="leaguePeriods" range-key="label" :value="leaguePeriodIndex" @change="onLeaguePeriodChange">
          <text class="period-selector">{{ leaguePeriodLabel }}⌄</text>
        </picker>
        <text v-else class="period-label">{{ leaguePeriod || '-' }}</text>
      </view>

      <view v-if="leagueLoading" class="state-box"><text class="state-text">加载联赛队伍...</text></view>
      <view v-else-if="leagueError && !leagueClans.length" class="state-box">
        <text class="error-text">{{ leagueError }}</text>
        <text class="retry-btn" @tap="fetchCwlLive">点击重试</text>
      </view>
      <scroll-view v-else scroll-y class="war-list-scroll">
        <view class="war-list-inner">
          <view v-if="leagueUpdatedAt" class="update-time">数据更新于 {{ formatTime(leagueUpdatedAt) }}</view>
          <view v-if="!leagueClans.length" class="empty-list">该月尚未生成联赛队伍</view>

          <view v-for="clan in leagueClans" :key="clan.team_index" class="war-card league-card" @tap="openLeagueDetail(clan)">
            <view class="card-header">
              <text class="category-badge" :class="'category-' + clan.category">{{ leagueCategoryLabel(clan.category) }}</text>
              <text class="clan-name">{{ clan.team_name || clan.team_alias }}</text>
              <text class="clan-tag">{{ clan.clan_tag || '缺少标签' }}</text>
              <text class="status-badge" :class="'league-status-' + clan.status">{{ leagueStatusLabel(clan.status) }}</text>
            </view>
            <view class="league-management-row">
              <text class="league-leader">首领：{{ clan.leader_name || '-' }}</text>
              <text class="league-managers">联赛管理：{{ clan.manager_names || '-' }}</text>
            </view>

            <view v-if="clan.status === 'error'" class="simple-state error-state">
              <text>{{ clan.error || '联赛数据同步失败' }}</text>
              <text class="detail-link state-detail-link">查看详情 ›</text>
            </view>
            <view v-else-if="clan.status === 'waiting'" class="simple-state">
              <text class="league-alias">{{ clan.team_alias }} · {{ clan.league_level || '未定级' }}</text>
              <text class="waiting-hint">{{ clan.error || '等待联赛开启' }}</text>
              <text class="detail-link state-detail-link">查看详情 ›</text>
            </view>
            <view v-else class="league-summary">
              <view class="league-primary-row">
                <text>{{ clan.team_alias }} · {{ clan.league_level || '未定级' }}</text>
                <text v-if="clan.rank" class="league-rank">当前第{{ clan.rank }}名</text>
              </view>
              <view class="league-metrics">
                <text>第{{ clan.current_round || '-' }}场</text>
                <text>{{ leagueResultSummary(clan) }}</text>
                <text>{{ clan.attack_stars || 0 }}⭐</text>
                <text>{{ formatPercent(clan.average_destruction) }}</text>
              </view>
              <view class="card-footer">
                <text class="countdown">{{ clan.member_count || 0 }}人队 · {{ clan.category === 'shell' ? '壳子队' : '实战队' }}</text>
                <view class="card-actions" @tap.stop>
                  <text class="detail-link" @tap="openLeagueDetail(clan)">详情 ›</text>
                  <button class="share-btn" open-type="share" data-share-type="cwl" :data-clan-tag="clan.clan_tag" :data-clan-name="clan.team_name || clan.team_alias" :data-period="leaguePeriod">分享</button>
                </view>
              </view>
            </view>
          </view>
          <view class="bottom-space"></view>
        </view>
      </scroll-view>
    </view>

    <CwlCheckIn
      v-else
      ref="checkIn"
      class="check-in-host"
      :initial-view="checkInView"
      @view-change="onCheckInViewChange"
    />

    <view v-if="filterVisible" class="filter-mask" @tap="closeFilter">
      <view class="filter-panel" @tap.stop>
        <view class="filter-title">{{ warView === 'history' ? '筛选最近部落战' : '筛选当前部落战' }}</view>
        <text v-if="warView !== 'history'" class="filter-group-title">部落分类（可多选）</text>
        <view v-if="warView !== 'history'" class="filter-options">
          <view v-for="category in activeCategories" :key="category.key" class="filter-option" @tap="toggleDraftCategory(category.key)">
            <text class="filter-check" :class="{ checked: draftCategories.indexOf(category.key) >= 0 }">{{ draftCategories.indexOf(category.key) >= 0 ? '✓' : '' }}</text>
            <text>{{ category.label }}</text>
          </view>
        </view>
        <text class="filter-group-title">{{ warView === 'history' ? '战争结果' : '战争状态' }}</text>
        <view class="status-filter-options">
          <text v-for="option in activeFilterOptions" :key="option.key" class="status-filter-option" :class="{ active: draftStatus === option.key }" @tap="draftStatus = option.key">{{ option.label }}</text>
        </view>
        <text v-if="warView !== 'history'" class="filter-group-title">具体部落（可多选）</text>
        <scroll-view v-if="warView !== 'history'" scroll-y class="clan-options">
          <view v-for="clan in activeClanOptions" :key="clan.clan_tag" class="filter-option clan-option" @tap="toggleDraftClan(clan.clan_tag)">
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
import CwlCheckIn from './check-in.vue'
import { getCurrentWars, getWarHistory, getCwlLive } from '@/utils/api.js'

const CACHE_REFRESH_INTERVAL_MS = 60 * 1000
const BUSINESS_TIMEZONE_OFFSET_MS = 8 * 60 * 60 * 1000

function currentBusinessPeriod() {
  const date = new Date(Date.now() + BUSINESS_TIMEZONE_OFFSET_MS)
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, '0')}`
}

function consumeReturnTopTab() {
  const app = getApp()
  if (!app || !app.globalData) return ''
  const tab = app.globalData.warReturnTopTab || ''
  app.globalData.warReturnTopTab = ''
  return tab
}

function rememberReturnTopTab(tab) {
  const app = getApp()
  if (app && app.globalData) app.globalData.warReturnTopTab = tab
}

export default {
  components: { TopBar, CwlCheckIn },
  data() {
    return {
      activeTopTab: 'clan-war',
      checkInView: 'attack',
      warView: 'current',
      selectedHistoryClanTag: '',
      loading: true,
      loadError: '',
      clans: [],
      categories: [],
      updatedAt: '',
      historyLoading: false,
      historyError: '',
      historyWars: [],
      historyCategories: [],
      historyClans: [],
      historyUpdatedAt: '',
      historyResultFilter: 'all',
      leagueLoading: false,
      leagueError: '',
      leagueClans: [],
      leaguePeriod: '',
      leagueUpdatedAt: '',
      leaguePeriods: [],
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
      ],
      resultOptions: [
        { key: 'all', label: '全部' }, { key: 'victory', label: '胜利' },
        { key: 'defeat', label: '失败' }, { key: 'tied', label: '平局' }
      ]
    }
  },
  computed: {
    topButtons() {
      return [
        { key: 'clan-war', icon: '⚔️', text: '部落战', action: 'onTopTab', active: this.activeTopTab === 'clan-war' },
        { key: 'league', icon: '🏆', text: '联赛数据', action: 'onTopTab', active: this.activeTopTab === 'league' },
        { key: 'check-in', icon: '📋', text: '联赛点名', action: 'onTopTab', active: this.activeTopTab === 'check-in' }
      ]
    },
    filteredClans() {
      return this.clans
        .filter(clan => this.selectedCategories.indexOf(clan.category) >= 0)
        .filter(clan => this.selectedClans.indexOf(clan.clan_tag) >= 0)
        .filter(clan => this.statusFilter === 'all' || clan.status === this.statusFilter)
        .slice()
        .sort((a, b) => (a.config_order == null ? 9999 : a.config_order) - (b.config_order == null ? 9999 : b.config_order))
    },
    filteredHistoryWars() {
      return this.historyWars
        .filter(war => war.clan_tag === this.selectedHistoryClanTag)
        .filter(war => this.historyResultFilter === 'all' || war.result === this.historyResultFilter)
    },
    selectedHistoryClan() { return this.historyClans.find(clan => clan.clan_tag === this.selectedHistoryClanTag) || null },
    selectedHistoryWarTotal() { return this.historyWars.filter(war => war.clan_tag === this.selectedHistoryClanTag).length },
    warViewOptions() {
      const clans = this.historyClans.length ? this.historyClans : this.clans
      return [{ key: 'current', view: 'current', label: '当前部落战' }].concat(clans.map(clan => ({
        key: `history:${clan.clan_tag}`,
        view: 'history',
        clanTag: clan.clan_tag,
        label: `${clan.clan_name} · ${this.categoryLabel(clan.category)} · 最近15场`
      })))
    },
    activeCategories() { return this.categories },
    activeClanOptions() { return this.clans },
    activeFilterOptions() { return this.warView === 'history' ? this.resultOptions : this.statusOptions },
    activeWarCount() { return this.warView === 'history' ? this.filteredHistoryWars.length : this.filteredClans.length },
    activeWarTotal() { return this.warView === 'history' ? this.selectedHistoryWarTotal : this.clans.length },
    warViewIndex() {
      const key = this.warView === 'history' ? `history:${this.selectedHistoryClanTag}` : 'current'
      const index = this.warViewOptions.findIndex(item => item.key === key)
      return index < 0 ? 0 : index
    },
    warViewLabel() { const item = this.warViewOptions[this.warViewIndex]; return item ? item.label : '当前部落战' },
    isFiltered() {
      if (this.warView === 'history') return this.historyResultFilter !== 'all'
      const stateFiltered = this.statusFilter !== 'all'
      return this.selectedCategories.length !== this.activeCategories.length || this.selectedClans.length !== this.activeClanOptions.length || stateFiltered
    },
    filterLabel() {
      const labels = []
      if (this.warView === 'history') {
        if (this.historyResultFilter !== 'all') labels.push(this.resultLabel(this.historyResultFilter))
        return labels.length ? `当前：${labels.join(' · ')}` : '全部结果'
      }
      if (this.selectedCategories.length !== this.activeCategories.length) labels.push(`分类 ${this.selectedCategories.length}项`)
      if (this.selectedClans.length !== this.activeClanOptions.length) labels.push(`部落 ${this.selectedClans.length}个`)
      if (this.statusFilter !== 'all') labels.push(this.statusLabel(this.statusFilter))
      return labels.length ? `当前：${labels.join(' · ')}` : '全部部落'
    },
    leaguePeriodIndex() { const index = this.leaguePeriods.findIndex(item => item.period === this.leaguePeriod); return index < 0 ? 0 : index },
    leaguePeriodLabel() { const item = this.leaguePeriods[this.leaguePeriodIndex]; return item ? item.label : (this.leaguePeriod || '-') },
    isCurrentLeaguePeriod() { return !this.leaguePeriod || this.leaguePeriod === currentBusinessPeriod() }
  },
  onLoad(options) {
    if (options && ['league', 'check-in'].indexOf(options.tab) >= 0) this.activeTopTab = options.tab
    if (options && options.check_in_view === 'arrival') this.checkInView = 'arrival'
    if (options && options.view === 'history') {
      this.warView = 'history'
      try { this.selectedHistoryClanTag = decodeURIComponent(options.clan_tag || '') } catch (e) { this.selectedHistoryClanTag = options.clan_tag || '' }
    }
    if (options && options.period) this.leaguePeriod = options.period
    if (this.activeTopTab === 'league') this.fetchCwlLive(this.leaguePeriod)
    else if (this.activeTopTab === 'check-in') return
    else if (this.warView === 'history') this.fetchWarHistory()
    else this.fetchCurrentWars()
  },
  onShow() {
    const returnTab = consumeReturnTopTab()
    if (['clan-war', 'league', 'check-in'].indexOf(returnTab) >= 0) this.activeTopTab = returnTab
    this.startTimers()
    if (this.activeTopTab === 'check-in') this.$nextTick(() => { if (this.$refs.checkIn) this.$refs.checkIn.startTimers() })
    if (this.activeTopTab === 'league' && this.leagueClans.length && this.isCurrentLeaguePeriod) this.fetchCwlLive(this.leaguePeriod)
    else if (this.activeTopTab === 'clan-war' && this.warView === 'current' && this.clans.length) this.fetchCurrentWars()
  },
  onHide() {
    this.stopTimers()
    if (this.$refs.checkIn) this.$refs.checkIn.stopTimers()
  },
  onUnload() {
    this.stopTimers()
    if (this.$refs.checkIn) this.$refs.checkIn.stopTimers()
  },
  onShareAppMessage(options) {
    const dataset = options && options.target && options.target.dataset
    if (dataset && dataset.shareType === 'cwl' && dataset.clanTag) {
      return { title: `苍穹联赛助手｜${dataset.clanName || '联赛战斗日'}`, path: `/pages/war/cwl-detail?clan_tag=${encodeURIComponent(dataset.clanTag)}&period=${encodeURIComponent(dataset.period || this.leaguePeriod)}&view=war-day` }
    }
    if (dataset && dataset.shareType === 'war-history' && dataset.clanTag && dataset.warKey) {
      return { title: `苍穹联赛助手｜${dataset.clanName || '历史部落战'}`, path: `/pages/war/current-detail?clan_tag=${encodeURIComponent(dataset.clanTag)}&war_key=${encodeURIComponent(dataset.warKey)}` }
    }
    if (dataset && dataset.clanTag) {
      return { title: `苍穹联赛助手｜${dataset.clanName || '当前部落战'}`, path: `/pages/war/current-detail?clan_tag=${encodeURIComponent(dataset.clanTag)}` }
    }
    if (this.activeTopTab === 'league') return { title: `苍穹联赛助手｜${this.leaguePeriodLabel}联赛`, path: `/pages/war/war?tab=league&period=${encodeURIComponent(this.leaguePeriod)}` }
    if (this.activeTopTab === 'check-in') return { title: '苍穹联赛助手｜联赛点名', path: `/pages/war/war?tab=check-in&check_in_view=${this.checkInView}` }
    if (this.warView === 'history') return { title: `苍穹联赛助手｜${this.selectedHistoryClan ? this.selectedHistoryClan.clan_name : '历史部落战'}`, path: `/pages/war/war?view=history&clan_tag=${encodeURIComponent(this.selectedHistoryClanTag)}` }
    return { title: '苍穹联赛助手｜当前部落战', path: '/pages/war/war' }
  },
  onShareTimeline() {
    if (this.activeTopTab === 'league') return { title: `苍穹联赛助手｜${this.leaguePeriodLabel}联赛`, query: `tab=league&period=${encodeURIComponent(this.leaguePeriod)}` }
    if (this.activeTopTab === 'check-in') return { title: '苍穹联赛助手｜联赛点名', query: `tab=check-in&check_in_view=${this.checkInView}` }
    return { title: this.warView === 'history' ? `苍穹联赛助手｜${this.selectedHistoryClan ? this.selectedHistoryClan.clan_name : '历史部落战'}` : '苍穹联赛助手｜当前部落战', query: this.warView === 'history' ? `view=history&clan_tag=${encodeURIComponent(this.selectedHistoryClanTag)}` : '' }
  },
  methods: {
    onTopTab(tab) {
      this.activeTopTab = tab
      this.filterVisible = false
      if (tab === 'league' && !this.leagueClans.length) this.fetchCwlLive()
      if (tab === 'clan-war' && this.warView === 'history' && !this.historyWars.length) this.fetchWarHistory()
      if (tab === 'clan-war' && this.warView === 'current') this.fetchCurrentWars()
    },
    onCheckInViewChange(view) { this.checkInView = view },
    switchWarView(option) {
      if (!option) return
      if (option.view === this.warView && (option.view !== 'history' || option.clanTag === this.selectedHistoryClanTag)) return
      this.warView = option.view
      this.selectedHistoryClanTag = option.clanTag || ''
      this.filterVisible = false
      if (option.view === 'history' && !this.historyWars.length) this.fetchWarHistory()
      else {
        this.resetFilters()
        if (option.view === 'current') this.fetchCurrentWars()
      }
    },
    onWarViewChange(event) {
      const selected = this.warViewOptions[Number(event.detail.value)]
      if (selected) this.switchWarView(selected)
    },
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
    async fetchWarHistory() {
      if (!this.historyWars.length) this.historyLoading = true
      this.historyError = ''
      try {
        const res = await getWarHistory()
        this.historyWars = res.wars || []
        this.historyCategories = res.categories || []
        this.historyClans = res.clans || []
        this.historyUpdatedAt = res.updated_at || ''
        if (!this.historyClans.some(clan => clan.clan_tag === this.selectedHistoryClanTag)) {
          const firstWithHistory = this.historyClans.find(clan => this.historyWars.some(war => war.clan_tag === clan.clan_tag))
          this.selectedHistoryClanTag = firstWithHistory ? firstWithHistory.clan_tag : (this.historyClans[0] ? this.historyClans[0].clan_tag : '')
        }
        if (this.warView === 'history') this.resetFilters()
      } catch (e) {
        this.historyError = e.message || '历史部落战加载失败'
        if (this.historyWars.length) uni.showToast({ title: this.historyError, icon: 'none' })
      } finally { this.historyLoading = false }
    },
    async fetchCwlLive(period) {
      const selected = typeof period === 'string' ? period : this.leaguePeriod
      if (!this.leagueClans.length) this.leagueLoading = true
      this.leagueError = ''
      try {
        const res = await getCwlLive(selected)
        this.leagueClans = res.clans || []
        this.leaguePeriod = res.period || ''
        this.leagueUpdatedAt = res.updated_at || ''
        this.leaguePeriods = res.available_periods || []
      } catch (e) {
        this.leagueError = e.message || '联赛队伍加载失败'
        if (this.leagueClans.length) uni.showToast({ title: this.leagueError, icon: 'none' })
      } finally { this.leagueLoading = false }
    },
    onLeaguePeriodChange(event) {
      const selected = this.leaguePeriods[Number(event.detail.value)]
      if (!selected || selected.period === this.leaguePeriod) return
      this.leaguePeriod = selected.period
      this.leagueClans = []
      this.fetchCwlLive(selected.period)
    },
    startTimers() {
      this.stopTimers()
      this.nowMs = Date.now()
      this.clockTimer = setInterval(() => { this.nowMs = Date.now() }, 1000)
      this.refreshTimer = setInterval(() => {
        if (this.activeTopTab === 'league') {
          if (this.isCurrentLeaguePeriod) this.fetchCwlLive(this.leaguePeriod)
        } else if (this.activeTopTab === 'clan-war' && this.warView === 'current') this.fetchCurrentWars()
      }, CACHE_REFRESH_INTERVAL_MS)
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
      this.draftStatus = this.warView === 'history' ? this.historyResultFilter : this.statusFilter
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
      if (this.warView === 'history') {
        this.draftStatus = 'all'
        return
      }
      this.draftCategories = this.activeCategories.map(item => item.key)
      this.draftClans = this.activeClanOptions.map(item => item.clan_tag)
      this.draftStatus = 'all'
    },
    resetFilters() {
      if (this.warView === 'history') {
        this.historyResultFilter = 'all'
        return
      }
      this.selectedCategories = this.activeCategories.map(item => item.key)
      this.selectedClans = this.activeClanOptions.map(item => item.clan_tag)
      this.statusFilter = 'all'
    },
    applyFilters() {
      if (this.warView === 'history') this.historyResultFilter = this.draftStatus
      else {
        this.selectedCategories = this.draftCategories.slice()
        this.selectedClans = this.draftClans.slice()
        this.statusFilter = this.draftStatus
      }
      this.filterVisible = false
    },
    openDetail(clan) {
      if (['not_in_war', 'sync_pending', 'error'].indexOf(clan.status) >= 0) return
      uni.navigateTo({ url: `/pages/war/current-detail?clan_tag=${encodeURIComponent(clan.clan_tag)}` })
    },
    openHistoryDetail(war) {
      uni.navigateTo({ url: `/pages/war/current-detail?clan_tag=${encodeURIComponent(war.clan_tag)}&war_key=${encodeURIComponent(war.war_key)}` })
    },
    openLeagueDetail(clan) {
      if (!clan.clan_tag) return
      rememberReturnTopTab('league')
      uni.navigateTo({ url: `/pages/war/cwl-detail?clan_tag=${encodeURIComponent(clan.clan_tag)}&period=${encodeURIComponent(this.leaguePeriod)}&view=war-day` })
    },
    categoryLabel(key) {
      const item = this.historyCategories.find(category => category.key === key) || this.categories.find(category => category.key === key)
      return item ? item.label : key
    },
    leagueCategoryLabel(key) { return key === 'shell' ? '壳子' : '实战' },
    leagueStatusLabel(status) {
      return ({ active: '战斗日', preparation: '准备日', ended: '已结束', waiting: '待开启', error: '同步失败' })[status] || status
    },
    statusLabel(status) {
      return ({ in_war: '战斗日', preparation: '准备日', war_ended: '已结束', not_in_war: '无战争', cwl: '联赛中', sync_pending: '待同步', error: '同步失败' })[status] || status
    },
    resultLabel(result) {
      return ({ leading: '领先', losing: '落后', tied: '平', victory: '胜利', defeat: '失败', pending: '尚未开战' })[result] || '-'
    },
    leagueResultSummary(clan) {
      if (!clan) return '-'
      return `${clan.wins || 0}胜 ${clan.losses || 0}负${clan.ties ? ' ' + clan.ties + '平' : ''}`
    },
    warPhaseResultClass(status) {
      if (status === 'in_war') return 'result-active'
      if (status === 'preparation') return 'result-preparation'
      return 'result-ended'
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
    formatFullDate(value) {
      const date = this.parseTime(value)
      if (!date) return '-'
      const month = String(date.getMonth() + 1).padStart(2, '0')
      const day = String(date.getDate()).padStart(2, '0')
      return `${date.getFullYear()}-${month}-${day}`
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
.check-in-host { width: 100%; height: 0; min-height: 0; flex: 1; display: block; }
.war-pane, .content-area { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.war-toolbar { flex-shrink: 0; height: 72rpx; padding: 0 24rpx; display: flex; align-items: center; justify-content: space-between; background: #141428; border-bottom: 1rpx solid #2a2a4a; }
.toolbar-title-wrap, .toolbar-actions { display: flex; align-items: center; }.toolbar-title { color: #d8dce8; font-size: 28rpx; font-weight: 600; }.toolbar-count { margin-left: 12rpx; color: #66708a; font-size: 22rpx; }.filter-trigger { padding: 12rpx; color: #aab4c8; font-size: 25rpx; }
.state-box { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; }.state-text { color: #8890a0; font-size: 28rpx; }.error-text { margin: 0 32rpx 20rpx; color: #e17055; font-size: 26rpx; text-align: center; }.retry-btn { color: #5fa8ff; font-size: 26rpx; }
.war-list-scroll { flex: 1; height: 0; }.war-list-inner { padding: 18rpx 24rpx 0; }.update-time { margin-bottom: 14rpx; color: #596178; font-size: 22rpx; text-align: center; }.filter-summary { display: flex; align-items: center; justify-content: center; margin-bottom: 16rpx; padding: 12rpx; color: #9aa0b0; font-size: 22rpx; background: #15152a; border-radius: 8rpx; }.clear-filter { margin-left: 18rpx; color: #5fa8ff; }.empty-list { padding: 100rpx 0; color: #66708a; font-size: 26rpx; text-align: center; }
.war-card { margin-bottom: 20rpx; overflow: hidden; border: 1rpx solid #2a2a4a; border-radius: 14rpx; background: #18182d; box-sizing: border-box; }.card-header { min-height: 68rpx; padding: 14rpx 18rpx; display: flex; align-items: center; box-sizing: border-box; border-bottom: 1rpx solid #282844; }.category-badge { flex-shrink: 0; margin-right: 10rpx; padding: 3rpx 9rpx; border-radius: 6rpx; color: #9fc9ff; background: rgba(74,144,217,.18); font-size: 20rpx; }.category-farm { color: #7fd8a8; background: rgba(0,184,148,.15); }.category-flat { color: #d9b8ff; background: rgba(162,111,212,.16); }.clan-name { min-width: 0; overflow: hidden; color: #f0f0f5; font-size: 28rpx; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }.clan-tag { flex-shrink: 0; margin-left: 8rpx; color: #66708a; font-size: 20rpx; }.status-badge { flex-shrink: 0; margin-left: auto; padding-left: 12rpx; color: #8890a0; font-size: 22rpx; }.status-in_war { color: #ff7675; }.status-preparation { color: #fdcb6e; }.status-war_ended { color: #8890a0; }.status-error { color: #e17055; }
.simple-state { padding: 28rpx 20rpx; color: #7d8498; font-size: 25rpx; text-align: center; }.error-state { color: #e17055; }.cwl-state { color: #74b9ff; }.sync-warning { margin-bottom: 16rpx; padding: 12rpx 14rpx; border-radius: 8rpx; color: #fdcb6e; background: rgba(253,203,110,.1); font-size: 21rpx; line-height: 1.5; }
.war-summary { padding: 18rpx; }.opponent-row { display: flex; align-items: center; }.opponent-label { margin-right: 10rpx; color: #66708a; font-size: 22rpx; }.opponent-name { max-width: 280rpx; overflow: hidden; color: #d8dce8; font-size: 26rpx; text-overflow: ellipsis; white-space: nowrap; }.opponent-tag { margin-left: 8rpx; color: #596178; font-size: 20rpx; }.result-label { margin-left: auto; font-size: 23rpx; font-weight: 600; }.result-active { color: #ff7675; }.result-preparation { color: #fdcb6e; }.result-ended { color: #8890a0; font-weight: 400; }
.score-row { margin-top: 18rpx; display: flex; align-items: center; }.side-score { flex: 1; display: flex; align-items: center; color: #9aa0b0; font-size: 22rpx; }.side-score text { margin-right: 10rpx; }.opponent-score { justify-content: flex-end; }.opponent-score text { margin-right: 0; margin-left: 10rpx; }.side-name { color: #66708a; }.stars { color: #f0f0f5; font-weight: 600; }.versus { margin: 0 12rpx; color: #4a90d9; font-size: 22rpx; font-weight: 600; }
.attack-count { white-space: nowrap; }
.card-footer { margin-top: 18rpx; padding-top: 14rpx; display: flex; align-items: center; border-top: 1rpx solid #252540; }.countdown { color: #747c91; font-size: 22rpx; }.card-actions { margin-left: auto; display: flex; align-items: center; }.detail-link { padding: 8rpx 12rpx; color: #5fa8ff; font-size: 23rpx; }.share-btn { margin: 0 0 0 8rpx; padding: 8rpx 12rpx; border: 0; border-radius: 6rpx; color: #aab4c8; background: #252540; font-size: 23rpx; line-height: 1.4; }.share-btn::after { border: 0; }.bottom-space { height: 120rpx; }
.filter-mask { position: fixed; z-index: 1000; top: 0; right: 0; bottom: 0; left: 0; display: flex; align-items: flex-end; background: rgba(0,0,0,.6); }.filter-panel { width: 100%; max-height: 82vh; padding: 26rpx 30rpx 34rpx; box-sizing: border-box; border-radius: 24rpx 24rpx 0 0; background: #1a1a2e; }.filter-title { margin-bottom: 20rpx; color: #fff; font-size: 31rpx; font-weight: 600; text-align: center; }.filter-group-title { display: block; margin: 16rpx 0 10rpx; color: #8890a0; font-size: 23rpx; }.filter-options { display: flex; flex-wrap: wrap; }.filter-option { min-height: 62rpx; margin-right: 26rpx; display: flex; align-items: center; color: #d0d0dc; font-size: 25rpx; }.filter-check { width: 34rpx; height: 34rpx; margin-right: 9rpx; display: flex; align-items: center; justify-content: center; box-sizing: border-box; border: 2rpx solid #66708a; border-radius: 5rpx; color: #fff; }.filter-check.checked { border-color: #4a90d9; background: #4a90d9; }.status-filter-options { display: flex; flex-wrap: wrap; }.status-filter-option { margin: 0 12rpx 12rpx 0; padding: 10rpx 17rpx; border-radius: 8rpx; color: #9097aa; background: #252540; font-size: 23rpx; }.status-filter-option.active { color: #fff; background: #4a90d9; }.clan-options { max-height: 320rpx; border-top: 1rpx solid #2a2a4a; border-bottom: 1rpx solid #2a2a4a; }.clan-option { margin-right: 0; padding: 0 6rpx; border-bottom: 1rpx solid #252540; }.filter-actions { margin-top: 22rpx; display: flex; justify-content: flex-end; }.filter-action { min-width: 110rpx; margin-left: 14rpx; padding: 14rpx 20rpx; border-radius: 7rpx; text-align: center; font-size: 25rpx; }.reset-action { color: #74b9ff; }.cancel-action { color: #aab4c8; background: #252540; }.confirm-action { color: #fff; background: #4a90d9; }
.period-label, .period-selector { color: #74b9ff; font-size: 23rpx; }.period-selector { padding: 14rpx 8rpx; }.war-view-selector { display: block; max-width: 410rpx; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.history-scope { margin-bottom: 16rpx; padding: 16rpx 18rpx; border: 1rpx solid #2a2a4a; border-radius: 10rpx; background: #15152a; }.history-scope-name, .history-scope-meta { display: block; }.history-scope-name { overflow: hidden; color: #d8dce8; font-size: 26rpx; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }.history-scope-meta { margin-top: 6rpx; color: #747c91; font-size: 21rpx; }.league-card { min-height: 150rpx; }.league-management-row { padding: 12rpx 18rpx 0; display: flex; align-items: baseline; overflow: hidden; color: #8d95a8; font-size: 21rpx; line-height: 1.6; white-space: nowrap; }.league-leader { flex-shrink: 0; margin-right: 24rpx; color: #aab4c8; }.league-managers { min-width: 0; overflow: hidden; color: #8d95a8; text-overflow: ellipsis; white-space: nowrap; }.league-status-active { color: #ff7675; }.league-status-preparation { color: #fdcb6e; }.league-status-ended { color: #74b9ff; }.league-status-error { color: #e17055; }.league-alias, .waiting-hint, .state-detail-link { display: block; }.league-alias { color: #aab4c8; }.waiting-hint { margin-top: 8rpx; color: #66708a; font-size: 22rpx; }.state-detail-link { margin-top: 10rpx; }.league-summary { padding: 18rpx; }.league-primary-row { display: flex; align-items: center; color: #d8dce8; font-size: 25rpx; }.league-rank { margin-left: auto; color: #fdcb6e; }.league-metrics { margin-top: 18rpx; display: flex; align-items: center; justify-content: space-between; color: #9aa0b0; font-size: 23rpx; }
.history-card .result-label { margin-left: auto; }.history-opponent-row { padding: 15rpx 18rpx 0; }.history-score-row { padding: 14rpx 18rpx 4rpx; }.history-score-row .side-score { justify-content: space-around; }
</style>
