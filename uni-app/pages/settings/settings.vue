<template>
  <view class="page-container">
    <!-- 自定义顶部栏 -->
    <TopBar title="管理中心" />

    <!-- 中间展示区域 -->
    <view class="content">
      <!-- 已登录 + 不在绑定流程 -->
      <view v-if="isLoggedIn && pageState === 'main'" class="management-home">
        <view class="section-heading">
          <text class="section-heading-title">微信账号</text>
          <text class="section-heading-status"><text class="status-dot"></text>已登录</text>
        </view>

        <view class="user-card">
          <view class="user-card-main">
            <view class="user-detail">
              <view class="username">{{ displayName }}</view>
              <view v-if="userInfo && (userInfo.account_name || userInfo.player_tag)" class="bound-account">
                <text class="bound-account-label">已绑定 COC 账号</text>
                <view class="bound-account-values">
                  <text v-if="userInfo.account_name" class="user-chip">{{ userInfo.account_name }}</text>
                  <text v-if="userInfo.player_tag" class="user-chip user-chip-muted">{{ userInfo.player_tag }}</text>
                </view>
              </view>
              <text v-else class="user-empty">暂未绑定 COC 账号</text>
            </view>
          </view>
          <view v-if="userInfo && userInfo.openid" class="account-id-row">
            <view class="account-id-copy">
              <text class="account-id-label">账号标识</text>
              <text class="account-id-tip">仅用于运营方核对身份</text>
            </view>
            <button class="openid-copy" size="mini" @tap="copyOpenId">复制</button>
          </view>
        </view>

        <view class="section-heading">
          <text class="section-heading-title">互刷系统</text>
          <text class="farm-system-account">独立账号</text>
        </view>

        <view class="farm-system-entry">
          <text class="farm-system-title">互刷联盟系统</text>
          <text class="farm-system-desc">查看开战时间、匹配结果与积分</text>
          <button class="farm-system-btn" @tap="openFarmSystem">
            <text>进入系统</text><text class="farm-system-arrow">→</text>
          </button>
        </view>

        <!-- 其他管理 -->
        <view class="menu-section">
          <view class="menu-title">其他管理</view>
          <view class="menu-list">
            <view v-if="canManageAlliance" class="menu-item" @tap="openCwlSettings">
              <view class="menu-icon menu-icon-league">赛</view>
              <view class="menu-copy">
                <text class="menu-text">联赛设置</text>
                <text class="menu-desc">配置本月和下月的联赛队伍</text>
              </view>
              <text class="menu-arrow">›</text>
            </view>
            <view v-if="canManageAlliance" class="menu-divider"></view>
            <view class="menu-item" @tap="pageState = 'bind'">
              <view class="menu-icon menu-icon-account">号</view>
              <view class="menu-copy">
                <text class="menu-text">游戏账号</text>
                <text class="menu-desc">绑定或修改 COC 玩家账号</text>
              </view>
              <text class="menu-arrow">›</text>
            </view>
            <view class="menu-divider"></view>
            <view class="menu-item" @tap="showAbout">
              <view class="menu-icon menu-icon-about">i</view>
              <view class="menu-copy">
                <text class="menu-text">关于与版本</text>
                <text class="menu-desc">服务状态、版本与应用信息</text>
              </view>
              <text class="menu-arrow">›</text>
            </view>
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
          :disabled="loginLoading || !privacyAgreed"
          @tap="handleLogin"
        >
          <text class="wechat-icon">💬</text>
          <text>微信一键登录</text>
        </button>

        <view class="login-tip" v-if="!loginLoading">首次登录将创建账号（需先同意协议）</view>
        <view class="login-tip loading-text" v-else>正在登录中...</view>

        <view class="privacy-row" @tap="togglePrivacy">
          <text class="checkbox-mark">{{ privacyAgreed ? '☑' : '□' }}</text>
          <text>我已阅读并同意</text>
          <text class="privacy-link" @tap.stop="openUserAgreement">《用户协议》</text>
          <text>和</text>
          <text class="privacy-link" @tap.stop="openPrivacyPolicy">《隐私政策》</text>
        </view>
        <view class="privacy-note">未同意前不会调用微信登录或创建账号</view>

        <view class="farm-system-entry farm-system-entry-login">
          <text class="farm-system-badge">独立账号</text>
          <text class="farm-system-title">互刷联盟系统</text>
          <text class="farm-system-desc">查看开战时间、匹配结果与积分</text>
          <button class="farm-system-btn" @tap="openFarmSystem">
            <text>进入系统</text><text class="farm-system-arrow">→</text>
          </button>
        </view>
      </view>
    </view>
  </view>
