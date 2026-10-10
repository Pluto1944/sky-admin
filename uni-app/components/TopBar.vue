<template>
  <view class="top-bar" :style="{ paddingTop: topPadding + 'px' }">
    <view class="alliance-switch" :style="allianceButtonStyle" @tap="openAlliancePicker">
      <text class="alliance-switch-name">{{ allianceButtonLabel }}</text>
      <text class="alliance-switch-arrow">⌄</text>
    </view>
    <view class="top-bar-content">
      <view class="top-bar-left">
        <view v-if="showBack" class="back-btn" @tap="goBack">&#8249;</view>
        <text class="title">{{ title }}</text>
      </view>
      <view class="top-bar-right">
        <view
          v-for="btn in buttons"
          :key="btn.key"
          class="top-btn"
          :class="{ active: btn.active }"
          @tap="$emit(btn.action, btn.key)"
        >
          <text v-if="btn.icon" class="top-btn-icon">{{ btn.icon }}</text>
          <text class="top-btn-label">{{ btn.text || '' }}</text>
        </view>
      </view>
    </view>

    <view v-if="alliancePickerVisible" class="alliance-picker-mask" @tap="closeAlliancePicker">
      <view class="alliance-picker" @tap.stop>
        <view class="alliance-picker-head">
          <text class="alliance-picker-title">切换联盟</text>
          <text class="alliance-picker-close" @tap="closeAlliancePicker">关闭</text>
        </view>
        <scroll-view scroll-y class="alliance-picker-list" :style="allianceListStyle">
          <view v-if="allianceLoading" class="alliance-picker-state">正在加载...</view>
          <view v-else-if="!alliances.length" class="alliance-picker-state">暂无可访问联盟</view>
          <view
            v-for="item in alliances"
            :key="item.id"
            class="alliance-picker-item"
            :class="{ active: currentAlliance && Number(currentAlliance.id) === Number(item.id) }"
            @tap="chooseAlliance(item)"
          >
            <view class="alliance-picker-main">
              <text class="alliance-picker-name">{{ item.name }}</text>
              <text class="alliance-picker-role">{{ allianceRoleLabel(item) }}</text>
            </view>
            <text v-if="currentAlliance && Number(currentAlliance.id) === Number(item.id)" class="alliance-picker-check">✓</text>
          </view>
        </scroll-view>
      </view>
    </view>
  </view>
</template>

<script>
import {
  ALLIANCE_CHANGED_EVENT,
  getCurrentAlliance,
  loadAllianceContext,
  selectAlliance
} from '@/utils/alliance.js'

