<template>
  <view class="page">
    <TopBar title="战绩详情" :showBack="true" />
    <view class="card">
      <text class="icon">⚔️</text>
      <text class="title">战绩详情</text>
      <text class="line">月份：{{ period || '全部' }}</text>
      <text class="hint">请从战斗页进入联赛或部落战统计查看完整排名。</text>
    </view>
  </view>
</template>

<script>
import TopBar from '@/components/TopBar.vue'
export default {
  components: { TopBar },
  data() { return { period: '' } },
  onLoad(options) { this.period = options && options.period ? options.period : '' }
}
</script>

<style scoped>
.page { min-height: 100vh; background: #0f0f23; }
.card { margin: 40rpx 30rpx; padding: 46rpx 34rpx; border-radius: 20rpx; background: #1a1a3e; display: flex; flex-direction: column; align-items: center; }
.icon { font-size: 80rpx; margin-bottom: 22rpx; }
.title { color: #fff; font-size: 36rpx; font-weight: 600; margin-bottom: 30rpx; }
.line { align-self: stretch; color: #b9c0cf; font-size: 28rpx; padding: 18rpx 0; border-bottom: 1rpx solid #2a2a4a; }
.hint { color: #8890a0; font-size: 25rpx; line-height: 1.7; margin-top: 28rpx; }
</style>
