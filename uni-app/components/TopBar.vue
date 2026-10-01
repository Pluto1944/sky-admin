<template>
  <view class="top-bar" :style="{ paddingTop: topPadding + 'px' }">
    <view class="top-bar-content">
      <view class="top-bar-left">
        <view v-if="showBack" class="back-btn" @tap="goBack">&#8249;</view>
        <text class="title">{{ title }}</text>
      </view>
      <view class="top-bar-right">
        <text
          v-for="btn in buttons"
          :key="btn.key"
          class="top-btn"
          :class="{ active: btn.active }"
          @tap="$emit(btn.action, btn.key)"
        >{{ btn.icon }}{{ btn.text || '' }}</text>
      </view>
    </view>
  </view>
</template>

<script>
export default {
  name: 'TopBar',
  props: {
    title: { type: String, default: '' },
    showBack: { type: Boolean, default: false },
    backFallback: { type: String, default: '' },
    buttons: { type: Array, default: () => [] }
  },
  data() {
    return { topPadding: 0 }
  },
  created() {
    const info = uni.getSystemInfoSync()
    const menuButton = uni.getMenuButtonBoundingClientRect()
    // 胶囊底部到屏幕顶部的距离 = 状态栏 + 胶囊高度 + 间距
    // 让 TopBar 内容区从胶囊底部开始
    const statusBarHeight = info.statusBarHeight || 20
    const menuBottom = menuButton.bottom
    this.topPadding = menuBottom
  },
  methods: {
    goBack() {
      uni.navigateBack({
        delta: 1,
        fail: () => {
          if (this.backFallback) uni.switchTab({ url: this.backFallback })
        }
      })
    }
  }
}
</script>

<style>
.top-bar {
  width: 100%;
  background: #1a1a2e;
  border-bottom: 1rpx solid #2a2a4a;
}

.top-bar-content {
  height: 88rpx;
  padding: 0 24rpx;
  overflow: hidden;
}

.top-bar-left {
  float: left;
  height: 88rpx;
  line-height: 88rpx;
}

.back-btn {
  display: inline-flex;
  width: 72rpx;
  height: 88rpx;
  box-sizing: border-box;
  align-items: center;
  justify-content: center;
  font-size: 48rpx;
  color: #4a90d9;
  margin-left: -12rpx;
  margin-right: 4rpx;
  font-weight: 300;
  vertical-align: middle;
}

.back-btn:active {
  background: rgba(255, 255, 255, 0.1);
}

.title {
  font-size: 34rpx;
  font-weight: 600;
  color: #ffffff;
  vertical-align: middle;
}

.top-bar-right {
  float: right;
  height: 88rpx;
  line-height: 88rpx;
}

.top-btn {
  font-size: 26rpx;
  color: #c0c0c0;
  padding: 8rpx 12rpx;
  margin-left: 12rpx;
}

.top-btn:first-child {
  margin-left: 0;
}

.top-btn:active {
  background: rgba(255, 255, 255, 0.1);
}

.top-btn.active {
  color: #5fa8ff;
  background: rgba(74, 144, 217, 0.16);
  border-radius: 10rpx;
  font-weight: 600;
}
</style>
