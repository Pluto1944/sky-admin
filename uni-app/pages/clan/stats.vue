<template>
  <view class="page-container">
    <TopBar title="联赛战绩" :showBack="true" />

    <view v-if="loading" class="loading-box"><text class="loading-text">加载中...</text></view>

    <view v-else-if="!stats.length" class="empty-box">
      <text class="empty-icon">📊</text>
      <text class="empty-text">暂无战绩数据</text>
    </view>

    <view v-else class="table-wrap">
      <!-- 表头 -->
      <view class="tr tr-head">
        <text class="td w-name">昵称</text>
        <text class="td w-th">本</text>
        <text v-for="col in columns" :key="col.key" class="td w-data head-cell" @tap="onSort(col.key)">
          <text class="hl">{{ col.line1 }}</text>
          <text class="hl">{{ col.line2 }}</text>
          <text v-if="sortKey === col.key" class="arrow">{{ sortOrder === 'desc' ? '↓' : '↑' }}</text>
        </text>
      </view>

      <!-- 数据体 -->
      <scroll-view scroll-y class="tbody">
        <view v-for="(item, idx) in sortedStats" :key="idx" class="tr" :class="{ 'tr-even': idx % 2 === 1 }">
          <text class="td w-name name-text">{{ item.account_name }}</text>
          <text class="td w-th th-text">{{ item.town_hall_level || '-' }}</text>
          <text
            v-for="col in columns"
            :key="col.key"
            class="td w-data data-text"
            :style="{ color: getColor(item[col.key], col.key) }"
          >{{ formatRate(item[col.key]) }}</text>
        </view>
      </scroll-view>
    </view>
  </view>
</template>

<script>
import TopBar from '@/components/TopBar.vue'
import { getLeagueStats } from '@/utils/api.js'

export default {
  components: { TopBar },
  data() {
    return {
      loading: true,
      stats: [],
      sortKey: 'offense_6m',
      sortOrder: 'desc',
      columns: [
        { key: 'offense_1m', line1: '进攻', line2: '上月' },
        { key: 'offense_3m', line1: '进攻', line2: '前3月' },
        { key: 'offense_6m', line1: '进攻', line2: '前6月' },
        { key: 'defense_1m', line1: '防守', line2: '上月' },
        { key: 'defense_3m', line1: '防守', line2: '前3月' },
        { key: 'defense_6m', line1: '防守', line2: '前6月' }
      ]
    }
  },
  computed: {
    sortedStats() {
      const arr = [...this.stats]
      const key = this.sortKey; const order = this.sortOrder
      arr.sort((a, b) => {
        const va = a[key]; const vb = b[key]
        if (va === null || va === undefined) return 1
        if (vb === null || vb === undefined) return -1
        return order === 'desc' ? vb - va : va - vb
      })
      return arr
    }
  },
  onLoad() { this.fetchData() },
  methods: {
    async fetchData() {
      this.loading = true
      try { const res = await getLeagueStats(); this.stats = res.stats || [] }
      catch (e) { uni.showToast({ title: '加载失败', icon: 'none' }) }
      finally { this.loading = false }
    },
    onSort(key) {
      if (this.sortKey === key) { this.sortOrder = this.sortOrder === 'desc' ? 'asc' : 'desc' }
      else { this.sortKey = key; this.sortOrder = 'desc' }
    },
    formatRate(val) {
      if (val === null || val === undefined) return '-'
      return (val * 100).toFixed(0) + '%'
    },
    getColor(val, colKey) {
      if (val === null || val === undefined) return '#666'
      // 防守：越低越好（≤4场被三星绿色，5~6场黄色，>6场红色）
      if (colKey && colKey.startsWith('defense')) {
        if (val <= 0.571) return '#00b894'      // ≤ 4/7 ≈ 57.1%
        if (val <= 0.857) return '#fdcb6e'      // ≤ 6/7 ≈ 85.7%
        return '#e17055'                          // > 6/7 ≈ 85.7%
      }
      // 进攻：越高越好（>6场三星绿色，5~6场黄色，≤4场红色）
      if (val > 0.857) return '#00b894'          // > 6/7 ≈ 85.7%
      if (val > 0.571) return '#fdcb6e'          // > 4/7 ≈ 57.1%
      return '#e17055'                            // ≤ 4/7 ≈ 57.1%
    }
  }
}
</script>

<style>
.page-container { height: 100vh; display: flex; flex-direction: column; background: #0f0f23; }
.loading-box { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; }
.empty-box { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; }
.loading-text { font-size: 28rpx; color: #888; }
.empty-icon { font-size: 80rpx; margin-bottom: 20rpx; }
.empty-text { font-size: 28rpx; color: #888; }

.table-wrap { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.tbody { flex: 1; height: 0; }

.tr { display: flex; flex-direction: row; align-items: center; height: 72rpx; border-bottom: 1rpx solid #1a1a2e; }
.tr-head { height: 88rpx; background: #1a1a2e; border-bottom: 2rpx solid #2a2a4a; flex-shrink: 0; }
.tr-even { background: rgba(26, 26, 46, 0.4); }

.td { flex-shrink: 0; text-align: center; font-size: 24rpx; border-right: 1rpx solid #1a1a2e; line-height: 72rpx; }
.w-name { width: 120rpx; padding-left: 12rpx; text-align: left; }
.w-th { width: 50rpx; }
.w-data { width: 96rpx; line-height: 1.3; display: flex; flex-direction: column; align-items: center; justify-content: center; }

.head-cell { color: #8890a0; font-weight: 600; line-height: 1.3; }
.hl { display: block; font-size: 20rpx; }
.arrow { font-size: 16rpx; color: #4a90d9; }

.name-text { color: #e0e0e0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.th-text { color: #4a90d9; font-weight: 600; }
.data-text { font-weight: 500; }
</style>
