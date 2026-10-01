<template>
  <view class="clan-members-root">
    <view class="clan-members-toolbar">
      <text class="clan-members-tool" @tap="onFilter">⏬ 筛选</text>
      <text class="clan-members-tool" @tap="onSearch">🔍 搜索</text>
    </view>
    <view v-if="loading" class="clan-members-state"><text>加载成员...</text></view>
    <view v-else-if="!members.length" class="clan-members-state"><text>暂无成员数据</text></view>
    <scroll-view v-else scroll-x scroll-y class="clan-members-table-scroll">
      <view class="clan-members-table-wrap">
        <view v-if="updatedAt" class="clan-members-update">数据更新于 {{ updatedAt }}</view>
        <view v-if="searchText || memberFilter !== 'all' || clanFilters.length" class="clan-members-summary">
          <text>当前：{{ filterLabel }}{{ searchText ? ' · “' + searchText + '”' : '' }} · {{ sortedMembers.length }} 人</text>
          <text class="clan-members-clear" @tap="clearFilters">清除</text>
        </view>
        <view class="clan-members-tr clan-members-head">
          <view class="clan-members-td cm-name" @tap="onSort('account_name')">昵称{{ sortMark('account_name') }}</view><view class="clan-members-td cm-owner">归属人</view><view class="clan-members-td cm-clan" @tap="onSort('clan_tag')">部落{{ sortMark('clan_tag') }}</view><view class="clan-members-td cm-role">职位</view><view class="clan-members-td cm-th" @tap="onSort('town_hall_level')">本{{ sortMark('town_hall_level') }}</view><view class="clan-members-td cm-exp" @tap="onSort('exp_level')">经验{{ sortMark('exp_level') }}</view><view class="clan-members-td cm-trophy" @tap="onSort('trophies')">奖杯{{ sortMark('trophies') }}</view><view class="clan-members-td cm-league">联赛</view><view class="clan-members-td cm-score" @tap="onSort('history_score')">历史分{{ sortMark('history_score') }}</view><view class="clan-members-td cm-status">报名状态</view><view class="clan-members-td cm-member">成员状态</view><view class="clan-members-td cm-reg">最近报名</view><view class="clan-members-td cm-sync">最近同步</view>
        </view>
        <view v-if="!sortedMembers.length" class="clan-members-no-result">没有符合条件的成员</view>
        <view v-for="(item, idx) in sortedMembers" :key="item.player_tag" class="clan-members-tr" :class="{ 'clan-members-even': idx % 2 === 1 }">
          <view class="clan-members-td cm-name clan-members-name-text">{{ item.account_name || '-' }}</view><view class="clan-members-td cm-owner">{{ item.player_name || '-' }}</view><view class="clan-members-td cm-clan">{{ item.clan_tag || '-' }}</view><view class="clan-members-td cm-role">{{ formatRole(item.clan_role) }}</view><view class="clan-members-td cm-th">{{ item.town_hall_level || '-' }}</view><view class="clan-members-td cm-exp">{{ item.exp_level || '-' }}</view><view class="clan-members-td cm-trophy">{{ item.trophies || 0 }}</view><view class="clan-members-td cm-league">{{ item.league_name || '-' }}</view><view class="clan-members-td cm-score">{{ item.history_score || 0 }}</view><view class="clan-members-td cm-status">{{ formatStatus(item.status) }}</view><view class="clan-members-td cm-member">{{ formatStatus(item.membership_status) }}</view><view class="clan-members-td cm-reg">{{ item.last_reg_period || '-' }}</view><view class="clan-members-td cm-sync">{{ formatTime(item.last_synced_at) }}</view>
        </view>
      </view>
    </scroll-view>

    <view v-if="filterPanelVisible" class="clan-members-mask" @tap="closeFilterPanel">
      <view class="clan-members-panel" @tap.stop>
        <view class="clan-members-panel-title">筛选成员</view>
        <text class="clan-members-group-title">成员状态</text>
        <view class="clan-members-options">
          <view v-for="option in memberFilterOptions" :key="option.key" class="clan-members-option" @tap="draftMemberFilter = option.key">
            <text class="clan-members-check" :class="{ checked: draftMemberFilter === option.key }">{{ draftMemberFilter === option.key ? '✓' : '' }}</text><text>{{ option.label }}</text>
          </view>
        </view>
        <text class="clan-members-group-title">部落（可多选）</text>
        <scroll-view scroll-y class="clan-members-clan-options">
          <view v-for="clan in clanOptions" :key="clan.tag" class="clan-members-option" @tap="toggleClanFilter(clan.tag)">
            <text class="clan-members-check" :class="{ checked: draftClanFilters.indexOf(clan.tag) >= 0 }">{{ draftClanFilters.indexOf(clan.tag) >= 0 ? '✓' : '' }}</text><text>{{ clan.name }}（{{ clan.tag }}）</text>
          </view>
          <text v-if="!clanOptions.length" class="clan-members-filter-empty">暂无部落数据</text>
        </scroll-view>
        <view class="clan-members-actions">
          <text class="clan-members-action clan-members-clear-action" @tap="clearFilters">清除</text>
          <text class="clan-members-action clan-members-cancel-action" @tap="closeFilterPanel">取消</text>
          <text class="clan-members-action clan-members-confirm-action" @tap="applyFilters">确定</text>
        </view>
      </view>
    </view>
  </view>
