<template>
  <view class="container">
    <!-- 标题 -->
    <view class="header">
      <view class="title">绑定游戏账号</view>
      <view class="desc">绑定后可使用全部功能</view>
    </view>

    <!-- 表单 -->
    <view class="form-card">
      <view class="form-item">
        <view class="label">游戏昵称</view>
        <input
          class="input"
          v-model="accountName"
          placeholder="请输入游戏内昵称"
          placeholder-style="color:#555"
          maxlength="30"
        />
      </view>

      <view class="form-item">
        <view class="label">玩家标签</view>
        <input
          class="input"
          v-model="playerTag"
          placeholder="例如：#ABC123"
          placeholder-style="color:#555"
          maxlength="15"
        />
      </view>

      <view class="form-tip">
        ⚠️ 至少填写一项，请确保信息准确
      </view>
    </view>

    <!-- 操作按钮 -->
    <view class="actions">
      <button
        class="submit-btn"
        :loading="submitting"
        :disabled="submitting || (!accountName && !playerTag)"
        @tap="handleBind"
      >
        确认绑定
      </button>
      <button class="skip-btn" @tap="handleSkip">暂不绑定，先看看</button>
    </view>
  </view>
</template>

<script>
import { bindAccount } from '@/utils/api.js'

export default {
  data() {
    return {
      accountName: '',
      playerTag: '',
      submitting: false
    }
  },
  methods: {
    handleBind() {
      // 基本校验
      const name = this.accountName.trim()
      const tag = this.playerTag.trim()

      if (!name && !tag) {
        uni.showToast({
          title: '请至少填写一项',
          icon: 'none'
        })
        return
      }

      // player_tag 格式提示
      if (tag && !tag.startsWith('#')) {
        uni.showModal({
          title: '提示',
          content: '玩家标签通常以 # 开头（如 #ABC123），确定提交吗？',
          success: (res) => {
            if (res.confirm) {
              this.doBind(name, tag)
            }
          }
        })
        return
      }

      this.doBind(name, tag)
    },

    doBind(accountName, playerTag) {
      this.submitting = true
      bindAccount(accountName || undefined, playerTag || undefined)
        .then((res) => {
          // 更新全局用户信息
          getApp().globalData.userInfo = res.user

          uni.showToast({
            title: '绑定成功',
            icon: 'success',
            duration: 1500
          })

          setTimeout(() => {
            uni.redirectTo({ url: '/pages/index/index' })
          }, 1500)
        })
        .catch((err) => {
          this.submitting = false
          uni.showModal({
            title: '绑定失败',
            content: err.message || '请稍后重试',
            showCancel: false
          })
        })
    },

    handleSkip() {
      uni.redirectTo({ url: '/pages/index/index' })
    }
  }
}
</script>

<style scoped>
.container {
  min-height: 100vh;
  padding: 60rpx 40rpx;
  background: linear-gradient(180deg, #0f0f23 0%, #1a1a3e 50%, #0f0f23 100%);
}

.header {
  text-align: center;
  margin-bottom: 60rpx;
}

.title {
  font-size: 44rpx;
  font-weight: 700;
  color: #ffffff;
  margin-bottom: 12rpx;
}

.desc {
  font-size: 26rpx;
  color: #8890a0;
}

.form-card {
  background: #1a1a2e;
  border-radius: 20rpx;
  padding: 40rpx 30rpx;
  border: 1rpx solid #2a2a4a;
  margin-bottom: 60rpx;
}

.form-item {
  margin-bottom: 36rpx;
}

.form-item:last-of-type {
  margin-bottom: 20rpx;
}

.label {
  font-size: 28rpx;
  color: #c0c0c0;
  margin-bottom: 16rpx;
  font-weight: 500;
}

.input {
  width: 100%;
  height: 88rpx;
  background: #0f0f23;
  border: 1rpx solid #2a2a4a;
  border-radius: 12rpx;
  padding: 0 24rpx;
  font-size: 30rpx;
  color: #e0e0e0;
  box-sizing: border-box;
}

.input:focus {
  border-color: #4a90d9;
}

.form-tip {
  font-size: 24rpx;
  color: #666;
  text-align: center;
  margin-top: 10rpx;
}

.actions {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 24rpx;
}

.submit-btn {
  width: 520rpx;
  height: 96rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #4a90d9, #3a7bc8);
  color: #ffffff;
  font-size: 32rpx;
  font-weight: 600;
  border-radius: 48rpx;
  border: none;
  box-shadow: 0 8rpx 24rpx rgba(74, 144, 217, 0.3);
}

.submit-btn::after {
  border: none;
}

.submit-btn[disabled] {
  opacity: 0.5;
}

.submit-btn:active {
  transform: scale(0.96);
  opacity: 0.9;
}

.skip-btn {
  background: transparent;
  color: #8890a0;
  font-size: 28rpx;
  border: none;
}

.skip-btn::after {
  border: none;
}
</style>
