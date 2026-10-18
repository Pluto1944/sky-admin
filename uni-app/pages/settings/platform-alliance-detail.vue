<template>
  <view class="page">
    <TopBar title="联盟详情" :show-back="true" back-fallback="/pages/settings/platform-alliance-list" />
    <scroll-view scroll-y class="content">
      <view v-if="loading && !detail" class="state">加载联盟...</view>
      <template v-else-if="detail">
        <view class="summary-card">
          <view class="title-row">
            <view class="grow">
              <text class="summary-name">{{ detail.alliance.name }}</text>
              <text class="sub">{{ detail.alliance.alliance_key }} · {{ planLabel(detail.alliance.plan_code) }}</text>
            </view>
            <text :class="['status', 'status-' + detail.alliance.status]">{{ statusLabel(detail.alliance.status) }}</text>
          </view>
          <button class="secondary-btn rename-btn" @tap="renameAlliance">修改联盟名称</button>
          <text class="platform-tip">超级管理模式：成员、部落和联赛使用平台专用页面及权限，数量不受套餐限制，所有操作均保留审计。</text>
        </view>

        <view class="section-title">业务管理</view>
        <view class="menu-card">
          <view class="menu-row" @tap="openPage('platform-alliance-members')">
            <view class="menu-icon icon-member">员</view>
            <view class="grow"><text class="name">管理联盟成员</text><text class="sub">添加、搜索、设置权限与移交首领</text></view>
            <text class="menu-count">{{ activeMemberCount }} 人</text><text class="arrow">›</text>
          </view>
          <view class="menu-row" @tap="openPage('platform-clan-management')">
            <view class="menu-icon icon-clan">部</view>
            <view class="grow"><text class="name">管理部落</text><text class="sub">添加、移除、排序、类型、别名与认证</text></view>
            <text class="menu-count">{{ activeClanCount }} 个</text><text class="arrow">›</text>
          </view>
          <view class="menu-row" @tap="openPage('platform-cwl-settings')">
            <view class="menu-icon icon-cwl">赛</view>
            <view class="grow"><text class="name">管理联赛部落</text><text class="sub">配置本月和下月的联赛队伍</text></view>
            <text class="menu-count">按月配置</text><text class="arrow">›</text>
          </view>
        </view>

        <view class="section-title">联盟设置</view>
        <view class="menu-card">
          <view class="menu-row" @tap="openPage('platform-alliance-plan')">
            <view class="menu-icon icon-plan">权</view>
            <view class="grow"><text class="name">套餐权益</text><text class="sub">调整免费版、普通会员、高级会员与权益期限</text></view>
            <text class="menu-count">{{ planLabel(detail.alliance.plan_code) }}</text><text class="arrow">›</text>
          </view>
          <view class="menu-row" @tap="openPage('platform-alliance-status')">
            <view class="menu-icon icon-status">态</view>
            <view class="grow"><text class="name">联盟状态</text><text class="sub">停用、恢复或删除联盟</text></view>
            <text :class="['menu-count', 'status-' + detail.alliance.status]">{{ statusLabel(detail.alliance.status) }}</text><text class="arrow">›</text>
          </view>
          <view class="menu-row" @tap="openPage('platform-alliance-audit')">
            <view class="menu-icon icon-audit">记</view>
            <view class="grow"><text class="name">联盟操作记录</text><text class="sub">查看该联盟最近的审计记录</text></view>
            <text class="menu-count">{{ detail.audit.length }} 条</text><text class="arrow">›</text>
          </view>
        </view>
        <view class="bottom-space"></view>
      </template>
    </scroll-view>
  </view>
</template>

<script>
import TopBar from '@/components/TopBar.vue'
import { getPlatformAlliance, renamePlatformAlliance } from '@/utils/api.js'

