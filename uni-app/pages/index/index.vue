<template>
  <view class="container">
    <!-- 用户卡片 -->
    <view class="user-card" v-if="userInfo">
      <view class="avatar">👤</view>
      <view class="user-detail">
        <view class="username">{{ displayName }}</view>
        <view class="user-meta">
          <text v-if="userInfo.account_name">🎮 {{ userInfo.account_name }}</text>
          <text v-if="userInfo.player_tag">🏷️ {{ userInfo.player_tag }}</text>
        </view>
        <view class="user-role">
          <text class="role-badge" :class="userInfo.role">{{ roleText }}</text>
        </view>
      </view>
    </view>

    <!-- 功能入口 -->
    <view class="menu-section">
      <view class="menu-title">功能</view>

      <view class="menu-item" @tap="goMembers">
        <text class="menu-icon">👥</text>
        <text class="menu-text">成员列表</text>
        <text class="menu-arrow">›</text>
      </view>

      <view class="menu-item" @tap="goBind">
        <text class="menu-icon">🔗</text>
        <text class="menu-text">绑定/修改游戏账号</text>
        <text class="menu-arrow">›</text>
      </view>
    </view>

    <!-- 退出登录 -->
    <view class="logout-section">
      <button class="logout-btn" @tap="handleLogout">退出登录</button>
    </view>

    <!-- 未登录状态 -->
    <view class="empty" v-if="!userInfo">
      <text class="empty-text">请先登录</text>
      <button class="go-login-btn" @tap="goLogin">去登录</button>
    </view>
  </view>
</template>

<script>
import { getMyInfo } from '@/utils/api.js'

export default {
  data() {
    return {
      userInfo: null,
      loading: true
    }
  },
  computed: {
    displayName() {
      if (this.userInfo && this.userInfo.nickname) {
        return this.userInfo.nickname
      }
      return '微信用户'
    },
    roleText() {
      if (!this.userInfo) return ''
      const map = {
        admin: '管理员',
        member: '成员',
        moderator: '审核员'
      }
      return map[this.userInfo.role] || this.userInfo.role
    }
  },
  onShow() {
    this.loadUserInfo()
  },
  methods: {
    loadUserInfo() {
      const token = uni.getStorageSync('token')
      if (!token) {
        this.userInfo = null
        this.loading = false
        return
      }

      getMyInfo()
        .then((res) => {
          this.userInfo = res
          getApp().globalData.userInfo = res
          getApp().globalData.isLoggedIn = true
          this.loading = false
        })
        .catch((err) => {
          console.error('获取用户信息失败:', err)
          this.userInfo = null
          this.loading = false
        })
    },

    goMembers() {
      // TODO: 后续实现成员列表页
      uni.showToast({
        title: '功能开发中',
        icon: 'none'
      })
    },

    goBind() {
      uni.navigateTo({ url: '/pages/bind/bind' })
    },

    goLogin() {
      uni.reLaunch({ url: '/pages/login/login' })
    },

    handleLogout() {
      uni.showModal({
        title: '退出登录',
        content: '确定要退出登录吗？',
        success: (res) => {
          if (res.confirm) {
            uni.removeStorageSync('token')
            getApp().globalData.isLoggedIn = false
            getApp().globalData.userInfo = null
            uni.reLaunch({ url: '/pages/login/login' })
          }
        }
      })
    }
  }
}
</script>

<style scoped>
.container {
  min-height: 100vh;
  padding: 30rpx 30rpx;
  background-color: #0f0f23;
}

/* 用户卡片 */
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
  margin-bottom: 12rpx;
}

.user-role {
  display: flex;
}

.role-badge {
  font-size: 22rpx;
  padding: 4rpx 16rpx;
  border-radius: 8rpx;
  background: #252545;
  color: #8890a0;
}

.role-badge.admin {
  background: rgba(74, 144, 217, 0.2);
  color: #4a90d9;
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

/* 空状态 */
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding-top: 300rpx;
}

.empty-text {
  font-size: 32rpx;
  color: #666;
  margin-bottom: 40rpx;
}

.go-login-btn {
  width: 400rpx;
  height: 88rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #4a90d9, #3a7bc8);
  color: #ffffff;
  font-size: 30rpx;
  font-weight: 600;
  border-radius: 44rpx;
  border: none;
}

.go-login-btn::after {
  border: none;
}
</style>
