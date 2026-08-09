<template>
  <view class="page-container">
    <!-- 自定义顶部栏 -->
    <TopBar title="设置" />

    <!-- 中间展示区域 -->
    <view class="content">
      <!-- 已登录 + 不在绑定流程 -->
      <view v-if="isLoggedIn && pageState === 'main'">
        <!-- 用户信息 -->
        <view class="user-card">
          <view class="avatar">👤</view>
          <view class="user-detail">
            <view class="username">{{ displayName }}</view>
            <view class="user-meta">
              <text v-if="userInfo && userInfo.account_name">🎮 {{ userInfo.account_name }}</text>
              <text v-if="userInfo && userInfo.player_tag">🏷️ {{ userInfo.player_tag }}</text>
            </view>
          </view>
        </view>

        <!-- 设置项 -->
        <view class="menu-section">
          <view class="menu-title">账号</view>
          <view class="menu-item" @tap="pageState = 'bind'">
            <text class="menu-icon">🔗</text>
            <text class="menu-text">绑定/修改游戏账号</text>
            <text class="menu-arrow">›</text>
          </view>
        </view>

        <!-- 关于 -->
        <view class="menu-section">
          <view class="menu-title">关于</view>
          <view class="menu-item" @tap="showAbout">
            <text class="menu-icon">ℹ️</text>
            <text class="menu-text">关于苍穹联赛助手</text>
            <text class="menu-arrow">›</text>
          </view>
        </view>

        <!-- 退出登录 -->
        <view class="logout-section">
          <button class="logout-btn" @tap="handleLogout">退出登录</button>
        </view>
      </view>

      <!-- 绑定/修改游戏账号（页面内状态） -->
      <view v-else-if="isLoggedIn && pageState === 'bind'" class="bind-page">
        <view class="bind-header">
          <text class="bind-title">绑定游戏账号</text>
          <text class="bind-desc">绑定后可使用全部功能</text>
        </view>

        <view class="form-card">
          <view class="form-item">
            <view class="label">游戏昵称</view>
            <input
              class="input"
              v-model="bindAccountName"
              placeholder="请输入游戏内昵称"
              placeholder-style="color:#555"
              maxlength="30"
            />
          </view>
          <view class="form-item">
            <view class="label">玩家标签</view>
            <input
              class="input"
              v-model="bindPlayerTag"
              placeholder="例如：#ABC123"
              placeholder-style="color:#555"
              maxlength="15"
            />
          </view>
          <view class="form-tip">
            ⚠️ 至少填写一项，请确保信息准确
          </view>
        </view>

        <view class="bind-actions">
          <button
            class="submit-btn"
            :loading="bindSubmitting"
            :disabled="bindSubmitting || (!bindAccountName && !bindPlayerTag)"
            @tap="handleBind"
          >
            确认绑定
          </button>
          <button class="skip-btn" @tap="pageState = 'main'">返回</button>
        </view>
      </view>

      <!-- 未登录状态 -->
      <view v-else class="login-section">
        <view class="logo-area">
          <view class="logo">⚔️</view>
          <view class="app-name">苍穹联赛助手</view>
          <view class="subtitle">COC 部落冲突 · 联赛管理</view>
        </view>

        <button
          class="login-btn"
          :loading="loginLoading"
          :disabled="loginLoading"
          @tap="handleLogin"
        >
          <text class="wechat-icon">💬</text>
          <text>微信一键登录</text>
        </button>

        <view class="login-tip" v-if="!loginLoading">首次登录自动注册账号</view>
        <view class="login-tip loading-text" v-else>正在登录中...</view>

        <view class="footer-text">登录即表示同意《用户协议》和《隐私政策》</view>
      </view>
    </view>
  </view>
</template>

<script>
import TopBar from '@/components/TopBar.vue'
import { wechatLogin, getMyInfo, bindAccount } from '@/utils/api.js'

