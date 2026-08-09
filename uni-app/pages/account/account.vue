<template>
  <view class="page-container">
    <!-- 自定义顶部栏 -->
    <TopBar title="账号" :buttons="topButtons" @onEdit="onEdit" />

    <!-- 中间展示区域 -->
    <view class="content">
      <!-- 已登录：用户信息卡片 -->
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

      <!-- 未登录 -->
      <view class="placeholder" v-else>
        <text class="placeholder-icon">👤</text>
        <text class="placeholder-text">暂未登录</text>
        <text class="placeholder-desc">请前往「设置」页登录</text>
      </view>
    </view>
  </view>
</template>

<script>
import TopBar from '@/components/TopBar.vue'
import { getMyInfo } from '@/utils/api.js'

export default {
  components: { TopBar },
  data() {
    return {
      userInfo: null,
      topButtons: [
        { key: 'edit', icon: '✏️', text: '编辑', action: 'onEdit' }
      ]
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
        return
      }

      getMyInfo()
        .then((res) => {
          this.userInfo = res
          getApp().globalData.userInfo = res
          getApp().globalData.isLoggedIn = true
        })
        .catch(() => {
          this.userInfo = null
        })
    },
    onEdit() {
      uni.navigateTo({ url: '/pages/bind/bind' })
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

/* 用户卡片 */
.user-card {
  display: flex;
  align-items: center;
  background: linear-gradient(135deg, #1a1a3e, #1e1e40);
  border: 1rpx solid #2a2a4a;
  border-radius: 20rpx;
  padding: 40rpx 30rpx;
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

/* 未登录占位 */
.placeholder {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-top: 300rpx;
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
