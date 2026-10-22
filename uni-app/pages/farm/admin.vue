<template>
  <view class="admin-hub">
    <view v-if="loading" class="page-state">正在加载...</view>
    <view v-else-if="error" class="page-state">
      <text class="state-error">{{ error }}</text>
      <button class="small-button" @tap="load">重新加载</button>
    </view>
    <view v-else>
      <view class="scope-card">
        <text class="scope-label">管理范围</text>
        <text class="scope-title">整个互刷联盟</text>
        <text class="scope-desc">统一管理联盟内的账号、互刷部落和开战场次</text>
      </view>

      <view class="section-head">
        <text class="section-title">选择管理功能</text>
        <text class="section-tip">进入后进行具体操作</text>
      </view>
      <view class="function-row">
        <view class="function-button" @tap="openSection('/pages/farm/admin-rounds')">
          <text class="function-name">场次管理</text>
          <text class="function-arrow">›</text>
        </view>
        <view class="function-button" @tap="openSection('/pages/farm/admin-clans')">
          <text class="function-name">部落管理</text>
          <text class="function-arrow">›</text>
        </view>
        <view class="function-button" @tap="openSection('/pages/farm/admin-accounts')">
          <text class="function-name">账号管理</text>
          <text class="function-arrow">›</text>
        </view>
      </view>

      <view class="help-card">
        <view class="help-row">
          <text class="help-name">场次管理</text>
          <text class="help-desc">设置开始搜战时间、开放场次和查看登记结果</text>
        </view>
        <view class="help-row">
          <text class="help-name">部落管理</text>
          <text class="help-desc">添加互刷部落、调整账号归属和启用状态</text>
        </view>
        <view class="help-row">
          <text class="help-name">账号管理</text>
          <text class="help-desc">创建独立账号、设置角色和账号状态</text>
        </view>
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
.scope-card { padding: 30rpx; border: 1rpx solid #31527b; border-radius: 20rpx; background: linear-gradient(145deg, #19243d, #171a32); }.scope-label, .scope-title, .scope-desc { display: block; }.scope-label { color: #7890ad; font-size: 21rpx; }.scope-title { margin-top: 8rpx; font-size: 34rpx; font-weight: 700; }.scope-desc { margin-top: 10rpx; color: #8793aa; font-size: 22rpx; line-height: 1.5; }
.section-head { display: flex; align-items: flex-end; justify-content: space-between; padding: 34rpx 4rpx 18rpx; }.section-title { font-size: 28rpx; font-weight: 650; }.section-tip { color: #69738a; font-size: 20rpx; }
.function-row { display: flex; gap: 12rpx; }.function-button { display: flex; min-width: 0; height: 96rpx; flex: 1; align-items: center; justify-content: center; border: 1rpx solid #2d3e62; border-radius: 16rpx; background: #191c34; color: #e8edf6; }.function-name { font-size: 24rpx; font-weight: 600; white-space: nowrap; }.function-arrow { margin-left: 6rpx; color: #75afe5; font-size: 32rpx; line-height: 1; }
.help-card { margin-top: 24rpx; padding: 0 24rpx; border: 1rpx solid #292f4e; border-radius: 18rpx; background: #17182d; }.help-row { padding: 23rpx 0; border-bottom: 1rpx solid #282e4b; }.help-row:last-child { border-bottom: 0; }.help-name, .help-desc { display: block; }.help-name { font-size: 24rpx; font-weight: 600; }.help-desc { margin-top: 7rpx; color: #717c93; font-size: 21rpx; line-height: 1.5; }
</style>
