<template>
  <view class="clan-members-root">
    <view class="clan-members-toolbar">
      <view class="clan-members-overview">
        <view class="clan-members-overview-main">
          <text class="clan-members-count">{{ sortedMembers.length }}</text>
          <text class="clan-members-count-label">位成员</text>
          <text v-if="updatedAt" class="clan-members-update">更新 {{ updatedAt }}</text>
        </view>
        <view class="clan-members-overview-meta">
          <text class="clan-members-filter-summary">{{ filterSummary }}</text>
          <text v-if="hasActiveFilters" class="clan-members-reset" @tap="clearFilters">重置</text>
        </view>
      </view>
      <view class="clan-members-tools">
        <view class="clan-members-tool" :class="{ active: activeFilterCount }" @tap="onFilter">
          <text class="clan-members-tool-icon">⏬</text><text>筛选</text>
          <text v-if="activeFilterCount" class="clan-members-tool-badge">{{ activeFilterCount }}</text>
        </view>
        <view class="clan-members-tool" :class="{ active: searchText }" @tap="onSearch">
          <text class="clan-members-tool-icon">🔍</text><text>搜索</text>
        </view>
      </view>
    </view>
    <view v-if="!loading && sortedMembers.length > pageSize" class="clan-members-pagination">
      <text class="clan-members-page-action" :class="{ disabled: currentPage <= 1 }" @tap="previousPage">‹ 上一页</text>
      <text class="clan-members-page-label">第 {{ currentPage }}/{{ totalPages }} 页 · 每页 {{ pageSize }} 人</text>
      <text class="clan-members-page-action" :class="{ disabled: currentPage >= totalPages }" @tap="nextPage">下一页 ›</text>
    </view>
    <view v-if="loading" class="clan-members-state"><text>加载成员...</text></view>
    <view v-else-if="!members.length" class="clan-members-state"><text>暂无成员数据</text></view>
    <scroll-view v-else scroll-x scroll-y :scroll-top="tableScrollTop" class="clan-members-table-scroll">
      <view class="clan-members-table-wrap">
        <view class="clan-members-tr clan-members-head">
          <view class="clan-members-td cm-name" @tap="onSort('account_name')">昵称{{ sortMark('account_name') }}</view><view class="clan-members-td cm-tag">玩家标签</view><view class="clan-members-td cm-clan" @tap="onSort('clan_tag')">部落{{ sortMark('clan_tag') }}</view><view class="clan-members-td cm-role">职位</view><view class="clan-members-td cm-th" @tap="onSort('town_hall_level')">本{{ sortMark('town_hall_level') }}</view><view class="clan-members-td cm-league">联赛</view><view class="clan-members-td cm-trophy" @tap="onSort('trophies')">奖杯{{ sortMark('trophies') }}</view><view class="clan-members-td cm-attacks" @tap="onSort('season_attack_wins')">赛季进攻{{ sortMark('season_attack_wins') }}</view><view class="clan-members-td cm-donation" @tap="onSort('donations')">赛季捐兵{{ sortMark('donations') }}</view><view class="clan-members-td cm-donation" @tap="onSort('donations_received')">赛季收兵{{ sortMark('donations_received') }}</view><view class="clan-members-td cm-war" @tap="onSort('war_recent_15')">部落战近15场{{ sortMark('war_recent_15') }}</view><view class="clan-members-td cm-cwl" @tap="onSort('cwl_recent_3m')">联赛近3月{{ sortMark('cwl_recent_3m') }}</view><view class="clan-members-td cm-cwl-risk" @tap="onSort('cwl_one_star_rate')">一星率近3月{{ sortMark('cwl_one_star_rate') }}</view><view class="clan-members-td cm-cwl-risk" @tap="onSort('cwl_missed_attack_rate')">漏刀近3月{{ sortMark('cwl_missed_attack_rate') }}</view><view class="clan-members-td cm-capital" @tap="onSort('capital_recent_4w')">都城近4周{{ sortMark('capital_recent_4w') }}</view><view class="clan-members-td cm-games" @tap="onSort('clan_games')">竞赛贡献{{ sortMark('clan_games') }}</view><view class="clan-members-td cm-activity" @tap="onSort('last_activity_at')">最近活动{{ sortMark('last_activity_at') }}</view>
        </view>
        <view v-if="!sortedMembers.length" class="clan-members-no-result">没有符合条件的成员</view>
        <view v-for="(item, idx) in pageMembers" :key="item.player_tag" class="clan-members-tr" :class="{ 'clan-members-even': idx % 2 === 1 }">
          <view class="clan-members-td cm-name clan-members-name-text"><text>{{ item.account_name || '-' }}</text><text v-if="item.membership_status === 'left'" class="clan-members-left-badge">已离开</text></view><view class="clan-members-td cm-tag">{{ item.player_tag || '-' }}</view><view class="clan-members-td cm-clan">{{ item.clan_name || item.clan_tag || '-' }}</view><view class="clan-members-td cm-role">{{ formatRole(item.clan_role) }}</view><view class="clan-members-td cm-th">{{ item.town_hall_level || '-' }}</view><view class="clan-members-td cm-league">{{ item.league_name || '-' }}</view><view class="clan-members-td cm-trophy">{{ numberText(item.trophies) }}</view><view class="clan-members-td cm-attacks">{{ numberText(item.season_attack_wins) }}</view><view class="clan-members-td cm-donation">{{ numberText(item.donations) }}</view><view class="clan-members-td cm-donation">{{ numberText(item.donations_received) }}</view><view class="clan-members-td cm-war clan-members-two-lines"><text>{{ warLine1(item.war_recent_15) }}</text><text class="clan-members-subline">{{ warLine2(item.war_recent_15) }}</text></view><view class="clan-members-td cm-cwl clan-members-two-lines"><text>{{ cwlLine1(item.cwl_recent_3m) }}</text><text class="clan-members-subline">{{ cwlLine2(item.cwl_recent_3m) }}</text></view><view class="clan-members-td cm-cwl-risk clan-members-two-lines"><text>{{ cwlOneStarLine1(item.cwl_recent_3m) }}</text><text class="clan-members-subline">{{ cwlOneStarLine2(item.cwl_recent_3m) }}</text></view><view class="clan-members-td cm-cwl-risk clan-members-two-lines"><text>{{ cwlMissedLine1(item.cwl_recent_3m) }}</text><text class="clan-members-subline">{{ cwlMissedLine2(item.cwl_recent_3m) }}</text></view><view class="clan-members-td cm-capital clan-members-two-lines"><text>{{ capitalLine1(item.capital_recent_4w) }}</text><text class="clan-members-subline">{{ capitalLine2(item.capital_recent_4w) }}</text></view><view class="clan-members-td cm-games clan-members-two-lines"><text>{{ gamesLine1(item.clan_games) }}</text><text class="clan-members-subline">{{ gamesLine2(item.clan_games) }}</text></view><view class="clan-members-td cm-activity clan-members-two-lines"><text>{{ activityTime(item) }}</text><text class="clan-members-subline">{{ activityReason(item) }}</text></view>
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
const MEMBER_PAGE_SIZE = 100

