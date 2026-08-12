<template>
  <view class="page-container">
    <TopBar title="互刷部落" :showBack="true" :buttons="[]" />

    <view v-if="loading" class="loading-box"><text class="loading-text">加载中...</text></view>

    <view v-else-if="error" class="error-box">
      <text class="error-text">{{ error }}</text>
      <text class="retry-btn" @tap="fetchData">点击重试</text>
    </view>

    <view v-else-if="clans.length === 0" class="empty-box">
      <text class="empty-text">暂无互刷部落</text>
    </view>

    <scroll-view v-else scroll-y class="content-scroll">
      <view class="scroll-inner">
      <view v-if="updatedAt" class="update-time">
        <text class="update-text">数据更新于 {{ updatedAt }}</text>
      </view>

      <view v-for="clan in clans" :key="clan.clan_tag" class="clan-card">
        <!-- 标题行 -->
        <view class="clan-header">
          <text class="clan-name">{{ clan.clan_name }}</text>
          <text class="clan-tag">{{ clan.clan_tag }}</text>
          <text class="clan-badge">互刷</text>
          <text class="clan-count">人数:{{ clan.member_count }} / 50</text>
        </view>

        <!-- 表格一：部落实时配置 -->
        <view class="table-section">
          <view class="table-title">部落实时配置（大本数目）</view>
          <view class="table-body">
            <view class="tr tr-head">
              <text class="td td-avg">平均</text>
              <text class="td" v-for="lv in thLevels" :key="lv">{{ lv }}</text>
              <text class="td">other</text>
            </view>
            <view class="tr tr-data">
              <text class="td td-avg">{{ clan.realtime.avg_th }}</text>
              <text class="td" v-for="lv in thLevels" :key="lv">{{ clan.realtime.distribution[lv] || 0 }}</text>
              <text class="td">{{ otherCount(clan.realtime.distribution) }}</text>
            </view>
          </view>
        </view>

        <!-- 表格二：去速本后实时配置 -->
        <view class="table-section">
          <view class="table-title">部落去速本后实时配置（大本数目）</view>
          <view v-if="clan.despeed.has_war">
            <view class="table-body">
              <view class="tr tr-head">
                <text class="td td-avg">平均</text>
                <text class="td" v-for="lv in thLevels" :key="lv">{{ lv }}</text>
                <text class="td">other</text>
              </view>
              <view class="tr tr-data">
                <text class="td td-avg">{{ clan.despeed.avg_th }}</text>
                <text class="td" v-for="lv in thLevels" :key="lv">{{ clan.despeed.distribution[lv] || 0 }}</text>
                <text class="td">{{ otherCount(clan.despeed.distribution) }}</text>
              </view>
            </view>
          </view>
          <view v-else class="no-war">
            <text class="no-war-text">当前无部落战</text>
          </view>
        </view>
      </view>

      <view class="bottom-space"></view>
      </view>
    </scroll-view>
  </view>
</template>

<script>
import TopBar from '@/components/TopBar.vue'
import { getFarmConfig } from '@/utils/api.js'

export default {
  components: { TopBar },
  data() {
    return {
      loading: true,
      error: '',
      clans: [],
      updatedAt: '',
      thLevels: ['18', '17', '16', '15', '14', '13', '12', '11']
    }
  },
  created() {
    this.fetchData()
  },
  methods: {
    async fetchData() {
      this.loading = true
      this.error = ''
      try {
        const res = await getFarmConfig()
        this.clans = res.clans || []
        this.updatedAt = res.updated_at ? this.formatTime(res.updated_at) : ''
      } catch (e) {
        this.error = e.message || '加载失败'
      } finally {
        this.loading = false
      }
    },
    formatTime(isoStr) {
      if (!isoStr) return ''
      // 把 UTC ISO 时间转成北京时间显示
      const d = new Date(isoStr.replace('+00:00', 'Z'))
      if (isNaN(d.getTime())) return isoStr
      const month = (d.getMonth() + 1).toString().padStart(2, '0')
      const day = d.getDate().toString().padStart(2, '0')
      const hour = d.getHours().toString().padStart(2, '0')
      const min = d.getMinutes().toString().padStart(2, '0')
      return `${month}-${day} ${hour}:${min}`
    },
    otherCount(dist) {
      return (dist['10'] || 0) + (dist['below_10'] || 0)
    }
  }
}
</script>

<style>
.page-container {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: #0f0f23;
}

/* 加载 / 错误 / 空状态 */
.loading-box, .error-box, .empty-box {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}
.loading-text { font-size: 28rpx; color: #888; }
.error-text { font-size: 28rpx; color: #e06060; margin-bottom: 20rpx; }
.retry-btn { font-size: 26rpx; color: #4a90d9; text-decoration: underline; }
.empty-text { font-size: 28rpx; color: #888; }

/* 内容滚动区 */
.content-scroll {
  flex: 1;
  height: 0;
}
.scroll-inner {
  padding: 20rpx 24rpx 0;
}

/* 更新时间 */
.update-time {
  text-align: center;
  padding: 0 0 20rpx;
}
.update-text {
  font-size: 24rpx;
  color: #556;
}

/* 部落卡片 */
.clan-card {
  background: #1a1a2e;
  border-radius: 16rpx;
  margin-bottom: 30rpx;
  border: 1rpx solid #2a2a4a;
  overflow: visible;
  box-sizing: border-box;
  width: 100%;
}

.clan-header {
  display: flex;
  align-items: center;
  padding: 24rpx 24rpx 16rpx;
  border-bottom: 1rpx solid #2a2a4a;
}
.clan-name {
  font-size: 32rpx;
  font-weight: 600;
  color: #fff;
}
.clan-tag {
  font-size: 22rpx;
  color: #8e8eb0;
  margin-left: 8rpx;
  margin-right: 12rpx;
}
.clan-badge {
  font-size: 22rpx;
  color: #4a90d9;
  background: rgba(74, 144, 217, 0.15);
  border-radius: 8rpx;
  padding: 4rpx 14rpx;
  margin-right: 16rpx;
}
.clan-count {
  font-size: 24rpx;
  color: #8890a0;
}

/* 表格区域 */
.table-section {
  padding: 20rpx 24rpx 24rpx;
}
.table-title {
  font-size: 26rpx;
  color: #8890a0;
  margin-bottom: 16rpx;
  font-weight: 500;
}

/* 表格体容器 */
.table-body {
  background: rgba(74, 144, 217, 0.08);
  border-radius: 8rpx;
  overflow: hidden;
}

/* 行 */
.tr {
  display: flex;
  flex-direction: row;
  align-items: center;
  height: 72rpx;
  width: 100%;
}
.tr-data {
  background: rgba(255, 255, 255, 0.03);
}

/* 单元格 */
.td {
  flex-shrink: 0;
  text-align: center;
  font-size: 24rpx;
  color: #c0c0c0;
  padding: 0 4rpx;
  width: 52rpx;
  line-height: 72rpx;
}
.td-label {
  width: 64rpx;
  text-align: left;
  color: #8890a0;
  font-weight: 500;
}
.td-avg {
  flex-shrink: 0;
  width: 64rpx;
  color: #4a90d9;
  font-weight: 600;
  padding: 0 4rpx;
}

.tr-head .td {
  color: #8890a0;
  font-size: 22rpx;
}
.tr-data .td {
  color: #fff;
  font-size: 24rpx;
}

/* 无部落战 */
.no-war {
  text-align: center;
  padding: 30rpx 0;
}
.no-war-text {
  font-size: 26rpx;
  color: #666;
}

/* 底部留白 */
.bottom-space {
  height: 40rpx;
}
</style>
