<template>
  <view class="page-container">
    <TopBar title="战斗" :buttons="topButtons" @onRefresh="onRefresh" />

    <view v-if="loading" class="state-box"><text class="state-text">正在加载战绩...</text></view>
    <view v-else class="content">
      <view class="summary-card" @tap="openStats('war')">
        <view class="card-icon">⚔️</view>
        <view class="card-main">
          <text class="card-title">部落战表现</text>
          <text class="card-desc">查看成员最近 5、15、45 场进攻与防守表现</text>
          <text class="card-count">{{ warCount }} 名成员有战绩数据</text>
        </view>
        <text class="arrow">›</text>
      </view>

      <view class="summary-card" @tap="openStats('league')">
        <view class="card-icon">🏆</view>
        <view class="card-main">
          <text class="card-title">联赛战绩</text>
          <text class="card-desc">查看上月及近 3、6 个月联赛攻防表现</text>
          <text class="card-count">{{ leagueCount }} 名成员有联赛数据</text>
        </view>
        <text class="arrow">›</text>
      </view>

      <view class="info-card">
        <text class="info-title">数据说明</text>
        <text class="info-text">点击卡片可查看成员排名，并可按任意统计列升序或降序排列。</text>
        <text v-if="updatedAt" class="updated">最近更新：{{ updatedAt }}</text>
      </view>
    </view>
  </view>
</template>

<script>
import TopBar from '@/components/TopBar.vue'
import { getLeagueStats, getWarStats } from '@/utils/api.js'

export default {
  components: { TopBar },
  data() {
    return {
      topButtons: [{ key: 'refresh', icon: '🔄', text: '刷新', action: 'onRefresh' }],
      loading: true,
      warCount: 0,
      leagueCount: 0,
      updatedAt: ''
    }
  },
  onLoad() { this.loadSummary() },
  onShow() { if (!this.loading && !this.updatedAt) this.loadSummary() },
  methods: {
    async loadSummary(showFeedback = false) {
      this.loading = true
      try {
        const [war, league] = await Promise.all([getWarStats(), getLeagueStats()])
        this.warCount = (war.stats || []).length
        this.leagueCount = (league.stats || []).length
        const times = [war.updated_at, league.updated_at].filter(Boolean).sort()
        this.updatedAt = times.length ? this.formatTime(times[times.length - 1]) : ''
        if (showFeedback) uni.showToast({ title: '数据已刷新', icon: 'success' })
      } catch (e) {
        uni.showToast({ title: '战绩加载失败，请稍后重试', icon: 'none' })
      } finally {
        this.loading = false
      }
    },
    onRefresh() { this.loadSummary(true) },
    openStats(tab) { uni.navigateTo({ url: `/pages/clan/stats?tab=${tab}` }) },
    formatTime(value) {
      const d = new Date(String(value).replace('+00:00', 'Z'))
      if (isNaN(d.getTime())) return String(value)
      const month = String(d.getMonth() + 1).padStart(2, '0')
      const day = String(d.getDate()).padStart(2, '0')
      const hour = String(d.getHours()).padStart(2, '0')
      const minute = String(d.getMinutes()).padStart(2, '0')
      return `${month}-${day} ${hour}:${minute}`
    }
  }
}
</script>

<style scoped>
.page-container { min-height: 100vh; display: flex; flex-direction: column; background: #0f0f23; }
.content { flex: 1; padding: 30rpx 28rpx 130rpx; }
.state-box { flex: 1; display: flex; align-items: center; justify-content: center; }
.state-text { color: #8890a0; font-size: 28rpx; }
.summary-card { display: flex; align-items: center; background: linear-gradient(135deg, #1a1a3e, #1e1e40); border: 1rpx solid #2c2c52; border-radius: 18rpx; padding: 34rpx 26rpx; margin-bottom: 24rpx; }
.summary-card:active { opacity: 0.82; }
.card-icon { width: 78rpx; font-size: 48rpx; }
.card-main { flex: 1; display: flex; flex-direction: column; }
.card-title { color: #fff; font-size: 32rpx; font-weight: 600; margin-bottom: 10rpx; }
.card-desc { color: #9aa0b0; font-size: 24rpx; line-height: 1.5; }
.card-count { color: #5fa8ff; font-size: 23rpx; margin-top: 14rpx; }
.arrow { color: #667088; font-size: 52rpx; margin-left: 12rpx; }
.info-card { border-radius: 16rpx; background: #15152a; padding: 28rpx; margin-top: 36rpx; display: flex; flex-direction: column; }
.info-title { color: #d8dce8; font-size: 27rpx; font-weight: 600; margin-bottom: 12rpx; }
.info-text { color: #858b9c; font-size: 24rpx; line-height: 1.7; }
.updated { color: #5e6578; font-size: 22rpx; margin-top: 18rpx; }
</style>