export default {
  name: 'ClanMembers',
  props: { initialClanTag: { type: String, default: '' } },
  data() {
    return {
      members: [], allowedClans: [], loading: true, updatedAt: '',
      sortKey: 'town_hall_level', sortOrder: 'desc', searchText: '',
      memberFilter: 'member', clanFilters: [], filterPanelVisible: false,
      draftMemberFilter: 'member', draftClanFilters: [],
      pageSize: MEMBER_PAGE_SIZE, currentPage: 1, tableScrollTop: 0
    }
  },
  computed: {
    memberFilterOptions() { return [{ key: 'all', label: '全部成员' }, { key: 'member', label: '仅在部落' }, { key: 'left', label: '已离开' }] },
    clanOptions() { return this.allowedClans },
    activeFilterCount() {
      return (this.memberFilter !== 'member' ? 1 : 0) + this.clanFilters.length
    },
    hasActiveFilters() {
      return Boolean(this.searchText || this.activeFilterCount)
    },
    filterSummary() {
      const labels = []
      if (this.memberFilter !== 'all') labels.push(({ member: '仅在部落', left: '已离开' }[this.memberFilter] || '全部成员'))
      if (this.clanFilters.length === 1) {
        const clan = this.clanOptions.find(item => item.tag === this.clanFilters[0])
        labels.push(clan ? clan.name : this.clanFilters[0])
      } else if (this.clanFilters.length > 1) {
        labels.push(`${this.clanFilters.length}个部落`)
      }
      if (this.searchText) labels.push(`“${this.searchText}”`)
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
        const xv = this.sortValue(x, key); const yv = this.sortValue(y, key)
        if (xv == null && yv == null) return 0
        if (xv == null) return 1
        if (yv == null) return -1
        const comparison = typeof xv === 'number' && typeof yv === 'number' ? xv - yv : String(xv).localeCompare(String(yv), 'zh-CN')
        return this.sortOrder === 'desc' ? -comparison : comparison
      })
      return result
    },
    totalPages() { return Math.max(1, Math.ceil(this.sortedMembers.length / this.pageSize)) },
    pageMembers() {
      const page = Math.min(this.currentPage, this.totalPages)
      const start = (page - 1) * this.pageSize
      return this.sortedMembers.slice(start, start + this.pageSize)
    }
  },
  watch: {
    initialClanTag() { this.applyInitialClan() },
    totalPages(value) {
      if (this.currentPage > value) this.goToPage(value)
    }
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
      this.updatedAt = res.updated_at ? this.formatTime(res.updated_at) : ''
      this.currentPage = 1
      this.applyInitialClan()
    },
    applyInitialClan() {
      if (this.initialClanTag) {
        this.clanFilters = [this.initialClanTag]
        this.memberFilter = 'member'
      }
      this.resetPage()
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
    numberText(value) { return value == null ? '-' : value },
    percent(value) { return value == null ? '-' : `${Number(value).toFixed(1).replace('.0', '')}%` },
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
    relativeTime(value) {
      if (!value) return '-'
      const date = new Date(String(value).replace('+00:00', 'Z'))
      if (isNaN(date.getTime())) return '-'
      const minutes = Math.max(0, Math.floor((Date.now() - date.getTime()) / 60000))
      if (minutes < 60) return `${Math.max(1, minutes)}分钟前`
      const hours = Math.floor(minutes / 60)
      if (hours < 24) return `${hours}小时前`
      const days = Math.floor(hours / 24)
      return days < 30 ? `${days}天前` : this.formatTime(value)
    },
    activityTime(item) { return item.last_activity_at ? this.relativeTime(item.last_activity_at) : '暂未检测到' },
    activityReason(item) {
      if (!item.last_activity_at) return item.activity_observed_since ? `观察始于 ${this.formatTime(item.activity_observed_since)}` : '尚未开始观察'
      const labels = { donations: '捐兵增加', donations_received: '收兵增加', exp_level: '经验提升', town_hall_level: '大本升级', name: '昵称变化', player_house: '玩家小屋变化', season_attack_wins: '赛季进攻', war_attack: '部落战出刀', cwl_attack: '联赛出刀' }
      return (item.last_activity_reasons || []).map(key => labels[key] || key).join('、') || '公开数据变化'
    },
    warLine1(stats) { return stats && stats.attacks ? `三星率 ${this.percent(stats.three_star_rate)}` : '-' },
    warLine2(stats) { return stats && stats.attacks ? `${stats.three_stars}/${stats.attacks}（共${stats.available_attacks}刀）` : '' },
    cwlLine1(stats) { return stats && stats.attacks ? `三星率 ${this.percent(stats.three_star_rate)}` : '-' },
    cwlLine2(stats) { return stats && stats.attacks ? `${stats.three_stars}/${stats.attacks}` : '' },
    cwlOneStarLine1(stats) { return stats && stats.attacks ? `一星率 ${this.percent(stats.one_star_rate)}` : '-' },
    cwlOneStarLine2(stats) { return stats && stats.attacks ? `${stats.one_stars}/${stats.attacks}刀` : '' },
    cwlMissedLine1(stats) { return stats && stats.appearances ? `漏刀率 ${this.percent(stats.missed_attack_rate)}` : '-' },
    cwlMissedLine2(stats) { return stats && stats.appearances ? `${stats.missed_attacks}/${stats.appearances}场` : '' },
    compactNumber(value) { if (value == null) return '-'; if (value >= 1000000) return `${(value / 1000000).toFixed(1)}M`; if (value >= 1000) return `${(value / 1000).toFixed(1)}K`; return String(value) },
    capitalLine1(stats) { return stats && stats.weeks ? `掠夺 ${this.compactNumber(stats.looted)}` : '-' },
    capitalLine2(stats) { return stats && stats.weeks ? `出刀 ${stats.attacks}/${stats.available_attacks} · 均${this.compactNumber(stats.loot_per_attack)}` : '' },
    gamesLine1(stats) { return stats ? `${stats.period || '-'} ${stats.complete ? this.numberText(stats.points) : '记录不完整'}` : '-' },
    gamesLine2(stats) { return stats && stats.average_3 != null ? `近${stats.period_count}期均 ${Math.round(stats.average_3)}` : '' },
    sortValue(item, key) {
      if (key === 'war_recent_15') return item.war_recent_15 && item.war_recent_15.three_star_rate
      if (key === 'cwl_recent_3m') return item.cwl_recent_3m && item.cwl_recent_3m.three_star_rate
      if (key === 'cwl_one_star_rate') return item.cwl_recent_3m && item.cwl_recent_3m.one_star_rate
      if (key === 'cwl_missed_attack_rate') return item.cwl_recent_3m && item.cwl_recent_3m.missed_attack_rate
      if (key === 'capital_recent_4w') return item.capital_recent_4w && item.capital_recent_4w.looted
      if (key === 'clan_games') return item.clan_games && item.clan_games.points
      if (key === 'last_activity_at') return item.last_activity_at ? new Date(String(item.last_activity_at).replace('+00:00', 'Z')).getTime() : null
      return item[key]
    },
    resetTableScroll() {
      this.tableScrollTop = 1
      this.$nextTick(() => { this.tableScrollTop = 0 })
    },
    resetPage() {
      this.currentPage = 1
      this.resetTableScroll()
    },
    goToPage(page) {
      const target = Math.min(this.totalPages, Math.max(1, Number(page) || 1))
      if (target === this.currentPage) return
      this.currentPage = target
      this.resetTableScroll()
    },
    previousPage() { this.goToPage(this.currentPage - 1) },
    nextPage() { this.goToPage(this.currentPage + 1) },
    onSort(key) {
      if (this.sortKey === key) this.sortOrder = this.sortOrder === 'desc' ? 'asc' : 'desc'
      else { this.sortKey = key; this.sortOrder = 'desc' }
      this.resetPage()
    },
    sortMark(key) { return this.sortKey === key ? (this.sortOrder === 'desc' ? '↓' : '↑') : '' },
    onFilter() { this.draftMemberFilter = this.memberFilter; this.draftClanFilters = this.clanFilters.slice(); this.filterPanelVisible = true },
    closeFilterPanel() { this.filterPanelVisible = false },
    toggleClanFilter(tag) { const index = this.draftClanFilters.indexOf(tag); if (index >= 0) this.draftClanFilters.splice(index, 1); else this.draftClanFilters.push(tag) },
    applyFilters() { this.memberFilter = this.draftMemberFilter; this.clanFilters = this.draftClanFilters.slice(); this.filterPanelVisible = false; this.resetPage() },
    onSearch() {
      uni.showModal({ title: '搜索成员', editable: true, placeholderText: '输入昵称、玩家标签或部落标签', content: this.searchText, success: (res) => { if (res.confirm) { this.searchText = (res.content || '').trim(); this.resetPage() } } })
    },
    clearFilters() { this.searchText = ''; this.memberFilter = 'member'; this.clanFilters = []; this.draftMemberFilter = 'member'; this.draftClanFilters = []; this.filterPanelVisible = false; this.resetPage() }
  }
}
</script>