export default {
  components: { TopBar },
  data() { return { allianceId: null, loading: true, detail: null } },
  computed: {
    activeMemberCount() { return this.detail ? this.detail.members.filter(item => item.status === 'active').length : 0 },
    activeClanCount() { return this.detail ? this.detail.clans.filter(item => item.status === 'active').length : 0 }
  },
  onLoad(options) { this.allianceId = Number(options && options.id) || null },
  async onShow() { if (this.allianceId) await this.reloadDetail() },
  methods: {
    async reloadDetail() {
      this.loading = true
      try { this.detail = await getPlatformAlliance(this.allianceId) }
      catch (err) { uni.showModal({ title: '联盟加载失败', content: err.message || '请稍后重试', showCancel: false }) }
      finally { this.loading = false }
    },
    openPage(page) { uni.navigateTo({ url: `/pages/settings/${page}?id=${this.allianceId}` }) },
    renameAlliance() {
      const alliance = this.detail.alliance
      uni.showModal({
        title: '修改联盟名称', editable: true, content: alliance.name, placeholderText: '联盟名称',
        success: async result => {
          if (!result.confirm || !result.content.trim() || result.content.trim() === alliance.name) return
          try {
            await renamePlatformAlliance(alliance.id, result.content.trim())
            await this.reloadDetail()
            uni.showToast({ title: '名称已更新', icon: 'success' })
          } catch (err) { uni.showToast({ title: err.message || '修改失败', icon: 'none' }) }
        }
      })
    },
    statusLabel(value) { return ({ active: '正常', suspended: '已停用', archived: '已删除' }[value] || value) },
    planLabel(value) { return ({ free: '免费版', standard: '普通会员', premium: '高级会员', paid: '历史付费版', internal: '内部版' }[value] || value) }
  }
}
</script>

<style>
.page { height: 100vh; display: flex; flex-direction: column; color: #dce1ed; background: #0f0f23; }.content { flex: 1; min-height: 0; padding: 24rpx; box-sizing: border-box; }.state { padding: 180rpx 24rpx; color: #717b91; text-align: center; }
.summary-card, .menu-card { border: 1rpx solid #292945; border-radius: 14rpx; background: #18182d; }.summary-card { padding: 22rpx; }.title-row, .menu-row { display: flex; align-items: center; }.grow { flex: 1; min-width: 0; }
.summary-name, .name, .sub { display: block; }.summary-name { color: #f0f2f8; font-size: 31rpx; font-weight: 700; }.name { color: #e8ebf3; font-size: 26rpx; font-weight: 600; }.sub { margin-top: 7rpx; color: #778198; font-size: 21rpx; line-height: 1.5; }
.status { font-size: 22rpx; }.status-active { color: #54b9a6; }.status-suspended { color: #d29a5f; }.status-archived { color: #737b8e; }.secondary-btn { border: 0; border-radius: 9rpx; color: #7eb8f6; background: #202b42; font-size: 23rpx; }.secondary-btn::after { border: 0; }.rename-btn { width: 100%; margin-top: 18rpx; }
.platform-tip { display: block; margin-top: 18rpx; padding-top: 16rpx; border-top: 1rpx solid #292945; color: #69758c; font-size: 20rpx; line-height: 1.6; }.section-title { margin: 30rpx 8rpx 14rpx; color: #7f8aa2; font-size: 23rpx; }.menu-card { overflow: hidden; }
.menu-row { min-height: 116rpx; padding: 16rpx 20rpx; box-sizing: border-box; border-bottom: 1rpx solid #25253e; }.menu-row:last-child { border-bottom: 0; }.menu-icon { width: 58rpx; height: 58rpx; margin-right: 18rpx; display: flex; align-items: center; justify-content: center; flex-shrink: 0; border-radius: 13rpx; color: #73afe7; background: #20304d; font-size: 24rpx; font-weight: 600; }
.icon-clan { color: #91b4d4; background: #243044; }.icon-cwl { color: #d4aa67; background: #332d38; }.icon-plan { color: #a99de0; background: #2d2948; }.icon-status { color: #66bca9; background: #243a3a; }.icon-audit { color: #aea6d7; background: #302d45; }.menu-count { margin-left: 12rpx; color: #7e89a1; font-size: 20rpx; white-space: nowrap; }.arrow { margin-left: 12rpx; color: #606b83; font-size: 36rpx; }.bottom-space { height: 80rpx; }
</style>