export default {
  components: { TopBar },
  data() {
    return {
      pageState: 'main',      // 'main' | 'bind'
      loginLoading: false,
      isLoggedIn: false,
      userInfo: null,
      // 绑定表单
      bindAccountName: '',
      bindPlayerTag: '',
      bindSubmitting: false
    }
  },
  computed: {
    displayName() {
      if (this.userInfo && this.userInfo.nickname) {
        return this.userInfo.nickname
      }
      return '微信用户'
    }
  },
  onShow() {
    this.refreshLoginState()
  },
  methods: {
    refreshLoginState() {
      const token = uni.getStorageSync('token')
      if (token) {
        getMyInfo()
          .then((res) => {
            this.isLoggedIn = true
            this.userInfo = res
            getApp().globalData.userInfo = res
            getApp().globalData.isLoggedIn = true
            // 预填已有信息
            if (res.account_name) this.bindAccountName = res.account_name
            if (res.player_tag) this.bindPlayerTag = res.player_tag
          })
          .catch(() => {
            this.isLoggedIn = false
            this.userInfo = null
            getApp().globalData.isLoggedIn = false
          })
      } else {
        this.isLoggedIn = false
        this.userInfo = null
        getApp().globalData.isLoggedIn = false
        getApp().globalData.userInfo = null
      }
    },

    // ====== 登录 ======
    handleLogin() {
      this.loginLoading = true

      uni.login({
        provider: 'weixin',
        success: (loginRes) => {
          wechatLogin(loginRes.code)
            .then((res) => {
              uni.setStorageSync('token', res.token)
              this.isLoggedIn = true
              this.userInfo = res.user
              getApp().globalData.isLoggedIn = true
              getApp().globalData.userInfo = res.user
              this.loginLoading = false

              uni.showToast({ title: '登录成功', icon: 'success', duration: 1500 })

              // 未绑定则自动进入绑定流程
              if (res.user && !res.user.account_name && !res.user.player_tag) {
                setTimeout(() => { this.pageState = 'bind' }, 1500)
              }
            })
            .catch((err) => {
              this.loginLoading = false
              uni.showModal({
                title: '登录失败',
                content: err.message || '请稍后重试',
                showCancel: false
              })
            })
        },
        fail: (err) => {
          this.loginLoading = false
          console.error('wx.login 失败:', err)
          uni.showModal({
            title: '登录失败',
            content: '微信登录接口调用失败，请确保在微信小程序环境中运行',
            showCancel: false
          })
        }
      })
    },

    // ====== 绑定 ======
    handleBind() {
      const name = this.bindAccountName.trim()
      const tag = this.bindPlayerTag.trim()

      if (!name && !tag) {
        uni.showToast({ title: '请至少填写一项', icon: 'none' })
        return
      }

      if (tag && !tag.startsWith('#')) {
        uni.showModal({
          title: '提示',
          content: '玩家标签通常以 # 开头（如 #ABC123），确定提交吗？',
          success: (res) => {
            if (res.confirm) this.doBind(name, tag)
          }
        })
        return
      }

      this.doBind(name, tag)
    },

    doBind(accountName, playerTag) {
      this.bindSubmitting = true
      bindAccount(accountName || undefined, playerTag || undefined)
        .then((res) => {
          this.userInfo = res.user
          getApp().globalData.userInfo = res.user
          this.bindSubmitting = false

          uni.showToast({ title: '绑定成功', icon: 'success', duration: 1500 })
          setTimeout(() => { this.pageState = 'main' }, 1500)
        })
        .catch((err) => {
          this.bindSubmitting = false
          uni.showModal({
            title: '绑定失败',
            content: err.message || '请稍后重试',
            showCancel: false
          })
        })
    },

    showAbout() {
      uni.showModal({
        title: '苍穹联赛助手',
        content: '版本 1.0.0\n\nCOC 部落冲突联赛管理工具\n提供成员管理、联赛战绩查看等功能',
        showCancel: false,
        confirmText: '知道了'
      })
    },

    handleLogout() {
      uni.showModal({
        title: '退出登录',
        content: '确定要退出登录吗？',
        success: (res) => {
          if (res.confirm) {
            uni.removeStorageSync('token')
            this.isLoggedIn = false
            this.userInfo = null
            getApp().globalData.isLoggedIn = false
            getApp().globalData.userInfo = null
            this.pageState = 'main'
            this.bindAccountName = ''
            this.bindPlayerTag = ''
          }
        }
      })
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
  padding: 30rpx 30rpx;
  padding-bottom: 100rpx;
}

/* ====== 已登录 - 主页面 ====== */

.user-card {
  display: flex;
  align-items: center;
  background: linear-gradient(135deg, #1a1a3e, #1e1e40);
  border: 1rpx solid #2a2a4a;
  border-radius: 20rpx;
  padding: 40rpx 30rpx;
  margin-bottom: 30rpx;
}

.avatar {
  width: 100rpx;
  height: 100rpx;
  background: #252545;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 50rpx;
  margin-right: 24rpx;
  flex-shrink: 0;
}

.user-detail {
  flex: 1;
}

.username {
  font-size: 36rpx;
  font-weight: 600;
  color: #ffffff;
  margin-bottom: 8rpx;
}

.user-meta {
  font-size: 24rpx;
  color: #8890a0;
  display: flex;
  flex-wrap: wrap;
  gap: 16rpx;
}

/* 菜单 */
.menu-section {
  margin-bottom: 30rpx;
}

.menu-title {
  font-size: 24rpx;
  color: #666;
  padding: 0 10rpx 16rpx;
  text-transform: uppercase;
  letter-spacing: 2rpx;
}

.menu-item {
  display: flex;
  align-items: center;
  background: #1a1a2e;
  border: 1rpx solid #2a2a4a;
  padding: 30rpx 24rpx;
  margin-bottom: 2rpx;
}

.menu-item:first-of-type {
  border-radius: 16rpx 16rpx 0 0;
}

.menu-item:last-of-type {
  border-radius: 0 0 16rpx 16rpx;
  margin-bottom: 0;
}

.menu-item:only-of-type {
  border-radius: 16rpx;
}

.menu-icon {
  font-size: 36rpx;
  margin-right: 20rpx;
}

.menu-text {
  flex: 1;
  font-size: 30rpx;
  color: #e0e0e0;
}

.menu-arrow {
  font-size: 32rpx;
  color: #555;
  font-weight: 300;
}

/* 退出 */
.logout-section {
  padding: 40rpx 0;
  text-align: center;
}

.logout-btn {
  width: 400rpx;
  height: 80rpx;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  color: #d9534f;
  font-size: 28rpx;
  border: 1rpx solid rgba(217, 83, 79, 0.3);
  border-radius: 40rpx;
}

.logout-btn::after {
  border: none;
}

/* ====== 已登录 - 绑定页 ====== */

.bind-page {
  padding-top: 20rpx;
}

.bind-header {
  text-align: center;
  margin-bottom: 40rpx;
}

.bind-title {
  font-size: 40rpx;
  font-weight: 700;
  color: #ffffff;
  display: block;
  margin-bottom: 10rpx;
}

.bind-desc {
  font-size: 26rpx;
  color: #8890a0;
}

.form-card {
  background: #1a1a2e;
  border-radius: 20rpx;
  padding: 40rpx 30rpx;
  border: 1rpx solid #2a2a4a;
  margin-bottom: 40rpx;
}

.form-item {
  margin-bottom: 30rpx;
}

.form-item:last-of-type {
  margin-bottom: 16rpx;
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
  margin-top: 6rpx;
}

.bind-actions {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 20rpx;
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

.skip-btn {
  background: transparent;
  color: #8890a0;
  font-size: 28rpx;
  border: none;
}

.skip-btn::after {
  border: none;
}

/* ====== 未登录状态 ====== */

.login-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-top: 200rpx;
}

.logo-area {
  display: flex;
  flex-direction: column;
  align-items: center;
  margin-bottom: 80rpx;
}

.logo {
  font-size: 120rpx;
  margin-bottom: 20rpx;
  filter: drop-shadow(0 0 20rpx rgba(74, 144, 217, 0.5));
}

.app-name {
  font-size: 44rpx;
  font-weight: 700;
  color: #ffffff;
  letter-spacing: 4rpx;
  margin-bottom: 10rpx;
}

.subtitle {
  font-size: 24rpx;
  color: #8890a0;
  letter-spacing: 2rpx;
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

.footer-text {
  position: absolute;
  bottom: 120rpx;
  font-size: 22rpx;
  color: #555;
}
</style>
