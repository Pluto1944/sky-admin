<template>
  <view class="farm-page">
    <view v-if="loading" class="page-state">正在加载...</view>
    <view v-else-if="error" class="page-state">
      <text class="state-error">{{ error }}</text>
      <button class="small-button" @tap="load">重新加载</button>
    </view>
    <view v-else>
      <view class="section-head first-head">
        <view>
          <text class="section-title">全部互刷部落</text>
          <text class="section-desc">管理部落资料、账号归属和启用状态</text>
        </view>
        <text class="section-count">{{ clans.length }} 个</text>
      </view>

      <view class="form-card">
        <text class="form-title">添加互刷部落</text>
        <input v-model="newClan.clan_tag" class="input" placeholder="部落标签，例如 #ABC123" maxlength="16" @input="onClanTagInput" />
        <view class="picker-field" @tap="openAccountSelector('new')">{{ selectedNewClanAccountName || '选择归属账号' }}<text>⌄</text></view>
        <button v-if="!clanSync || clanSync.status !== 'ready'" class="primary-button" :loading="syncing" :disabled="saving || syncing" @tap="requestClanSync">{{ clanSync && clanSync.status === 'failed' ? '重新查询' : '添加部落' }}</button>
        <view v-if="clanSync" class="sync-status" :class="clanSync.status">
          <text class="sync-title">{{ syncStatusTitle }}</text>
          <text v-if="clanSync.clan_name" class="sync-detail">{{ clanSync.clan_name }} · {{ clanSync.clan_tag }}</text>
          <text v-else-if="clanSync.error" class="sync-detail">{{ clanSync.error }}</text>
          <text v-else class="sync-detail">正在读取 COC 部落名称和标签</text>
        </view>
        <button v-if="clanSync && clanSync.status === 'ready'" class="primary-button" :loading="saving" :disabled="saving" @tap="createClan">确认添加到{{ clanSync.account_name }}</button>
        <text class="form-tip">系统会自动读取 COC 部落名称并检查标签，确认无误后添加到所选账号。</text>
      </view>

      <view class="sort-bar">
        <view>
          <text class="sort-title">最近启用时间</text>
          <text class="sort-desc">停用后重新启用会刷新时间</text>
        </view>
        <text class="sort-toggle" @tap="sortDescending = !sortDescending">{{ sortDescending ? '最新在前 ↓' : '最早在前 ↑' }}</text>
      </view>

      <view class="search-box">
        <text class="search-icon">⌕</text>
        <input v-model="searchQuery" class="search-input" placeholder="搜索部落名称、标签或所属账号" placeholder-style="color:#59637a" />
        <text v-if="searchQuery" class="search-clear" @tap="searchQuery = ''">清除</text>
      </view>
      <text v-if="searchQuery" class="result-count">找到 {{ filteredClans.length }} 个部落</text>

      <view v-if="!filteredClans.length" class="empty-card">{{ searchQuery ? '没有匹配的互刷部落' : '暂未添加互刷部落' }}</view>
      <view v-for="clan in filteredClans" :key="clan.id" class="data-card">
        <view class="card-main" @tap="openClanDetail(clan)">
          <view class="card-copy">
            <text class="card-title">{{ clan.clan_name }}</text>
            <text class="card-meta">{{ clan.clan_tag }} · 当前积分 {{ clan.score }}</text>
            <text class="enabled-time">最近启用 {{ formatEnabledAt(clan.enabled_at) }}</text>
          </view>
          <view class="card-side">
            <text class="status-badge" :class="{ disabled: clan.status !== 'active' }">{{ clan.status === 'active' ? '启用' : '停用' }}</text>
            <text class="detail-arrow">›</text>
          </view>
        </view>
        <view class="card-actions">
          <view class="action-field" @tap="openAccountSelector('transfer', clan)">归属：{{ accountName(clan.account_id) }}<text>⌄</text></view>
          <text class="action-link" @tap="toggleClan(clan)">{{ clan.status === 'active' ? '停用' : '启用' }}</text>
        </view>
      </view>
    </view>

    <view v-if="accountSelectorOpen" class="selector-mask" @tap="closeAccountSelector">
      <view class="selector-panel" @tap.stop>
        <view class="selector-head">
          <text class="selector-title">选择部落归属账号</text>
          <text class="selector-close" @tap="closeAccountSelector">关闭</text>
        </view>
        <view class="selector-search">
          <text class="search-icon">⌕</text>
          <input v-model="accountSearchQuery" class="search-input" placeholder="搜索联盟名称或登录邮箱" placeholder-style="color:#59637a" :focus="accountSelectorOpen" />
          <text v-if="accountSearchQuery" class="search-clear" @tap="accountSearchQuery = ''">清除</text>
        </view>
        <scroll-view class="selector-list" scroll-y>
          <view v-if="!filteredActiveAccounts.length" class="selector-empty">没有匹配的启用账号</view>
          <view v-for="account in filteredActiveAccounts" :key="account.id" class="selector-item" @tap="selectAccount(account)">
            <view class="selector-copy">
              <text class="selector-name">{{ account.display_name }}</text>
              <text class="selector-email">{{ account.username }}</text>
            </view>
            <text v-if="isSelectedAccount(account)" class="selector-selected">已选择</text>
          </view>
        </scroll-view>
      </view>
    </view>
    <view class="bottom-space"></view>
  </view>
