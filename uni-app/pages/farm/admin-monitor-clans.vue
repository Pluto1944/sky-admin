<template>
  <view class="list-page">
    <view class="toolbar">
      <view class="search-box">
        <text class="search-icon">⌕</text>
        <input
          v-model="searchQuery"
          class="search-input"
          placeholder="搜索部落名称、标签或所属账号"
          placeholder-style="color:#59637a"
          confirm-type="search"
          @input="scheduleSearch"
          @confirm="applySearch"
        />
        <text v-if="searchQuery" class="clear" @tap="clearSearch">×</text>
      </view>
      <scroll-view class="filter-scroll" scroll-x :show-scrollbar="false">
        <view class="filter-row">
          <text
            v-for="item in filters"
            :key="item.value"
            class="filter-chip"
            :class="{ active: statusFilter === item.value }"
            @tap="selectFilter(item.value)"
          >{{ item.label }}</text>
        </view>
      </scroll-view>
      <view class="select-row">
        <picker :range="accountOptions" range-key="label" :value="accountIndex" @change="changeAccount">
          <view class="select-field">{{ accountOptions[accountIndex].label }}<text>⌄</text></view>
        </picker>
        <picker :range="sortOptions" range-key="label" :value="sortIndex" @change="changeSort">
          <view class="select-field">{{ sortOptions[sortIndex].label }}<text>⌄</text></view>
        </picker>
      </view>
    </view>

    <view class="result-head">
      <text>{{ filterLabel }}</text>
      <text>{{ total }} 个部落</text>
    </view>

    <view v-if="loading && !clans.length" class="page-state">正在加载...</view>
    <view v-else-if="error && !clans.length" class="page-state">
      <text class="state-error">{{ error }}</text>
      <button class="small-button" @tap="load(true)">重新加载</button>
    </view>
    <view v-else-if="!clans.length" class="empty-card">当前筛选条件下没有部落</view>
    <view v-else>
      <view v-for="clan in clans" :key="clan.clan_id" class="clan-row" @tap="openClanDetail(clan)">
        <view class="clan-head">
          <view class="clan-copy">
            <text class="clan-name">{{ clan.clan_name }}</text>
            <text class="clan-meta">{{ clan.clan_tag }} · {{ clan.account_name }}</text>
          </view>
          <text class="detail-arrow">›</text>
        </view>
        <view class="status-grid">
          <view>
            <text class="status-label">战争</text>
            <text class="status-value" :class="warClass(clan.war_status)">{{ warLabel(clan.war_status) }}</text>
          </view>
          <view>
            <text class="status-label">登记</text>
            <text class="status-value">{{ registrationLabel(clan.registration_status) }}</text>
          </view>
          <view>
            <text class="status-label">匹配</text>
            <text class="status-value" :class="matchClass(clan)">{{ matchLabel(clan) }}</text>
          </view>
          <view>
            <text class="status-label">胜负</text>
            <text class="status-value" :class="resultClass(clan.result)">{{ resultLabel(clan.result) }}</text>
          </view>
        </view>
        <view v-if="clan.opponent_name || clan.opponent_tag" class="opponent-row">
          <text>对手部落</text>
          <text>{{ clan.opponent_name || '未知名称' }} {{ clan.opponent_tag || '' }}</text>
        </view>
        <view class="updated-row">
          <text v-if="clan.war_error" class="error-copy">{{ clan.war_error }}</text>
          <text v-else>战争数据更新 {{ formatUpdated(clan.war_checked_at) }}</text>
        </view>
      </view>
      <view class="load-more" @tap="loadMore">{{ hasMore ? (loadingMore ? '正在加载...' : '加载更多') : '已经到底了' }}</view>
    </view>
    <view class="bottom-space"></view>
  </view>
</template>

<script>
import { getFarmMonitorClans, getFarmMonitorOverview } from '@/utils/api.js'

