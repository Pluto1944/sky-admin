<template>
  <view class="container">
    <view class="placeholder">
      <text class="placeholder-icon">⚔️</text>
      <text class="placeholder-text">战绩详情</text>
      <text class="placeholder-desc">功能开发中</text>
    </view>
  </view>
</template>

<script>
export default {
  data() {
    return {}
  },
  onLoad(options) {
    // TODO: 根据 options.period 等参数加载战绩数据
    console.log('战绩详情页参数:', options)
  }
}
</script>

<style scoped>
.container {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #0f0f23;
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
