<template>
  <view class="top-bar">
    <view class="top-safe-area" :style="{ height: topPadding + 'px' }">
      <view class="alliance-switch" :style="allianceButtonStyle" @tap="openAlliancePicker">
        <text class="alliance-switch-name">{{ currentAlliance ? currentAlliance.name : '选择联盟' }}</text>
        <text v-if="currentAlliance" class="alliance-switch-role">{{ allianceRoleLabel(currentAlliance) }}</text>
        <text class="alliance-switch-arrow">⌄</text>
      </view>
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
        <view class="alliance-create-entry" :class="{ disabled: isLoggedIn && !canCreateAlliance }" @tap="toggleCreateForm">
          <text class="alliance-create-icon">＋</text>
          <text class="alliance-create-label">创建联盟</text>
        </view>
        <view v-if="createFormVisible" class="alliance-create-form">
          <input
            v-model="createAllianceName"
            class="alliance-create-input"
            maxlength="30"
            placeholder="联盟名称"
            placeholder-style="color:#59637a"
          />
          <view class="alliance-create-actions">
            <button class="alliance-create-cancel" :disabled="createBusy" @tap="cancelCreate">取消</button>
            <button class="alliance-create-submit" :loading="createBusy" :disabled="createBusy" @tap="submitCreateAlliance">创建</button>
          </view>
        </view>
        <view v-if="isLoggedIn" class="alliance-manage-entry" @tap="openAllianceListManagement">
          <text class="alliance-create-icon">⚙</text>
          <text class="alliance-create-label">管理联盟列表</text>
        </view>
        <scroll-view scroll-y class="alliance-picker-list" :style="allianceListStyle">
          <view v-if="allianceLoading" class="alliance-picker-state">正在加载...</view>
          <view v-else-if="!alliances.length && !browsedAlliances.length" class="alliance-picker-state">暂无可访问联盟</view>
          <view v-if="alliances.length" class="alliance-group-title">我的联盟</view>
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
            <view class="alliance-picker-actions">
              <text v-if="currentAlliance && Number(currentAlliance.id) === Number(item.id)" class="alliance-picker-check">✓</text>
            </view>
          </view>
          <view v-if="browsedAlliances.length" class="alliance-group-title">浏览过的联盟</view>
          <view
            v-for="item in browsedAlliances"
            :key="item.id"
            class="alliance-picker-item"
            :class="{ active: currentAlliance && Number(currentAlliance.id) === Number(item.id) }"
            @tap="chooseAlliance(item)"
          >
            <view class="alliance-picker-main">
              <text class="alliance-picker-name">{{ item.name }}</text>
              <text class="alliance-picker-role">浏览</text>
            </view>
            <view class="alliance-picker-actions">
              <text v-if="currentAlliance && Number(currentAlliance.id) === Number(item.id)" class="alliance-picker-check">✓</text>
              <text v-if="isLoggedIn" class="alliance-apply" @tap.stop="applyToAlliance(item)">申请加入</text>
            </view>
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
  ensureBrowseShareToken,
  selectAlliance,
  selectLocalAlliance
} from '@/utils/alliance.js'
import { createFreeAlliance, requestAllianceJoin } from '@/utils/api.js'

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
      browsedAlliances: [],
      hiddenAlliances: [],
      allianceFeatures: {},
      currentAlliance: getCurrentAlliance(),
      alliancePickerVisible: false,
      allianceLoading: false,
      hiddenExpanded: false,
      createFormVisible: false,
      createAllianceName: '我的部落',
      createBusy: false,
      allianceChangeHandler: null
    }
  },
  computed: {
    allianceListStyle() {
      const groupRows = (this.alliances.length ? 1 : 0) + (this.browsedAlliances.length ? 1 : 0)
      const rows = this.allianceLoading ? 1 : Math.max(this.alliances.length + this.browsedAlliances.length + groupRows, 1)
      return { height: `${Math.min(rows * 104, 624)}rpx` }
    },
    isLoggedIn() { return Boolean(uni.getStorageSync('token')) },
    canCreateAlliance() {
      if (!this.isLoggedIn) return true
      const feature = this.allianceFeatures.free_alliance || {}
      return Boolean(feature.can_create)
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
    this.allianceButtonStyle = `width:${Math.max(120, menuLeft - 24)}px;height:${menuHeight}px;`
    this.allianceChangeHandler = alliance => {
      this.currentAlliance = alliance
      // 同时向当前页面发送组件事件。部分小程序运行时在 tab 页中恢复全局事件
      // 监听较慢，页面可通过这个事件立即按新的联盟 ID 刷新数据。
      this.$emit('alliance-change', alliance)
    }
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
      this.allianceLoading = true
      try {
        const result = await loadAllianceContext()
        this.alliances = result.alliances
        this.browsedAlliances = result.browsedAlliances || []
        this.hiddenAlliances = result.hiddenAlliances || []
        this.allianceFeatures = result.features || {}
        this.currentAlliance = result.current
        if (this.currentAlliance && this.currentAlliance.role !== 'visitor' && this.isLoggedIn) {
          ensureBrowseShareToken(this.currentAlliance.id).catch(() => {})
        }
      } catch (e) {
        this.alliances = []
        this.browsedAlliances = []
        this.hiddenAlliances = []
        this.allianceFeatures = {}
      } finally {
        this.allianceLoading = false
      }
    },
    openAlliancePicker() {
      this.alliancePickerVisible = true
      this.refreshAlliances()
    },
    closeAlliancePicker() {
      this.alliancePickerVisible = false
      this.createFormVisible = false
    },
    toggleCreateForm() {
      if (this.createBusy) return
      if (!this.isLoggedIn) {
        this.closeAlliancePicker()
        uni.showToast({ title: '登录后可以创建联盟', icon: 'none' })
        setTimeout(() => uni.switchTab({ url: '/pages/settings/settings' }), 500)
        return
      }
      if (!this.canCreateAlliance) {
        const feature = this.allianceFeatures.free_alliance || {}
        const message = feature.existing_alliance_id
          ? '每个用户只能创建一个联盟'
          : '当前暂未开放创建联盟'
        uni.showToast({ title: message, icon: 'none' })
        return
      }
      this.createFormVisible = !this.createFormVisible
      if (this.createFormVisible && !this.createAllianceName.trim()) {
        this.createAllianceName = '我的部落'
      }
    },
    cancelCreate() {
      if (this.createBusy) return
      this.createFormVisible = false
    },
    async submitCreateAlliance() {
      const name = this.createAllianceName.trim()
      if (!name || this.createBusy) {
        if (!name) uni.showToast({ title: '请输入联盟名称', icon: 'none' })
        return
      }
      this.createBusy = true
      try {
        const created = await createFreeAlliance(name)
        this.currentAlliance = await selectAlliance(created.id)
        await this.refreshAlliances()
        this.createFormVisible = false
        uni.showToast({ title: '创建成功', icon: 'success' })
      } catch (e) {
        uni.showModal({ title: '创建失败', content: e.message || '请稍后重试', showCancel: false })
      } finally {
        this.createBusy = false
      }
    },
    openAllianceListManagement() {
      this.closeAlliancePicker()
      uni.navigateTo({ url: '/pages/settings/alliance-list-management' })
    },
    async applyToAlliance(item) {
      if (!this.isLoggedIn) {
        uni.showToast({ title: '请先登录', icon: 'none' })
        return
      }
      try {
        await requestAllianceJoin(item.id)
        uni.showToast({ title: '申请已提交', icon: 'success' })
      } catch (e) {
        uni.showToast({ title: e.message || '申请失败', icon: 'none' })
      }
    },
    async chooseAlliance(item) {
      if (this.allianceLoading) return
      if (!item || (this.currentAlliance && Number(item.id) === Number(this.currentAlliance.id))) {
        this.closeAlliancePicker()
        return
      }
      this.allianceLoading = true
      try {
        this.currentAlliance = this.isLoggedIn
          ? await selectAlliance(item.id)
          : selectLocalAlliance(item)
        if (this.currentAlliance.role !== 'visitor' && this.isLoggedIn) {
          ensureBrowseShareToken(this.currentAlliance.id).catch(() => {})
        }
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
  width: 100%;
  background: #1a1a2e;
  border-bottom: 1rpx solid #2a2a4a;
}

.top-safe-area {
  display: flex;
  width: 100%;
  box-sizing: border-box;
  align-items: flex-end;
  padding-left: 12px;
}

.alliance-switch {
  display: flex;
  align-items: center;
  box-sizing: border-box;
  padding: 0;
  color: #d9deea;
  background: transparent;
}

.alliance-switch:active { opacity: .68; }
.alliance-switch-name { min-width: 0; overflow: hidden; color: #ffffff; font-size: 35rpx; font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }
.alliance-switch-role { flex-shrink: 0; margin-left: 10rpx; color: #73809a; font-size: 20rpx; white-space: nowrap; }
.alliance-switch-arrow { flex-shrink: 0; margin-left: 7rpx; color: #5fa8ff; font-size: 21rpx; }

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
.alliance-create-entry { display: flex; align-items: center; min-height: 92rpx; padding: 0 28rpx; border-bottom: 1rpx solid #34345a; background: rgba(74, 144, 217, .08); color: #5fa8ff; }
.alliance-create-entry:active { background: rgba(74, 144, 217, .16); }
.alliance-create-entry.disabled { color: #626d82; background: rgba(255, 255, 255, .02); }
.alliance-create-icon { margin-right: 12rpx; font-size: 34rpx; font-weight: 400; }
.alliance-create-label { font-size: 27rpx; font-weight: 600; }
.alliance-manage-entry { display: flex; align-items: center; min-height: 82rpx; padding: 0 28rpx; border-bottom: 1rpx solid #34345a; color: #9aa6bb; }
.alliance-manage-entry:active { background: rgba(255, 255, 255, .04); }
.alliance-group-title { padding: 18rpx 28rpx 10rpx; color: #68738b; font-size: 21rpx; background: #151529; }
.alliance-create-form { padding: 22rpx 28rpx; border-bottom: 1rpx solid #34345a; background: #17172d; }
.alliance-create-input { height: 72rpx; padding: 0 20rpx; border: 1rpx solid #353555; border-radius: 12rpx; color: #eef0f6; font-size: 26rpx; background: #111125; }
.alliance-create-actions { display: flex; justify-content: flex-end; margin-top: 18rpx; }
.alliance-create-cancel, .alliance-create-submit { width: 144rpx; height: 64rpx; margin: 0 0 0 16rpx; padding: 0; border: 0; border-radius: 10rpx; font-size: 24rpx; line-height: 64rpx; }
.alliance-create-cancel { color: #8992a8; background: #24243f; }
.alliance-create-submit { color: #eef5ff; background: #356da8; }
.alliance-create-cancel::after, .alliance-create-submit::after { border: 0; }
.alliance-picker-item { display: flex; align-items: center; justify-content: space-between; min-height: 104rpx; padding: 0 28rpx; border-bottom: 1rpx solid #282846; }
.alliance-picker-item:last-child { border-bottom: 0; }
.alliance-picker-item.active { background: rgba(74, 144, 217, .12); }
.alliance-picker-main { min-width: 0; display: flex; flex-direction: column; }
.alliance-picker-name { overflow: hidden; color: #d7dae4; font-size: 28rpx; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.alliance-picker-role { margin-top: 8rpx; color: #727b92; font-size: 21rpx; }
.alliance-picker-actions { display: flex; flex-shrink: 0; align-items: center; margin-left: 18rpx; }
.alliance-picker-item.active .alliance-picker-role, .alliance-picker-check { color: #5fa8ff; }
.alliance-picker-check { margin-right: 18rpx; font-size: 30rpx; }
.alliance-picker-more { min-width: 52rpx; padding: 16rpx 0; color: #7e879d; font-size: 27rpx; text-align: right; }
.alliance-apply { min-width: 112rpx; padding: 16rpx 0 16rpx 16rpx; color: #5fa8ff; font-size: 22rpx; text-align: right; }
.alliance-hidden-toggle { display: flex; align-items: center; justify-content: space-between; min-height: 88rpx; padding: 0 28rpx; border-top: 1rpx solid #34345a; color: #7b849a; font-size: 23rpx; }
.alliance-picker-item-hidden { background: rgba(255, 255, 255, .018); }
.alliance-picker-item-hidden .alliance-picker-name { color: #9aa1b2; }
.alliance-restore { flex-shrink: 0; margin-left: 20rpx; padding: 18rpx 0 18rpx 20rpx; color: #5fa8ff; font-size: 23rpx; }
</style>