</template>

<script>
import TopBar from '@/components/TopBar.vue'
import { wechatLogin, getMyInfo, bindAccount, getServerInfo, getSystemVersion } from '@/utils/api.js'
import { clearAllianceContext, getCurrentAlliance, loadAllianceContext } from '@/utils/alliance.js'
import { APP_VERSION } from '@/config/release.js'

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
      bindSubmitting: false,
      privacyAgreed: false
    }
  },
  computed: {
    canManageAlliance() {
      const alliance = getCurrentAlliance()
      return alliance && ['admin', 'leader'].indexOf(alliance.role) >= 0
    },
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
    openCwlSettings() {
      uni.navigateTo({ url: '/pages/settings/cwl-settings' })
    },
    refreshLoginState() {
      const token = uni.getStorageSync('token')
      const consented = uni.getStorageSync('privacyConsent') === 'v1'
      this.privacyAgreed = consented
      if (token && consented) {
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
      if (!this.privacyAgreed) {
        uni.showToast({ title: '请先阅读并同意用户协议和隐私政策', icon: 'none' })
        return
      }
      this.loginLoading = true

      uni.login({
        provider: 'weixin',
        success: (loginRes) => {
          wechatLogin(loginRes.code)
            .then((res) => {
              uni.setStorageSync('token', res.token)
              uni.setStorageSync('privacyConsent', 'v1')
              this.isLoggedIn = true
              this.userInfo = res.user
              getApp().globalData.isLoggedIn = true
              getApp().globalData.userInfo = res.user
              loadAllianceContext(null, true).catch(() => {})
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

    togglePrivacy() {
      this.privacyAgreed = !this.privacyAgreed
    },
    openUserAgreement() {
      uni.navigateTo({ url: '/pages/legal/user-agreement' })
    },
    openPrivacyPolicy() {
      uni.navigateTo({ url: '/pages/legal/privacy-policy' })
    },

    openFarmSystem() {
      uni.showToast({ title: '互刷系统暂未开放', icon: 'none' })
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

    copyOpenId() {
      const openid = this.userInfo && this.userInfo.openid
      if (!openid) {
        uni.showToast({ title: '暂未获取到 OpenID', icon: 'none' })
        return
      }
      uni.setClipboardData({
        data: openid,
        success: () => {
          uni.showToast({ title: 'OpenID 已复制', icon: 'success' })
        },
        fail: () => {
          uni.showToast({ title: '复制失败，请稍后重试', icon: 'none' })
        }
      })
    },

    async showAbout() {
      let serverVersion = '获取失败'
      let serviceStatus = '暂不可用'
      let details = ''
      try {
        const systemInfo = await getSystemVersion()
        serverVersion = systemInfo.release_version || '未知'
        if (!systemInfo.healthy) {
          serviceStatus = '调度器异常'
        } else if (!systemInfo.consistent) {
          serviceStatus = '运行中，组件版本不一致'
        } else {
          serviceStatus = '正常'
        }
        if (this.userInfo && this.userInfo.role === 'admin') {
          const components = systemInfo.components || {}
          details = `\n\n运行详情（管理员）\n${this.runtimeLine('API', components.api)}\n${this.runtimeLine('调度器', components.scheduler)}`
        }
      } catch (err) {
        try {
          const serverInfo = await getServerInfo()
          serverVersion = serverInfo.version || '未知'
          serviceStatus = 'API 正常，调度器状态未知'
        } catch (pingErr) {
          // “关于”信息应保持可查看，服务暂不可达只影响版本核对。
        }
      }
      uni.showModal({
        title: '苍穹联赛助手',
        content: `小程序版本：${APP_VERSION}\n服务版本：${serverVersion}\n服务状态：${serviceStatus}${details}\n\nCOC 部落冲突联赛管理工具\n提供成员管理、联赛战绩查看等功能`,
        showCancel: false,
        confirmText: '知道了'
      })
    },

    runtimeLine(label, component) {
      if (!component || component.health === 'missing') return `${label}：未上报`
      const commit = component.git_commit && component.git_commit !== 'unknown'
        ? component.git_commit.slice(0, 8)
        : '未知提交'
      const health = component.health === 'healthy' ? '正常' : '心跳超时'
      const dirty = component.tracked_dirty ? ' · 有未提交改动' : ''
      return `${label}：${component.release_version || '未知'} · ${commit} · ${health}${dirty}`
    },

    handleLogout() {
      uni.showModal({
        title: '退出登录',
        content: '确定要退出登录吗？',
        success: (res) => {
          if (res.confirm) {
            uni.removeStorageSync('token')
            clearAllianceContext()
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

<style>
.page-container {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: #0f0f23;
}

.content {
  flex: 1;
  padding: 28rpx 28rpx 100rpx;
  box-sizing: border-box;
}

/* ====== 已登录 - 主页面 ====== */

.management-home {
  width: 100%;
}

.section-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 0 4rpx 16rpx;
}

.section-heading-title {
  color: #8f99ad;
  font-size: 23rpx;
  font-weight: 500;
  letter-spacing: 2rpx;
}

.section-heading-status {
  display: flex;
  align-items: center;
  color: #728098;
  font-size: 21rpx;
}

.status-dot {
  width: 10rpx;
  height: 10rpx;
  margin-right: 8rpx;
  background: #42c98b;
  border-radius: 50%;
}

.user-card {
  padding: 30rpx 28rpx 0;
  margin-bottom: 24rpx;
  overflow: hidden;
  background: linear-gradient(145deg, #1b1d38, #17182f);
  border: 1rpx solid #2d3153;
  border-radius: 18rpx;
  box-shadow: 0 10rpx 30rpx rgba(0, 0, 0, 0.14);
}

.user-card-main {
  display: flex;
  align-items: center;
  min-height: 84rpx;
  padding-bottom: 28rpx;
}

.user-detail {
  flex: 1;
}

.username {
  margin-bottom: 12rpx;
  color: #f3f5fb;
  font-size: 32rpx;
  font-weight: 600;
}

.bound-account-values {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
}

.bound-account-label {
  display: block;
  margin-bottom: 9rpx;
  color: #737f95;
  font-size: 20rpx;
  line-height: 1.2;
}

.user-chip {
  padding: 5rpx 12rpx;
  margin: 0 10rpx 6rpx 0;
  color: #aecff4;
  background: rgba(74, 144, 217, 0.13);
  border-radius: 8rpx;
  font-size: 21rpx;
}

.user-chip-muted {
  color: #8b96aa;
  background: rgba(139, 150, 170, 0.1);
}

.user-empty {
  color: #737d91;
  font-size: 22rpx;
}

.account-id-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 88rpx;
  margin: 0 -28rpx;
  padding: 0 28rpx;
  background: rgba(10, 11, 27, 0.34);
  border-top: 1rpx solid #292d4b;
}

.account-id-copy {
  min-width: 0;
  flex: 1;
}

.account-id-label {
  display: block;
  color: #aab3c5;
  font-size: 23rpx;
  font-weight: 500;
}

.account-id-tip {
  display: block;
  margin-top: 4rpx;
  color: #636d82;
  font-size: 19rpx;
}

.openid-copy {
  flex-shrink: 0;
  margin: 0;
  padding: 0 24rpx;
  color: #92c6ff;
  background: transparent;
  border: 1rpx solid #385072;
  border-radius: 22rpx;
  font-size: 21rpx;
  line-height: 44rpx;
}

.openid-copy::after {
  border: 0;
}

.farm-system-entry {
  padding: 30rpx 28rpx 28rpx;
  margin-bottom: 28rpx;
  overflow: hidden;
  background: linear-gradient(145deg, #1b1d38, #17182f);
  border: 1rpx solid #2d3153;
  border-radius: 18rpx;
  box-shadow: 0 10rpx 30rpx rgba(0, 0, 0, 0.14);
  box-sizing: border-box;
}

.farm-system-entry-login {
  width: 100%;
  margin-top: 44rpx;
  margin-bottom: 0;
  text-align: left;
}

.farm-system-account {
  padding: 4rpx 13rpx;
  color: #7fa8d4;
  background: rgba(74, 144, 217, 0.08);
  border: 1rpx solid rgba(94, 151, 207, 0.22);
  border-radius: 18rpx;
  font-size: 19rpx;
}

.farm-system-badge {
  display: inline-block;
  padding: 5rpx 14rpx;
  margin-bottom: 18rpx;
  color: #90bde9;
  background: rgba(79, 143, 207, 0.12);
  border: 1rpx solid rgba(124, 181, 237, 0.22);
  border-radius: 18rpx;
  font-size: 20rpx;
}

.farm-system-title,
.farm-system-desc {
  display: block;
}

.farm-system-title {
  color: #e8f1ff;
  font-size: 32rpx;
  font-weight: 600;
}

.farm-system-desc {
  margin-top: 10rpx;
  color: #8d9bb1;
  font-size: 23rpx;
  line-height: 1.6;
}

.farm-system-btn {
  width: 100%;
  height: 72rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 26rpx 0 0;
  padding: 0 28rpx;
  color: #f5f9ff;
  background: linear-gradient(135deg, #397fc2, #2d65a1);
  border: 0;
  border-radius: 12rpx;
  font-size: 26rpx;
  font-weight: 600;
  line-height: 72rpx;
}

.farm-system-arrow {
  margin-left: 14rpx;
  color: #cfe5ff;
  font-size: 27rpx;
}

.farm-system-btn::after {
  border: 0;
}

/* 菜单 */
.menu-section {
  margin-bottom: 18rpx;
}

.menu-title {
  padding: 0 4rpx 16rpx;
  color: #788398;
  font-size: 22rpx;
  font-weight: 500;
  letter-spacing: 2rpx;
}

.menu-list {
  overflow: hidden;
  background: #18192f;
  border: 1rpx solid #292d4c;
  border-radius: 16rpx;
}

.menu-item {
  display: flex;
  align-items: center;
  min-height: 102rpx;
  padding: 0 24rpx;
}

.menu-icon {
  width: 52rpx;
  height: 52rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-right: 18rpx;
  border-radius: 14rpx;
  font-size: 23rpx;
  font-weight: 700;
}

.menu-icon-account {
  color: #9bc6f2;
  background: rgba(74, 144, 217, 0.16);
}

.menu-icon-about {
  color: #b8acd9;
  background: rgba(147, 112, 219, 0.15);
}

.menu-copy {
  min-width: 0;
  flex: 1;
}

.menu-text {
  display: block;
  color: #dce0ea;
  font-size: 27rpx;
  font-weight: 500;
}

.menu-desc {
  display: block;
  margin-top: 5rpx;
  color: #687287;
  font-size: 20rpx;
}

.menu-arrow {
  margin-left: 18rpx;
  color: #565f73;
  font-size: 34rpx;
  font-weight: 300;
}

.menu-divider {
  height: 1rpx;
  margin-left: 94rpx;
  background: #292d49;
}

/* 退出 */
.logout-section {
  padding: 28rpx 0 12rpx;
  text-align: center;
}

.logout-btn {
  width: 280rpx;
  height: 68rpx;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  color: #a66b70;
  font-size: 24rpx;
  border: 1rpx solid rgba(184, 92, 99, 0.22);
  border-radius: 34rpx;
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

.privacy-row { display: flex; align-items: center; justify-content: center; flex-wrap: wrap; margin-top: 30rpx; color: #9aa0b0; font-size: 23rpx; line-height: 42rpx; }
.checkbox-mark { color: #4a90d9; font-size: 34rpx; margin-right: 8rpx; }
.privacy-link { color: #5fa8ff; padding: 0 4rpx; }
.privacy-note { display: block; text-align: center; color: #666; font-size: 20rpx; margin-top: 10rpx; }
</style>
