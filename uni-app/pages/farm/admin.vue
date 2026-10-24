<template>
  <view class="admin-hub">
    <view v-if="loading" class="page-state">正在加载...</view>
    <view v-else-if="error" class="page-state">
      <text class="state-error">{{ error }}</text>
      <button class="small-button" @tap="load">重新加载</button>
    </view>
    <view v-else class="menu-list">
      <view class="menu-card" @tap="openSection('/pages/farm/admin-rounds')">
        <view class="menu-icon icon-round">场</view>
        <view class="menu-copy">
          <text class="menu-name">场次管理</text>
          <text class="menu-desc">开始搜战时间、场次开放与登记结果</text>
        </view>
        <text class="menu-arrow">›</text>
      </view>

      <view class="menu-card" @tap="openSection('/pages/farm/admin-clans')">
        <view class="menu-icon icon-clan">部</view>
        <view class="menu-copy">
          <text class="menu-name">部落管理</text>
          <text class="menu-desc">添加、转移与管理互刷部落</text>
        </view>
        <text class="menu-arrow">›</text>
      </view>

      <view class="menu-card" @tap="openSection('/pages/farm/admin-accounts')">
        <view class="menu-icon icon-account">号</view>
        <view class="menu-copy">
          <text class="menu-name">账号管理</text>
          <text class="menu-desc">创建账号、设置角色和账号状态</text>
        </view>
        <text class="menu-arrow">›</text>
      </view>
    </view>
  </view>
</template>

<script>
import { getFarmMe } from '@/utils/api.js'

export default {
  data() {
    return { loading: true, error: '' }
  },
  onShow() { this.load() },
  methods: {
    async load() {
      this.loading = true
      this.error = ''
      try {
        const me = await getFarmMe()
        if (!['creator', 'admin'].includes(me.role)) throw new Error('当前账号没有互刷联盟管理权限')
      } catch (e) {
        this.error = e.message || '加载失败'
      } finally {
        this.loading = false
      }
    },
    openSection(url) { uni.navigateTo({ url }) }
  }
}
</script>

<style>
.admin-hub { min-height: 100vh; padding: 28rpx 26rpx; box-sizing: border-box; background: #0f0f23; color: #eef1f8; }
.page-state { display: flex; min-height: 70vh; flex-direction: column; align-items: center; justify-content: center; gap: 24rpx; color: #7f899f; font-size: 26rpx; }.state-error { color: #d78383; }.small-button { padding: 0 32rpx; border: 1rpx solid #31537d; border-radius: 12rpx; background: transparent; color: #76aee6; font-size: 24rpx; }
.menu-list { padding-top: 2rpx; }
.menu-card { display: flex; min-height: 116rpx; align-items: center; margin-bottom: 16rpx; padding: 16rpx 20rpx; border: 1rpx solid #292945; border-radius: 14rpx; box-sizing: border-box; background: #18182d; }
.menu-icon { display: flex; width: 58rpx; height: 58rpx; flex-shrink: 0; align-items: center; justify-content: center; margin-right: 18rpx; border-radius: 13rpx; font-size: 23rpx; font-weight: 700; }
.icon-round { background: #20304d; color: #73afe7; }.icon-clan { background: #243044; color: #91b4d4; }.icon-account { background: #302d45; color: #ad9edb; }
.menu-copy { min-width: 0; flex: 1; }.menu-name, .menu-desc { display: block; }.menu-name { color: #e8ebf3; font-size: 26rpx; font-weight: 600; }.menu-desc { margin-top: 7rpx; color: #778198; font-size: 21rpx; line-height: 1.5; }
.menu-arrow { flex-shrink: 0; margin-left: 12rpx; color: #606b83; font-size: 36rpx; }
</style>
