<template>
  <view class="page-container">
    <!-- 自定义顶部栏 -->
    <TopBar title="部落" :buttons="topButtons" @onFilter="onFilter" @onSearch="onSearch" @onRecord="onRecord" @onFarm="onFarm" />

    <!-- 中间展示区域 -->
    <view class="content">
      <view class="placeholder">
        <text class="placeholder-icon">🏰</text>
        <text class="placeholder-text">部落页面</text>
        <text class="placeholder-desc">成员列表、搜索筛选等功能开发中</text>
      </view>
    </view>
  </view>
</template>

<script>
import TopBar from '@/components/TopBar.vue'

export default {
  components: { TopBar },
  data() {
    return {
      topButtons: [
        { key: 'record', icon: '⚔️', text: '战绩', action: 'onRecord' },
        { key: 'farm', icon: '🔄', text: '互刷', action: 'onFarm' },
        { key: 'filter', icon: '⏬', text: '筛选', action: 'onFilter' },
        { key: 'search', icon: '🔍', text: '搜索', action: 'onSearch' }
      ]
    }
  },
  methods: {
    onRecord() {
      uni.navigateTo({ url: '/pages/clan/stats' })
    },
    onFarm() {
      uni.navigateTo({ url: '/pages/clan/farm' })
    },
    onFilter() {
      uni.showToast({ title: '筛选功能开发中', icon: 'none' })
    },
    onSearch() {
      uni.showToast({ title: '搜索功能开发中', icon: 'none' })
    }
  }
}
</script>

<style scoped>
.page-container {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: #0f0f23;
}

.content {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding-bottom: 100rpx;
}

.placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.placeholder-icon {
  font-size: 100rpx;
  margin-bottom: 30rpx;
}

.placeholder-text {
  font-size: 36rpx;
  color: #c0c0c0;
  font-weight: 600;
  margin-bottom: 12rpx;
}

.placeholder-desc {
  font-size: 24rpx;
  color: #666;
}
</style>