export default {
  name: 'TopBar',
  props: {
    title: { type: String, default: '' },
    showBack: { type: Boolean, default: false },
    backFallback: { type: String, default: '' },
    buttons: { type: Array, default: () => [] }
  },
  data() {
    return {
      topPadding: 0,
      allianceButtonStyle: {},
      alliances: [],
      currentAlliance: getCurrentAlliance(),
      alliancePickerVisible: false,
      allianceLoading: false,
      allianceChangeHandler: null
    }
  },
  computed: {
    allianceButtonLabel() {
      if (!this.currentAlliance) return '苍穹联盟'
      return `${this.currentAlliance.name}（${this.allianceRoleLabel(this.currentAlliance)}）`
    },
    allianceListStyle() {
      const rows = this.allianceLoading ? 1 : Math.max(this.alliances.length, 1)
      return { height: `${Math.min(rows * 104, 624)}rpx` }
    }
  },
  created() {
    const info = uni.getSystemInfoSync()
    const menuButton = uni.getMenuButtonBoundingClientRect()
    // 胶囊底部到屏幕顶部的距离 = 状态栏 + 胶囊高度 + 间距
    // 让 TopBar 内容区从胶囊底部开始
    const statusBarHeight = info.statusBarHeight || 20
    const menuTop = menuButton.top || statusBarHeight + 6
    const menuHeight = menuButton.height || 32
    const menuBottom = menuButton.bottom || menuTop + menuHeight
    const menuLeft = menuButton.left || (info.windowWidth || 375) - 100
    this.topPadding = menuBottom
    this.allianceButtonStyle = {
      top: `${menuTop}px`,
      left: '12px',
      width: `${Math.max(120, menuLeft - 24)}px`,
      height: `${menuHeight}px`
    }
    this.allianceChangeHandler = alliance => { this.currentAlliance = alliance }
    uni.$on(ALLIANCE_CHANGED_EVENT, this.allianceChangeHandler)
    this.refreshAlliances()
  },
  beforeDestroy() {
    if (this.allianceChangeHandler) uni.$off(ALLIANCE_CHANGED_EVENT, this.allianceChangeHandler)
  },
  methods: {
    allianceRoleLabel(item) {
      if (!item) return '成员'
      const role = item.role_label || ({ leader: '首领', admin: '管理', member: '成员' }[item.role] || '成员')
      if (item.role === 'admin' || item.role === 'leader') {
        if (item.verification_status === 'partial') return `${role}·部分认证 ${item.verified_clan_count || 0}/${item.clan_count || 0}`
        if (item.verification_status !== 'verified') return `${role}·未认证`
      }
      return role
    },
    async refreshAlliances() {
      if (!uni.getStorageSync('token')) return
      this.allianceLoading = true
      try {
        const result = await loadAllianceContext()
        this.alliances = result.alliances
        this.currentAlliance = result.current
      } catch (e) {
        this.alliances = []
      } finally {
        this.allianceLoading = false
      }
    },
    openAlliancePicker() {
      if (!uni.getStorageSync('token')) {
        uni.showToast({ title: '登录后可切换联盟', icon: 'none' })
        return
      }
      this.alliancePickerVisible = true
      this.refreshAlliances()
    },
    closeAlliancePicker() { this.alliancePickerVisible = false },
    async chooseAlliance(item) {
      if (!item || (this.currentAlliance && Number(item.id) === Number(this.currentAlliance.id))) {
        this.closeAlliancePicker()
        return
      }
      this.allianceLoading = true
      try {
        this.currentAlliance = await selectAlliance(item.id)
        this.closeAlliancePicker()
      } catch (e) {
        uni.showToast({ title: e.message || '切换失败', icon: 'none' })
      } finally {
        this.allianceLoading = false
      }
    },
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
  position: relative;
  width: 100%;
  background: #1a1a2e;
  border-bottom: 1rpx solid #2a2a4a;
}

.alliance-switch {
  position: absolute;
  z-index: 20;
  display: flex;
  align-items: center;
  box-sizing: border-box;
  padding: 0 18rpx;
  color: #d9deea;
  background: #20203a;
  border: 1rpx solid #303052;
  border-radius: 28rpx;
}

.alliance-switch:active { background: #292947; }
.alliance-switch-name { min-width: 0; overflow: hidden; font-size: 23rpx; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.alliance-switch-arrow { flex-shrink: 0; margin-left: 8rpx; color: #5fa8ff; font-size: 22rpx; }

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
  display: flex;
  align-items: center;
}

.top-btn {
  height: 56rpx;
  box-sizing: border-box;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 26rpx;
  color: #c0c0c0;
  padding: 8rpx 12rpx;
  margin-left: 12rpx;
  white-space: nowrap;
}

.top-btn-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  line-height: 1;
}

.top-btn-label {
  line-height: 1;
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

.alliance-picker-mask {
  position: fixed;
  z-index: 3000;
  top: 0;
  right: 0;
  bottom: 0;
  left: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 32rpx;
  box-sizing: border-box;
  background: rgba(5, 5, 18, .72);
}
.alliance-picker { width: 100%; max-height: 70vh; overflow: hidden; background: #1a1a32; border: 1rpx solid #34345a; border-radius: 20rpx; box-shadow: 0 20rpx 60rpx rgba(0, 0, 0, .35); }
.alliance-picker-list { max-height: 54vh; }
.alliance-picker-head { display: flex; align-items: center; justify-content: space-between; min-height: 92rpx; padding: 0 28rpx; border-bottom: 1rpx solid #2c2c4b; }
.alliance-picker-title { color: #f0f1f6; font-size: 30rpx; font-weight: 600; }
.alliance-picker-close { padding: 18rpx 0 18rpx 24rpx; color: #5fa8ff; font-size: 24rpx; }
.alliance-picker-state { padding: 48rpx 28rpx; color: #747d94; font-size: 25rpx; text-align: center; }
.alliance-picker-item { display: flex; align-items: center; justify-content: space-between; min-height: 104rpx; padding: 0 28rpx; border-bottom: 1rpx solid #282846; }
.alliance-picker-item:last-child { border-bottom: 0; }
.alliance-picker-item.active { background: rgba(74, 144, 217, .12); }
.alliance-picker-main { min-width: 0; display: flex; flex-direction: column; }
.alliance-picker-name { overflow: hidden; color: #d7dae4; font-size: 28rpx; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.alliance-picker-role { margin-top: 8rpx; color: #727b92; font-size: 21rpx; }
.alliance-picker-item.active .alliance-picker-role, .alliance-picker-check { color: #5fa8ff; }
.alliance-picker-check { flex-shrink: 0; margin-left: 20rpx; font-size: 30rpx; }
</style>
