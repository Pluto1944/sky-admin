<template>
  <view class="clan-stats-root">
    <view class="clan-stats-tabs">
      <view class="clan-stats-tab" :class="{ active: tab === 'war' }" @tap="switchTab('war')">部落战(满星前)</view>
      <view class="clan-stats-tab" :class="{ active: tab === 'league' }" @tap="switchTab('league')">联赛</view>
    </view>
    <view v-if="loading" class="clan-stats-state"><text>加载中...</text></view>
    <view v-else-if="!stats.length" class="clan-stats-state"><text class="clan-stats-empty-icon">📊</text><text>暂无战营数据</text></view>
    <view v-else class="clan-stats-table-wrap">
      <view v-if="updatedAt" class="clan-stats-update">数据更新于 {{ updatedAt }}<text v-if="tab === 'war' && coverage"> · 已收录 {{ coverage.available }}/{{ coverage.target }} 场</text><text> · 轻触数据看详情</text></view>
      <view class="clan-stats-tr clan-stats-head">
        <text class="clan-stats-td cs-name">昵称</text><text class="clan-stats-td cs-th">本</text>
        <text v-for="column in columns" :key="column.key" class="clan-stats-td cs-data clan-stats-head-cell" @tap="onSort(column.key)">
          <text>{{ column.line1 }}</text><text>{{ column.line2 }}</text><text v-if="sortKey === column.key" class="clan-stats-arrow">{{ sortOrder === 'desc' ? '↓' : '↑' }}</text>
        </text>
      </view>
      <scroll-view scroll-y class="clan-stats-body">
        <view v-for="(item, index) in sortedStats" :key="item.player_tag" class="clan-stats-tr" :class="{ 'clan-stats-even': index % 2 === 1 }">
          <text class="clan-stats-td cs-name clan-stats-name">{{ item.account_name }}</text><text class="clan-stats-td cs-th clan-stats-th">{{ item.town_hall_level || '-' }}</text>
          <view v-for="column in columns" :key="column.key" class="clan-stats-td cs-data clan-stats-data" :aria-label="sampleDescription(item, column)" @tap="showSample(item, column)">
            <text class="clan-stats-rate" :style="{ color: getColor(item[column.key], column.key) }">{{ formatRate(item[column.key]) }}</text>
            <view class="clan-stats-attacks">
              <text class="clan-stats-attacks-count">{{ sampleAttacks(item, column) }}</text>
              <text class="clan-stats-attacks-unit">刀</text>
            </view>
          </view>
        </view>
      </scroll-view>
    </view>

    <view v-if="sampleDetail" class="clan-stats-detail-mask" @tap="closeSample">
      <view class="clan-stats-detail-panel" @tap.stop>
        <view class="clan-stats-detail-header">
          <text>{{ sampleDetail.title }}</text>
          <text class="clan-stats-detail-close" @tap="closeSample">关闭</text>
        </view>
        <text class="clan-stats-detail-name">{{ sampleDetail.playerName }}</text>
        <view class="clan-stats-detail-metrics">
          <view class="clan-stats-detail-metric">
            <text class="clan-stats-detail-label">{{ sampleDetail.rateLabel }}</text>
            <text class="clan-stats-detail-value" :style="{ color: sampleDetail.color }">{{ sampleDetail.rate }}</text>
          </view>
          <view class="clan-stats-detail-metric">
            <text class="clan-stats-detail-label">{{ sampleDetail.starsLabel }}</text>
            <text class="clan-stats-detail-value">{{ sampleDetail.stars }}次</text>
          </view>
          <view class="clan-stats-detail-metric">
            <text class="clan-stats-detail-label">{{ sampleDetail.attacksLabel }}</text>
            <text class="clan-stats-detail-value">{{ sampleDetail.attacks }}刀</text>
          </view>
        </view>
      </view>
    </view>
  </view>
</template>

<script>
import { getLeagueStats, getWarStats } from '@/utils/api.js'