</template>

<script>
import {
  createFarmClan,
  getFarmAdminAccounts,
  getFarmAdminClans,
  getFarmClanSyncStatus,
  getFarmMe,
  requestFarmClanSync,
  transferFarmClan,
  updateFarmClan
} from '@/utils/api.js'

export default {
  data() {
    return {
      loading: true,
      hasLoaded: false,
      saving: false,
      error: '',
      accounts: [],
      clans: [],
      searchQuery: '',
      sortDescending: true,
      newClan: { clan_tag: '', account_id: null },
      accountSelectorOpen: false,
      accountSearchQuery: '',
      accountSelectorMode: 'new',
      accountSelectorClan: null,
      clanSync: null,
      syncing: false,
      syncTimer: null
    }
  },
  computed: {
    activeAccounts() { return this.accounts.filter(item => item.status === 'active') },
    filteredActiveAccounts() {
      const query = this.accountSearchQuery.trim().toLowerCase()
      if (!query) return this.activeAccounts
      return this.activeAccounts.filter(account => [account.display_name, account.username]
        .some(value => String(value || '').toLowerCase().includes(query)))
    },
    filteredClans() {
      const query = this.searchQuery.trim().toLowerCase()
      const filtered = query ? this.clans.filter(clan => {
        const account = this.accounts.find(item => Number(item.id) === Number(clan.account_id)) || {}
        return [
          clan.clan_name,
          clan.clan_tag,
          account.display_name,
          account.username,
          clan.status === 'active' ? '启用' : '停用'
        ].some(value => String(value || '').toLowerCase().includes(query))
      }) : this.clans
      const direction = this.sortDescending ? -1 : 1
      return filtered.slice().sort((left, right) => {
        const leftTime = Date.parse(left.enabled_at || left.created_at || '') || 0
        const rightTime = Date.parse(right.enabled_at || right.created_at || '') || 0
        if (leftTime !== rightTime) return (leftTime - rightTime) * direction
        return (Number(left.id) - Number(right.id)) * direction
      })
    },
    newClanAccountIndex() {
      return Math.max(0, this.activeAccounts.findIndex(item => Number(item.id) === Number(this.newClan.account_id)))
    },
    selectedNewClanAccountName() {
      const item = this.activeAccounts[this.newClanAccountIndex]
      return item ? item.display_name : ''
    },
    syncStatusTitle() {
      return ({ syncing: '正在验证官方资料', ready: '官方资料验证成功', failed: '官方资料验证失败' })[(this.clanSync || {}).status] || '等待验证'
    }
  },
  onShow() { this.load() },
  onHide() { this.stopSyncPolling() },
  onUnload() { this.stopSyncPolling() },
  methods: {
    formatEnabledAt(value) {
      if (!value) return '-'
      const date = new Date(value)
      const pad = number => String(number).padStart(2, '0')
      return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
    },
    openClanDetail(clan) {
      uni.navigateTo({ url: `/pages/farm/admin-clan-detail?clan_tag=${encodeURIComponent(clan.clan_tag)}` })
    },
    accountName(id) {
      const item = this.accounts.find(account => Number(account.id) === Number(id))
      return item ? item.display_name : '未知账号'
    },
    openAccountSelector(mode, clan = null) {
      this.accountSelectorMode = mode
      this.accountSelectorClan = clan
      this.accountSearchQuery = ''
      this.accountSelectorOpen = true
    },
    closeAccountSelector() {
      this.accountSelectorOpen = false
      this.accountSearchQuery = ''
      this.accountSelectorClan = null
    },
    isSelectedAccount(account) {
      const selectedId = this.accountSelectorMode === 'new'
        ? this.newClan.account_id
        : (this.accountSelectorClan || {}).account_id
      return Number(account.id) === Number(selectedId)
    },
    async selectAccount(account) {
      if (this.accountSelectorMode === 'new') {
        if (Number(account.id) !== Number(this.newClan.account_id)) {
          this.newClan.account_id = account.id
          this.clearSync()
        }
        this.closeAccountSelector()
        return
      }
      const clan = this.accountSelectorClan
      this.closeAccountSelector()
      if (!clan || Number(account.id) === Number(clan.account_id)) return
      await this.runUpdate(() => transferFarmClan(clan.clan_tag, account.id))
    },
    async load() {
      const initialLoad = !this.hasLoaded
      if (initialLoad) {
        this.loading = true
        this.error = ''
      }
      try {
        const me = await getFarmMe()
        if (!['creator', 'admin'].includes(me.role)) throw new Error('当前账号没有部落管理权限')
        const result = await Promise.all([getFarmAdminAccounts(), getFarmAdminClans()])
        this.accounts = result[0].accounts || []
        this.clans = result[1].clans || []
        if (!this.newClan.account_id && this.activeAccounts.length) this.newClan.account_id = this.activeAccounts[0].id
        this.error = ''
        this.hasLoaded = true
      } catch (e) {
        if (initialLoad) this.error = e.message || '加载失败'
        else uni.showToast({ title: e.message || '刷新失败', icon: 'none' })
      } finally {
        if (initialLoad) this.loading = false
      }
    },
    async requestClanSync() {
      if (this.saving || this.syncing) return
      const clanTag = this.newClan.clan_tag.trim()
      const account = this.activeAccounts[this.newClanAccountIndex]
      if (!clanTag || !account) {
        uni.showToast({ title: '请填写标签并选择归属账号', icon: 'none' })
        return
      }
      this.syncing = true
      try {
        const result = await requestFarmClanSync({ clan_tag: clanTag, account_id: account.id })
        this.clanSync = result.sync
        if (this.clanSync.status === 'syncing') this.scheduleSyncPoll()
      } catch (e) {
        this.clanSync = { status: 'failed', error: e.message || '无法建立同步任务' }
      } finally { this.syncing = false }
    },
    async pollClanSync() {
      if (!this.clanSync || this.clanSync.status !== 'syncing') return
      const account = this.activeAccounts[this.newClanAccountIndex]
      if (!account) return
      try {
        const result = await getFarmClanSyncStatus(this.newClan.clan_tag.trim(), account.id)
        this.clanSync = result.sync
      } catch (e) {
        this.clanSync = { status: 'failed', error: e.message || '读取同步状态失败' }
      }
      if (this.clanSync.status === 'syncing') this.scheduleSyncPoll()
    },
    scheduleSyncPoll() {
      this.stopSyncPolling()
      this.syncTimer = setTimeout(() => this.pollClanSync(), 2000)
    },
    stopSyncPolling() {
      if (this.syncTimer) clearTimeout(this.syncTimer)
      this.syncTimer = null
    },
    clearSync() {
      this.stopSyncPolling()
      this.clanSync = null
    },
    onClanTagInput(event) {
      this.newClan.clan_tag = event.detail.value
      this.clearSync()
    },
    async createClan() {
      if (this.saving || !this.clanSync || this.clanSync.status !== 'ready') return
      const account = this.activeAccounts[this.newClanAccountIndex]
      if (!account) return
      this.saving = true
      try {
        await createFarmClan({ clan_tag: this.clanSync.clan_tag, account_id: account.id })
        this.newClan.clan_tag = ''
        this.clearSync()
        await this.load()
        uni.showToast({ title: '部落已绑定', icon: 'success' })
      } catch (e) {
        uni.showModal({ title: '绑定失败', content: e.message, showCancel: false })
      } finally { this.saving = false }
    },
    async toggleClan(clan) {
      await this.runUpdate(() => updateFarmClan(clan.clan_tag, { status: clan.status === 'active' ? 'disabled' : 'active' }))
    },
    async runUpdate(action) {
      if (this.saving) return
      this.saving = true
      try {
        await action()
        await this.load()
      } catch (e) {
        uni.showModal({ title: '操作失败', content: e.message, showCancel: false })
      } finally { this.saving = false }
    }
  }
}
</script>

