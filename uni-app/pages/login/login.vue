<template>
  <view class="container">
    <!-- 头部 Logo 区域 -->
    <view class="header">
      <view class="logo">⚔️</view>
      <view class="app-name">苍穹联赛助手</view>
      <view class="subtitle">COC 部落冲突 · 联赛管理</view>
    </view>

    <!-- 登录按钮 -->
    <view class="login-section">
      <button
        class="login-btn"
        :loading="loading"
        :disabled="loading"
        @tap="handleLogin"
      >
        <text class="wechat-icon">💬</text>
        <text>微信一键登录</text>
      </button>
      <view class="login-tip" v-if="!loading">
        首次登录自动注册账号
      </view>
      <view class="login-tip loading-text" v-else>
        正在登录中...
      </view>
    </view>

    <!-- 底部说明 -->
    <view class="footer">
      <text class="footer-text">登录即表示同意《用户协议》和《隐私政策》</text>
    </view>
  </view>
</template>

<script>
import { wechatLogin } from '@/utils/api.js'

export default {
  data() {
    return {
      loading: false
    }
  },
  methods: {
    handleLogin() {
      this.loading = true

      // 1. 调用微信登录获取 code
      uni.login({
        provider: 'weixin',
        success: (loginRes) => {
          const code = loginRes.code

          // 2. 用 code 换后端 token
          wechatLogin(code)
            .then((res) => {
              // 3. 存储 token 和用户信息
              uni.setStorageSync('token', res.token)
              getApp().globalData.isLoggedIn = true
              getApp().globalData.userInfo = res.user

              uni.showToast({
                title: '登录成功',
                icon: 'success',
                duration: 1500
              })

              // 4. 判断是否需要绑定账号
              setTimeout(() => {
                if (res.user && !res.user.account_name && !res.user.player_tag) {
                  // 未绑定，跳转绑定页
                  uni.redirectTo({ url: '/pages/bind/bind' })
                } else {
                  // 已绑定，跳转首页
                  uni.redirectTo({ url: '/pages/index/index' })
                }
              }, 1500)
            })
            .catch((err) => {
              this.loading = false
              uni.showModal({
                title: '登录失败',
                content: err.message || '请稍后重试',
                showCancel: false
              })
            })
        },
        fail: (err) => {
          this.loading = false
          console.error('wx.login 失败:', err)
          uni.showModal({
            title: '登录失败',
            content: '微信登录接口调用失败，请确保在微信小程序环境中运行',
            showCancel: false
          })
        }
      })
    }
  }
}
</script>

<style scoped>
.container {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60rpx 40rpx;
  background: linear-gradient(180deg, #0f0f23 0%, #1a1a3e 50%, #0f0f23 100%);
}

.header {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-bottom: 120rpx;
}

.logo {
  font-size: 120rpx;
  margin-bottom: 30rpx;
  filter: drop-shadow(0 0 20rpx rgba(74, 144, 217, 0.5));
}

.app-name {
  font-size: 48rpx;
  font-weight: 700;
  color: #ffffff;
  letter-spacing: 4rpx;
  margin-bottom: 12rpx;
}

.subtitle {
  font-size: 26rpx;
  color: #8890a0;
  letter-spacing: 2rpx;
}

.login-section {
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
}

.login-btn {
  width: 520rpx;
  height: 96rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #07c160, #06ad56);
  color: #ffffff;
  font-size: 32rpx;
  font-weight: 600;
  border-radius: 48rpx;
  border: none;
  box-shadow: 0 8rpx 24rpx rgba(7, 193, 96, 0.35);
  transition: all 0.3s ease;
}

.login-btn::after {
  border: none;
}

.login-btn:active {
  transform: scale(0.96);
  opacity: 0.9;
}

.wechat-icon {
  margin-right: 12rpx;
  font-size: 36rpx;
}

.login-tip {
  margin-top: 24rpx;
  font-size: 24rpx;
  color: #666;
}

.loading-text {
  color: #8890a0;
}

.footer {
  position: absolute;
  bottom: 80rpx;
}

.footer-text {
  font-size: 22rpx;
  color: #555;
}
</style>