const WAR_COLUMNS = [
  { key: 'offense_5', line1: '进攻', line2: '前5场' }, { key: 'offense_15', line1: '进攻', line2: '前15场' }, { key: 'offense_45', line1: '进攻', line2: '前45场' },
  { key: 'defense_5', line1: '防守', line2: '前5场' }, { key: 'defense_15', line1: '防守', line2: '前15场' }, { key: 'defense_45', line1: '防守', line2: '前45场' }
]
const LEAGUE_COLUMNS = [
  { key: 'offense_1m', line1: '进攻', line2: '上月' }, { key: 'offense_3m', line1: '进攻', line2: '前3月' }, { key: 'offense_6m', line1: '进攻', line2: '前6月' },
  { key: 'defense_1m', line1: '防守', line2: '上月' }, { key: 'defense_3m', line1: '防守', line2: '前3月' }, { key: 'defense_6m', line1: '防守', line2: '前6月' }
]
const statsCache = { war: null, league: null }

export default {
  name: 'ClanStats',
  data() { return { loading: true, stats: [], updatedAt: '', coverage: null, tab: 'war', sortKey: 'offense_45', sortOrder: 'desc', sampleDetail: null } },
  computed: {
    columns() { return this.tab === 'war' ? WAR_COLUMNS : LEAGUE_COLUMNS },
    sortedStats() {
      const result = this.stats.slice(); const key = this.sortKey; const order = this.sortOrder
      result.sort((a, b) => { const av = a[key]; const bv = b[key]; if (av == null) return 1; if (bv == null) return -1; return order === 'desc' ? bv - av : av - bv })
      return result
    }
  },
  created() { this.fetchData() },
  methods: {
    switchTab(tab) { if (this.tab === tab) return; this.tab = tab; this.sortKey = tab === 'war' ? 'offense_45' : 'offense_6m'; this.sortOrder = 'desc'; this.fetchData() },
    applyResponse(response) { this.stats = response.stats || []; this.updatedAt = response.updated_at ? this.formatTime(response.updated_at) : ''; this.coverage = response.history_coverage || null },
    async fetchData() {
      this.loading = true
      try {
        if (!statsCache[this.tab]) statsCache[this.tab] = this.tab === 'war' ? await getWarStats() : await getLeagueStats()
        this.applyResponse(statsCache[this.tab])
      } catch (e) { uni.showToast({ title: '加载失败', icon: 'none' }) }
      finally { this.loading = false }
    },
    formatTime(value) { if (!value) return ''; const date = new Date(value.replace('+00:00', 'Z')); if (isNaN(date.getTime())) return value; return `${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}` },
    onSort(key) { if (this.sortKey === key) this.sortOrder = this.sortOrder === 'desc' ? 'asc' : 'desc'; else { this.sortKey = key; this.sortOrder = 'desc' } },
    formatRate(value) { return value == null ? '无' : (value * 100).toFixed(0) + '%' },
    getColor(value, key) { if (value == null) return '#666'; if (key && key.startsWith('defense')) return value <= 0.571 ? '#00b894' : value <= 0.857 ? '#fdcb6e' : '#e17055'; return value > 0.857 ? '#00b894' : value > 0.571 ? '#fdcb6e' : '#e17055' },
    sampleAttacks(item, column) { return Number((item[column.key + '_sample'] || {}).attacks) || 0 },
    sampleDescription(item, column) {
      const sample = item[column.key + '_sample'] || {}
      const stars = Number(sample.three_stars) || 0
      const attacks = Number(sample.attacks) || 0
      const rate = this.formatRate(item[column.key])
      return column.key.startsWith('defense')
        ? `${column.line1}${column.line2}：${rate}，被三星 ${stars} 次，有效被进攻 ${attacks} 刀`
        : `${column.line1}${column.line2}：${rate}，三星 ${stars} 次，有效进攻 ${attacks} 刀`
    },
    showSample(item, column) {
      if (item[column.key] == null) return
      const sample = item[column.key + '_sample'] || {}
      const defense = column.key.startsWith('defense')
      this.sampleDetail = {
        title: `${column.line1}${column.line2}`,
        playerName: item.account_name,
        rateLabel: defense ? '被三星率' : '三星率',
        rate: this.formatRate(item[column.key]),
        color: this.getColor(item[column.key], column.key),
        starsLabel: defense ? '被三星次数' : '三星次数',
        stars: Number(sample.three_stars) || 0,
        attacksLabel: defense ? '有效被进攻' : '有效进攻',
        attacks: Number(sample.attacks) || 0
      }
    },
    closeSample() { this.sampleDetail = null }
  }
}
</script>