export default {
  data() {
    return {
      loading: true,
      loadingMore: false,
      error: '',
      clans: [],
      total: 0,
      hasMore: false,
      page: 1,
      pageSize: 30,
      statusFilter: 'attention',
      accountId: null,
      accountIndex: 0,
      searchQuery: '',
      searchTimer: null,
      sortIndex: 0,
      initialized: false,
      filters: [
        { value: 'attention', label: '待处理' },
        { value: 'all', label: '全部' },
        { value: 'war_detected', label: '已检测战争' },
        { value: 'war_not_detected', label: '暂未检测到' },
        { value: 'war_unchecked', label: '未检查' },
        { value: 'war_error', label: '战争异常' },
        { value: 'unregistered', label: '未登记' },
        { value: 'registered', label: '已登记' },
        { value: 'war_mismatch', label: '时间不匹配' },
        { value: 'fetch_failed', label: '登记获取失败' },
        { value: 'match_success', label: '匹配成功' },
        { value: 'match_failed', label: '匹配失败' },
        { value: 'win', label: '胜' },
        { value: 'loss', label: '负' },
        { value: 'revoked', label: '已撤销' }
      ],
      accountOptions: [{ value: null, label: '全部账号' }],
      sortOptions: [
        { value: 'attention', label: '异常优先' },
        { value: 'account', label: '按账号排序' },
        { value: 'updated', label: '最近更新' }
      ]
    }
  },
  computed: {
    filterLabel() {
      const item = this.filters.find(item => item.value === this.statusFilter)
      return item ? item.label : '部落监控'
    }
  },
  onLoad(options) {
    if (options && this.filters.some(item => item.value === options.status_filter)) {
      this.statusFilter = options.status_filter
    }
    this.accountId = options && options.account_id ? Number(options.account_id) : null
  },
  onShow() {
    if (!this.initialized) this.initialize()
  },
  onUnload() { if (this.searchTimer) clearTimeout(this.searchTimer) },
  onReachBottom() { this.loadMore() },
  onPullDownRefresh() { this.load(true).finally(() => uni.stopPullDownRefresh()) },
  methods: {
    async initialize() {
      try {
        const overview = await getFarmMonitorOverview()
        this.accountOptions = [
          { value: null, label: '全部账号' },
          ...(overview.accounts || []).map(item => ({ value: item.account_id, label: item.account_name }))
        ]
        const index = this.accountOptions.findIndex(item => Number(item.value) === Number(this.accountId))
        this.accountIndex = index >= 0 ? index : 0
        await this.load(true)
        this.initialized = true
      } catch (e) {
        this.error = e.message || '加载监控列表失败'
        this.loading = false
      }
    },
    async load(reset = false) {
      const requestedPage = this.page
      if (reset) {
        this.page = 1
        this.loading = true
      }
      try {
        const result = await getFarmMonitorClans({
          statusFilter: this.statusFilter,
          accountId: this.accountId,
          search: this.searchQuery.trim(),
          sort: this.sortOptions[this.sortIndex].value,
          page: this.page,
          pageSize: this.pageSize
        })
        this.clans = reset ? (result.clans || []) : this.clans.concat(result.clans || [])
        this.total = result.total || 0
        this.hasMore = Boolean(result.has_more)
        this.error = ''
      } catch (e) {
        this.error = e.message || '加载监控列表失败'
        if (!reset) this.page = Math.max(1, requestedPage - 1)
        if (!reset) uni.showToast({ title: this.error, icon: 'none' })
      } finally {
        this.loading = false
        this.loadingMore = false
      }
    },
    loadMore() {
      if (!this.hasMore || this.loadingMore) return
      this.loadingMore = true
      this.page += 1
      this.load(false)
    },
    selectFilter(value) {
      if (this.statusFilter === value) return
      this.statusFilter = value
      this.load(true)
    },
    changeAccount(event) {
      this.accountIndex = Number(event.detail.value)
      this.accountId = this.accountOptions[this.accountIndex].value
      this.load(true)
    },
    changeSort(event) {
      this.sortIndex = Number(event.detail.value)
      this.load(true)
    },
    scheduleSearch() {
      if (this.searchTimer) clearTimeout(this.searchTimer)
      this.searchTimer = setTimeout(() => this.load(true), 350)
    },
    applySearch() {
      if (this.searchTimer) clearTimeout(this.searchTimer)
      this.load(true)
    },
    clearSearch() {
      this.searchQuery = ''
      this.load(true)
    },
    openClanDetail(clan) {
      uni.navigateTo({ url: `/pages/farm/admin-clan-detail?clan_tag=${encodeURIComponent(clan.clan_tag)}` })
    },
    warLabel(status) {
      return ({ unchecked: '未检查', not_in_war: '暂未检测到', preparation: '准备日', in_war: '战斗日', war_ended: '已结束', cwl: '当前为联赛', error: '检查失败' })[status] || status
    },
    warClass(status) {
      if (['preparation', 'in_war', 'war_ended'].includes(status)) return 'success'
      if (status === 'error' || status === 'cwl') return 'danger'
      return 'warning'
    },
    registrationLabel(status) {
      return ({ not_registered: '未登记', registering: '登记中', not_in_war: '等待重试', war_mismatch: '时间不匹配', fetch_failed: '获取失败', internal_matched: '已登记', match_failed: '已登记', revoked: '已撤销' })[status] || status
    },
    matchLabel(clan) {
      if (clan.registration_status === 'internal_matched') return '内部成功'
      if (clan.registration_status === 'match_failed') return '匹配失败'
      if (clan.registration_status === 'revoked') return '已撤销'
      return '待匹配'
    },
    matchClass(clan) {
      if (clan.registration_status === 'internal_matched') return 'success'
      if (clan.registration_status === 'match_failed') return 'warning'
      if (clan.registration_status === 'revoked') return 'danger'
      return ''
    },
    resultLabel(result) { return ({ win: '胜', loss: '负', match_failed: '匹配失败' })[result] || '待定' },
    resultClass(result) { return ({ win: 'success', loss: 'danger', match_failed: 'warning' })[result] || '' },
    formatUpdated(value) {
      if (!value) return '尚未检查'
      const date = new Date(value)
      const pad = number => String(number).padStart(2, '0')
      return `${date.getMonth() + 1}月${date.getDate()}日 ${pad(date.getHours())}:${pad(date.getMinutes())}`
    }
  }
}
</script>

