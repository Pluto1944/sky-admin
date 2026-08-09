<template>
  <view class="page-container">
    <!-- 自定义顶部栏 -->
    <TopBar title="战斗" :buttons="topButtons" @onMonth="onMonth" @onRefresh="onRefresh" />

    <!-- 中间展示区域 -->
    <view class="content">
      <view class="placeholder">
        <text class="placeholder-icon">⚔️</text>
        <text class="placeholder-text">战斗页面</text>
        <text class="placeholder-desc">联赛战绩、战斗记录、排名等功能开发中</text>
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
        { key: 'refresh', icon: '🔄', text: '刷新', action: 'onRefresh' },
        { key: 'month', icon: '📅', text: '月份', action: 'onMonth' }
      ]
    }
  },
  methods: {
    onMonth() {
      uni.showToast({ title: '月份选择开发中', icon: 'none' })
    },
    onRefresh() {
      uni.showToast({ title: '刷新功能开发中', icon: 'none' })
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