<style>
.clan-stats-root { flex: 1; min-height: 0; display: flex; flex-direction: column; background: #0f0f23; }
.clan-stats-tabs { display: flex; flex-shrink: 0; height: 72rpx; background: #141428; border-bottom: 1rpx solid #1a1a2e; }
.clan-stats-tab { flex: 1; display: flex; align-items: center; justify-content: center; color: #66708a; font-size: 28rpx; }
.clan-stats-tab.active { color: #4a90d9; font-weight: 600; border-bottom: 4rpx solid #4a90d9; }
.clan-stats-state { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; color: #8890a0; font-size: 28rpx; }
.clan-stats-empty-icon { margin-bottom: 20rpx; font-size: 80rpx; }
.clan-stats-update { flex-shrink: 0; padding: 16rpx 0 4rpx; color: #556078; font-size: 24rpx; text-align: center; }
.clan-stats-table-wrap { flex: 1; min-height: 0; display: flex; flex-direction: column; overflow: hidden; }
.clan-stats-body { flex: 1; height: 0; }
.clan-stats-tr { display: flex; align-items: center; height: 72rpx; border-bottom: 1rpx solid #1a1a2e; }
.clan-stats-head { height: 88rpx; flex-shrink: 0; background: #1a1a2e; border-bottom: 2rpx solid #2a2a4a; }
.clan-stats-even { background: rgba(26, 26, 46, 0.4); }
.clan-stats-td { flex-shrink: 0; text-align: center; font-size: 24rpx; border-right: 1rpx solid #1a1a2e; line-height: 72rpx; }
.cs-name { width: 120rpx; padding-left: 12rpx; text-align: left; }.cs-th { width: 50rpx; }.cs-data { width: 96rpx; line-height: 1.2; display: flex; flex-direction: column; align-items: center; justify-content: center; }
.clan-stats-head-cell { color: #8890a0; font-weight: 600; font-size: 20rpx; }.clan-stats-arrow { color: #4a90d9; font-size: 16rpx; }
.clan-stats-name { color: #e0e0e0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }.clan-stats-th { color: #4a90d9; font-weight: 600; }.clan-stats-data { font-weight: 600; }.clan-stats-rate { font-size: 23rpx; line-height: 28rpx; }
.clan-stats-attacks { margin-top: 4rpx; display: flex; align-items: baseline; justify-content: center; color: #7b849b; font-weight: 400; line-height: 19rpx; }
.clan-stats-attacks-count { font-size: 18rpx; }
.clan-stats-attacks-unit { margin-left: 3rpx; color: #596178; font-size: 15rpx; }
.clan-stats-detail-mask { position: fixed; z-index: 1000; top: 0; right: 0; bottom: 0; left: 0; display: flex; align-items: center; justify-content: center; background: rgba(0,0,0,.62); }
.clan-stats-detail-panel { width: calc(100% - 48rpx); padding: 24rpx 28rpx 30rpx; box-sizing: border-box; border: 1rpx solid #343452; border-radius: 20rpx; background: #1a1a30; box-shadow: 0 16rpx 48rpx rgba(0,0,0,.42); }
.clan-stats-detail-header { display: flex; align-items: center; justify-content: space-between; color: #dfe5f0; font-size: 27rpx; font-weight: 600; }
.clan-stats-detail-close { padding: 10rpx; color: #5fa8ff; font-size: 22rpx; font-weight: 400; }
.clan-stats-detail-name { display: block; margin-top: 24rpx; overflow: hidden; color: #f0f0f5; font-size: 26rpx; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.clan-stats-detail-metrics { margin-top: 22rpx; display: flex; border-top: 1rpx solid #2a2a44; }
.clan-stats-detail-metric { min-width: 0; flex: 1; padding-top: 20rpx; display: flex; flex-direction: column; align-items: center; }
.clan-stats-detail-label { color: #66708a; font-size: 19rpx; white-space: nowrap; }
.clan-stats-detail-value { margin-top: 8rpx; color: #c9cfda; font-size: 24rpx; font-weight: 600; white-space: nowrap; }
</style>