<style>
.farm-page { min-height: 100vh; padding: 28rpx 26rpx; box-sizing: border-box; background: #0f0f23; color: #eef1f8; }.page-state { display: flex; min-height: 70vh; flex-direction: column; align-items: center; justify-content: center; gap: 24rpx; color: #7f899f; font-size: 26rpx; }.state-error { color: #d78383; }.small-button { padding: 0 32rpx; border: 1rpx solid #31537d; border-radius: 12rpx; background: transparent; color: #76aee6; font-size: 24rpx; }
.section-head { display: flex; align-items: flex-start; justify-content: space-between; padding: 30rpx 4rpx 18rpx; }.first-head { padding-top: 4rpx; }.section-title, .section-desc { display: block; }.section-title { font-size: 29rpx; font-weight: 650; }.section-desc { margin-top: 7rpx; color: #717c93; font-size: 21rpx; }.section-count { flex-shrink: 0; margin-left: 18rpx; color: #687188; font-size: 22rpx; }
.form-card, .data-card, .empty-card { margin-bottom: 20rpx; border: 1rpx solid #2a3152; border-radius: 18rpx; background: #191a31; }.form-card { padding: 26rpx; }.form-title { display: block; margin-bottom: 20rpx; font-size: 27rpx; font-weight: 600; }.input, .picker-field { height: 76rpx; margin-bottom: 16rpx; padding: 0 20rpx; border: 1rpx solid #30375b; border-radius: 12rpx; box-sizing: border-box; background: #121326; color: #e9edf6; font-size: 25rpx; }.picker-field { display: flex; align-items: center; justify-content: space-between; color: #aeb7ca; }
.primary-button { display: flex; height: 78rpx; align-items: center; justify-content: center; border-radius: 12rpx; background: #397fc0; color: #fff; font-size: 26rpx; font-weight: 600; }.primary-button::after { border: 0; }.form-tip { display: block; margin-top: 16rpx; color: #626c84; font-size: 21rpx; line-height: 1.55; }
.sync-status { margin: 16rpx 0; padding: 18rpx 20rpx; border: 1rpx solid #31405f; border-radius: 12rpx; background: #15182b; }.sync-status.ready { border-color: #345e4b; }.sync-status.failed { border-color: #623d49; }.sync-title, .sync-detail { display: block; }.sync-title { color: #8ebbe5; font-size: 23rpx; font-weight: 600; }.sync-status.ready .sync-title { color: #72c497; }.sync-status.failed .sync-title { color: #cf7e82; }.sync-detail { margin-top: 6rpx; color: #778298; font-size: 21rpx; line-height: 1.5; }
.sort-bar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16rpx; padding: 18rpx 20rpx; border: 1rpx solid #2a3152; border-radius: 14rpx; background: #17182e; }.sort-title, .sort-desc { display: block; }.sort-title { color: #dce1ed; font-size: 23rpx; font-weight: 600; }.sort-desc { margin-top: 5rpx; color: #69748b; font-size: 19rpx; }.sort-toggle { flex-shrink: 0; margin-left: 20rpx; padding: 12rpx 0 12rpx 20rpx; color: #78afe3; font-size: 22rpx; }
.search-box { display: flex; height: 82rpx; align-items: center; margin-bottom: 20rpx; padding: 0 18rpx; border: 1rpx solid #2a3152; border-radius: 14rpx; box-sizing: border-box; background: #15162b; }.search-icon { flex-shrink: 0; margin-right: 12rpx; color: #71809a; font-size: 30rpx; }.search-input { flex: 1; min-width: 0; color: #e6eaf3; font-size: 23rpx; }.search-clear { flex-shrink: 0; margin-left: 14rpx; color: #74a9df; font-size: 21rpx; }.result-count { display: block; margin: -8rpx 8rpx 18rpx; color: #657087; font-size: 20rpx; }
.empty-card { padding: 70rpx 20rpx; color: #677087; font-size: 25rpx; text-align: center; }.data-card { overflow: hidden; }.card-main { display: flex; align-items: center; justify-content: space-between; padding: 25rpx; }.card-copy { min-width: 0; }.card-title, .card-meta, .enabled-time { display: block; }.card-title { overflow: hidden; font-size: 28rpx; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }.card-meta { margin-top: 8rpx; color: #747e96; font-size: 21rpx; }.enabled-time { margin-top: 7rpx; color: #5f6b83; font-size: 19rpx; }.card-side { display: flex; flex-shrink: 0; align-items: center; margin-left: 18rpx; }.status-badge { flex-shrink: 0; padding: 6rpx 14rpx; border-radius: 18rpx; background: rgba(67,170,115,.14); color: #6fc595; font-size: 21rpx; }.status-badge.disabled { background: rgba(193,107,110,.12); color: #be777b; }.detail-arrow { margin-left: 14rpx; color: #606b83; font-size: 36rpx; }
.card-actions { display: flex; min-height: 70rpx; align-items: center; justify-content: space-between; padding: 0 25rpx; border-top: 1rpx solid #282e4d; color: #8190ab; font-size: 23rpx; }.action-field { display: flex; align-items: center; gap: 12rpx; padding: 16rpx 0; }.action-link { padding: 18rpx 0 18rpx 30rpx; color: #77aee3; }.bottom-space { height: 50rpx; }
.selector-mask { position: fixed; z-index: 100; top: 0; right: 0; bottom: 0; left: 0; display: flex; align-items: flex-end; background: rgba(4, 5, 15, .72); }.selector-panel { width: 100%; max-height: 72vh; padding: 28rpx 26rpx calc(28rpx + env(safe-area-inset-bottom)); border-radius: 26rpx 26rpx 0 0; box-sizing: border-box; background: #191a31; }.selector-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 22rpx; }.selector-title { font-size: 29rpx; font-weight: 650; }.selector-close { padding: 10rpx 0 10rpx 20rpx; color: #77aee3; font-size: 23rpx; }.selector-search { display: flex; height: 78rpx; align-items: center; padding: 0 18rpx; border: 1rpx solid #30375b; border-radius: 12rpx; box-sizing: border-box; background: #121326; }.selector-list { height: 520rpx; margin-top: 18rpx; }.selector-item { display: flex; min-height: 94rpx; align-items: center; justify-content: space-between; padding: 16rpx 8rpx; border-bottom: 1rpx solid #292f4d; box-sizing: border-box; }.selector-copy { min-width: 0; }.selector-name, .selector-email { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.selector-name { color: #edf0f7; font-size: 26rpx; }.selector-email { margin-top: 7rpx; color: #707b93; font-size: 21rpx; }.selector-selected { flex-shrink: 0; margin-left: 20rpx; color: #72b7ee; font-size: 21rpx; }.selector-empty { padding: 70rpx 20rpx; color: #677087; font-size: 24rpx; text-align: center; }
</style>