<style>
.list-page { min-height: 100vh; padding: 24rpx; box-sizing: border-box; background: #0f0f23; color: #edf1f8; }.toolbar { position: sticky; z-index: 2; top: 0; padding-bottom: 18rpx; background: #0f0f23; }.search-box { display: flex; height: 76rpx; align-items: center; padding: 0 20rpx; border: 1rpx solid #292f4e; border-radius: 14rpx; background: #191a31; }.search-icon { margin-right: 12rpx; color: #748097; font-size: 27rpx; }.search-input { min-width: 0; flex: 1; color: #e7ebf4; font-size: 23rpx; }.clear { padding: 12rpx; color: #6d7890; font-size: 30rpx; }.filter-scroll { width: 100%; margin-top: 16rpx; white-space: nowrap; }.filter-row { display: inline-flex; padding-right: 20rpx; }.filter-chip { margin-right: 12rpx; padding: 11rpx 20rpx; border: 1rpx solid #2a3150; border-radius: 25rpx; background: #191a31; color: #7f8aa1; font-size: 21rpx; }.filter-chip.active { border-color: #396a9b; background: #22314d; color: #83b8ea; }.select-row { display: flex; gap: 14rpx; margin-top: 16rpx; }.select-row picker { min-width: 0; flex: 1; }.select-field { display: flex; height: 64rpx; align-items: center; justify-content: space-between; padding: 0 18rpx; border: 1rpx solid #292f4e; border-radius: 12rpx; background: #191a31; color: #9aa5b8; font-size: 21rpx; }.select-field text { color: #657087; }.result-head { display: flex; justify-content: space-between; padding: 8rpx 4rpx 16rpx; color: #818ca2; font-size: 22rpx; }.page-state { display: flex; min-height: 55vh; flex-direction: column; align-items: center; justify-content: center; gap: 22rpx; color: #79849a; font-size: 24rpx; }.state-error { color: #cf7c80; }.small-button { padding: 0 30rpx; border: 1rpx solid #31537d; border-radius: 12rpx; background: transparent; color: #77afe5; font-size: 23rpx; }.empty-card { padding: 80rpx 20rpx; border: 1rpx dashed #2b3150; border-radius: 16rpx; color: #687389; font-size: 23rpx; text-align: center; }
.clan-row { margin-bottom: 16rpx; overflow: hidden; border: 1rpx solid #292f4e; border-radius: 16rpx; background: #191a31; }.clan-head { display: flex; align-items: center; justify-content: space-between; padding: 21rpx 23rpx; }.clan-copy { min-width: 0; }.clan-name, .clan-meta { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.clan-name { font-size: 26rpx; font-weight: 650; }.clan-meta { margin-top: 6rpx; color: #707b92; font-size: 19rpx; }.detail-arrow { color: #616c84; font-size: 34rpx; }.status-grid { display: flex; border-top: 1rpx solid #282e4b; border-bottom: 1rpx solid #282e4b; }.status-grid view { min-width: 0; flex: 1; padding: 16rpx 6rpx; text-align: center; }.status-grid view + view { border-left: 1rpx solid #282e4b; }.status-label, .status-value { display: block; }.status-label { color: #69758c; font-size: 17rpx; }.status-value { margin-top: 6rpx; overflow: hidden; color: #a1acbd; font-size: 19rpx; text-overflow: ellipsis; white-space: nowrap; }.status-value.success { color: #70c293; }.status-value.warning { color: #d0a45f; }.status-value.danger { color: #c97d82; }.opponent-row { display: flex; align-items: center; justify-content: space-between; padding: 17rpx 23rpx 5rpx; color: #77839a; font-size: 19rpx; }.opponent-row text:last-child { max-width: 70%; overflow: hidden; color: #b6becd; text-overflow: ellipsis; white-space: nowrap; }.updated-row { padding: 12rpx 23rpx 17rpx; color: #616d84; font-size: 18rpx; text-align: right; }.error-copy { color: #b9797d; }.load-more { padding: 28rpx; color: #6c778e; font-size: 21rpx; text-align: center; }.bottom-space { height: 40rpx; }
</style>