</template>

<script>
import { getMembers } from '@/utils/api.js'

let membersCache = null

export default {
  name: 'ClanMembers',
  props: { initialClanTag: { type: String, default: '' } },
  data() {
    return { members: [], allowedClans: [], loading: true, updatedAt: '', sortKey: 'town_hall_level', sortOrder: 'desc', searchText: '', memberFilter: 'all', clanFilters: [], filterPanelVisible: false, draftMemberFilter: 'all', draftClanFilters: [] }
  },
  computed: {
    memberFilterOptions() { return [{ key: 'all', label: '全部成员' }, { key: 'member', label: '仅在部落' }, { key: 'left', label: '已离开' }] },
    clanOptions() { return this.allowedClans },
    filterLabel() {
      const labels = []
      if (this.memberFilter !== 'all') labels.push(({ member: '仅在部落', left: '已离开' }[this.memberFilter] || '全部成员'))
      if (this.clanFilters.length) labels.push(`部落 ${this.clanFilters.length}个`)
      return labels.length ? labels.join(' · ') : '全部成员'
    },
    sortedMembers() {
      const keyword = this.searchText.trim().toLowerCase()
      const result = this.members.filter((item) => {
        if (this.memberFilter !== 'all' && (item.membership_status || item.status) !== this.memberFilter) return false
        if (this.clanFilters.length && !this.clanFilters.includes(item.clan_tag)) return false
        if (!keyword) return true
        return [item.account_name, item.player_name, item.player_tag, item.clan_tag, item.league_name].filter(Boolean).some(value => String(value).toLowerCase().includes(keyword))
      })
      const key = this.sortKey
      result.sort((x, y) => {
        const xv = x[key]; const yv = y[key]
        if (xv == null) return 1
        if (yv == null) return -1
        const comparison = typeof xv === 'number' && typeof yv === 'number' ? xv - yv : String(xv).localeCompare(String(yv), 'zh-CN')
        return this.sortOrder === 'desc' ? -comparison : comparison
      })
      return result
    }
  },
  watch: {
    initialClanTag() { this.applyInitialClan() }
  },
  created() {
    if (membersCache) {
      this.applyResponse(membersCache)
      this.loading = false
    } else {
      this.fetchMembers()
    }
  },
  methods: {
    applyResponse(res) {
      this.members = res.members || []
      this.allowedClans = res.clans || []
      const times = this.members.map(item => item.last_synced_at).filter(Boolean).sort()
      this.updatedAt = times.length ? this.formatTime(times[times.length - 1]) : ''
      this.applyInitialClan()
    },
    applyInitialClan() {
      if (this.initialClanTag) {
        this.clanFilters = [this.initialClanTag]
        this.memberFilter = 'member'
      }
    },
    async fetchMembers() {
      try {
        const res = await getMembers()
        membersCache = res
        this.applyResponse(res)
      } catch (e) {
        uni.showToast({ title: '加载成员失败', icon: 'none' })
      } finally {
        this.loading = false
      }
    },
    formatRole(value) { return ({ leader: '首领', coLeader: '副首领', admin: '长老', member: '成员' }[value] || value || '-') },
    formatStatus(value) { return value === 'member' ? '在部落' : value === 'left' ? '已离开' : '-' },
    formatTime(value) {
      if (!value) return '-'
      const date = new Date(String(value).replace('+00:00', 'Z'))
      if (isNaN(date.getTime())) return String(value)
      const month = String(date.getMonth() + 1).padStart(2, '0')
      const day = String(date.getDate()).padStart(2, '0')
      const hour = String(date.getHours()).padStart(2, '0')
      const minute = String(date.getMinutes()).padStart(2, '0')
      return `${month}-${day} ${hour}:${minute}`
    },
    onSort(key) { if (this.sortKey === key) this.sortOrder = this.sortOrder === 'desc' ? 'asc' : 'desc'; else { this.sortKey = key; this.sortOrder = 'desc' } },
    sortMark(key) { return this.sortKey === key ? (this.sortOrder === 'desc' ? '↓' : '↑') : '' },
    onFilter() { this.draftMemberFilter = this.memberFilter; this.draftClanFilters = this.clanFilters.slice(); this.filterPanelVisible = true },
    closeFilterPanel() { this.filterPanelVisible = false },
    toggleClanFilter(tag) { const index = this.draftClanFilters.indexOf(tag); if (index >= 0) this.draftClanFilters.splice(index, 1); else this.draftClanFilters.push(tag) },
    applyFilters() { this.memberFilter = this.draftMemberFilter; this.clanFilters = this.draftClanFilters.slice(); this.filterPanelVisible = false },
    onSearch() {
      uni.showModal({ title: '搜索成员', editable: true, placeholderText: '输入昵称、玩家标签或部落标签', content: this.searchText, success: (res) => { if (res.confirm) this.searchText = (res.content || '').trim() } })
    },
    clearFilters() { this.searchText = ''; this.memberFilter = 'all'; this.clanFilters = []; this.draftMemberFilter = 'all'; this.draftClanFilters = []; this.filterPanelVisible = false }
  }
}
</script>