<style>
.clan-members-root { flex: 1; min-height: 0; display: flex; flex-direction: column; background: #0f0f23; }
.clan-members-toolbar { display: flex; flex-shrink: 0; align-items: center; min-height: 112rpx; padding: 12rpx 18rpx; box-sizing: border-box; background: #141428; border-bottom: 1rpx solid #252540; }
.clan-members-overview { min-width: 0; flex: 1; }
.clan-members-overview-main { display: flex; align-items: baseline; min-width: 0; white-space: nowrap; }
.clan-members-count { color: #5fa8ff; font-size: 34rpx; font-weight: 700; }
.clan-members-count-label { margin-left: 6rpx; color: #d0d0dc; font-size: 25rpx; font-weight: 600; }
.clan-members-update { min-width: 0; margin-left: 14rpx; overflow: hidden; color: #596178; font-size: 20rpx; text-overflow: ellipsis; white-space: nowrap; }
.clan-members-overview-meta { display: flex; align-items: center; min-width: 0; margin-top: 6rpx; }
.clan-members-filter-summary { min-width: 0; overflow: hidden; color: #7d859d; font-size: 22rpx; text-overflow: ellipsis; white-space: nowrap; }
.clan-members-reset { flex-shrink: 0; margin-left: 10rpx; padding: 6rpx 4rpx; color: #5fa8ff; font-size: 21rpx; }
.clan-members-tools { display: flex; flex-shrink: 0; align-items: center; margin-left: 14rpx; }
.clan-members-tool { position: relative; display: flex; align-items: center; justify-content: center; min-width: 112rpx; min-height: 80rpx; margin-left: 10rpx; padding: 0 14rpx; box-sizing: border-box; color: #aab4c8; background: #1d1d35; border: 1rpx solid #292947; border-radius: 12rpx; font-size: 24rpx; }
.clan-members-tool.active { color: #73b6ff; background: #1c2c4f; border-color: #315386; }
.clan-members-tool-icon { margin-right: 6rpx; font-size: 25rpx; }
.clan-members-tool-badge { position: absolute; top: -9rpx; right: -7rpx; display: flex; align-items: center; justify-content: center; min-width: 32rpx; height: 32rpx; padding: 0 5rpx; box-sizing: border-box; color: #fff; background: #4a90d9; border: 3rpx solid #141428; border-radius: 18rpx; font-size: 18rpx; font-weight: 700; }
.clan-members-pagination { flex-shrink: 0; height: 64rpx; padding: 0 22rpx; display: flex; align-items: center; justify-content: space-between; box-sizing: border-box; color: #7d859d; background: #111126; border-bottom: 1rpx solid #252540; font-size: 21rpx; }.clan-members-page-action { min-width: 116rpx; padding: 12rpx 4rpx; color: #5fa8ff; }.clan-members-page-action:last-child { text-align: right; }.clan-members-page-action.disabled { color: #3f4658; }.clan-members-page-label { color: #8d95a8; }
.clan-members-state { flex: 1; display: flex; align-items: center; justify-content: center; color: #8890a0; font-size: 28rpx; }
.clan-members-table-scroll { flex: 1; min-height: 0; width: 100%; }
.clan-members-table-wrap { width: 2620rpx; padding-bottom: 100rpx; }
.clan-members-tr { display: flex; flex-direction: row; width: 2620rpx; height: 94rpx; align-items: center; border-bottom: 2rpx solid #33334d; }
.clan-members-head { height: 88rpx; background: #262644; border-top: 2rpx solid #4a4a70; }
.clan-members-even { background: #19192f; }
.clan-members-td { display: flex; align-items: center; justify-content: center; flex-shrink: 0; box-sizing: border-box; height: 100%; color: #d0d0dc; font-size: 24rpx; border-right: 2rpx solid #33334d; white-space: nowrap; overflow: hidden; }
.clan-members-head .clan-members-td { color: #fff; font-weight: 600; background: #262644; border-color: #5a5a80; }
.cm-name { position: sticky; left: 0; z-index: 2; width: 190rpx; padding: 0 12rpx; justify-content: flex-start; border-left: 2rpx solid #33334d; background: #0f0f23; box-shadow: 6rpx 0 10rpx rgba(5, 5, 18, .32); }
.clan-members-even .cm-name { background: #19192f; }
.clan-members-head .cm-name { z-index: 3; background: #262644; }
.cm-tag { width: 145rpx; }.cm-clan { width: 185rpx; padding: 0 8rpx; }.cm-role { width: 100rpx; }.cm-th { width: 60rpx; }.cm-league { width: 145rpx; }.cm-trophy { width: 95rpx; }.cm-attacks { width: 115rpx; }.cm-donation { width: 110rpx; }.cm-activity { width: 190rpx; }.cm-war { width: 215rpx; }.cm-cwl { width: 195rpx; }.cm-cwl-risk { width: 180rpx; }.cm-capital { width: 230rpx; }.cm-games { width: 175rpx; }
.clan-members-name-text { color: #f0f0f5; }
.clan-members-left-badge { flex-shrink: 0; margin-left: 8rpx; padding: 2rpx 7rpx; color: #7d859d; background: #29293d; border-radius: 6rpx; font-size: 18rpx; }
.clan-members-two-lines { flex-direction: column; line-height: 1.35; white-space: normal; }
.clan-members-subline { margin-top: 5rpx; color: #778099; font-size: 20rpx; }
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