<style>
.clan-members-root { flex: 1; min-height: 0; display: flex; flex-direction: column; background: #0f0f23; }
.clan-members-toolbar { display: flex; flex-shrink: 0; justify-content: flex-end; min-height: 72rpx; align-items: center; padding: 0 18rpx; background: #141428; border-bottom: 1rpx solid #252540; }
.clan-members-tool { margin-left: 12rpx; padding: 12rpx 18rpx; color: #aab4c8; background: #1d1d35; border-radius: 10rpx; font-size: 25rpx; }
.clan-members-state { flex: 1; display: flex; align-items: center; justify-content: center; color: #8890a0; font-size: 28rpx; }
.clan-members-table-scroll { flex: 1; min-height: 0; width: 100%; }
.clan-members-table-wrap { width: 1570rpx; padding-bottom: 100rpx; }
.clan-members-update { padding: 12rpx 0 8rpx; color: #66708a; font-size: 22rpx; text-align: center; }
.clan-members-summary { height: 56rpx; display: flex; align-items: center; justify-content: center; color: #9aa0b0; font-size: 22rpx; background: #15152a; }
.clan-members-clear { color: #5fa8ff; margin-left: 18rpx; padding: 8rpx; }
.clan-members-tr { display: flex; flex-direction: row; width: 1570rpx; height: 72rpx; align-items: center; border-bottom: 2rpx solid #33334d; }
.clan-members-head { height: 88rpx; background: #262644; border-top: 2rpx solid #4a4a70; }
.clan-members-even { background: #19192f; }
.clan-members-td { display: flex; align-items: center; justify-content: center; flex-shrink: 0; box-sizing: border-box; height: 100%; color: #d0d0dc; font-size: 24rpx; border-right: 2rpx solid #33334d; white-space: nowrap; overflow: hidden; }
.clan-members-head .clan-members-td { color: #fff; font-weight: 600; background: #262644; border-color: #5a5a80; }
.cm-name { width: 190rpx; padding: 0 12rpx; justify-content: flex-start; border-left: 2rpx solid #33334d; }.cm-owner { width: 140rpx; }.cm-clan { width: 150rpx; }.cm-role { width: 120rpx; }.cm-th { width: 60rpx; }.cm-exp { width: 70rpx; }.cm-trophy { width: 100rpx; }.cm-league { width: 150rpx; }.cm-score { width: 110rpx; }.cm-status { width: 120rpx; }.cm-member { width: 120rpx; }.cm-reg { width: 110rpx; }.cm-sync { width: 130rpx; }
.clan-members-name-text { color: #f0f0f5; }
.clan-members-no-result { width: 750rpx; padding: 80rpx 0; color: #777f96; font-size: 26rpx; text-align: center; }
.clan-members-mask { position: fixed; left: 0; right: 0; top: 0; bottom: 0; z-index: 1000; display: flex; align-items: flex-end; background: rgba(0, 0, 0, 0.58); }
.clan-members-panel { width: 100%; max-height: 78vh; box-sizing: border-box; padding: 28rpx 32rpx 36rpx; background: #1a1a2e; border-radius: 24rpx 24rpx 0 0; }
.clan-members-panel-title { margin-bottom: 24rpx; color: #fff; font-size: 32rpx; font-weight: 600; text-align: center; }
.clan-members-group-title { display: block; margin: 18rpx 0 12rpx; color: #8890a0; font-size: 24rpx; }
.clan-members-options { display: flex; flex-wrap: wrap; }
.clan-members-option { display: flex; align-items: center; min-height: 72rpx; margin-right: 28rpx; color: #d0d0dc; font-size: 26rpx; }
.clan-members-check { display: flex; width: 36rpx; height: 36rpx; box-sizing: border-box; align-items: center; justify-content: center; margin-right: 10rpx; border: 2rpx solid #66708a; border-radius: 6rpx; color: #fff; font-size: 26rpx; }
.clan-members-check.checked { border-color: #4a90d9; background: #4a90d9; }
.clan-members-clan-options { max-height: 360rpx; border-top: 1rpx solid #2a2a4a; border-bottom: 1rpx solid #2a2a4a; }
.clan-members-clan-options .clan-members-option { margin-right: 0; padding: 0 8rpx; border-bottom: 1rpx solid #252540; }
.clan-members-filter-empty { display: block; padding: 28rpx 0; color: #66708a; font-size: 24rpx; text-align: center; }
.clan-members-actions { display: flex; justify-content: flex-end; margin-top: 24rpx; }
.clan-members-action { min-width: 120rpx; margin-left: 16rpx; padding: 16rpx 24rpx; border-radius: 8rpx; text-align: center; font-size: 26rpx; }
.clan-members-clear-action { color: #e06060; }.clan-members-cancel-action { color: #aab4c8; background: #252540; }.clan-members-confirm-action { color: #fff; background: #4a90d9; }
</style>
