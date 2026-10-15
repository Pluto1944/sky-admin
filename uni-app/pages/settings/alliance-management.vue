<template>
  <view class="page">
    <TopBar title="管理联盟" :show-back="true" back-fallback="/pages/settings/settings" />
    <scroll-view scroll-y class="content">
      <view v-if="loading" class="state">正在加载...</view>
      <template v-else-if="alliance">
        <view class="summary-card">
          <view class="summary-head">
            <view class="grow">
              <text class="summary-name">{{ alliance.name }}</text>
              <text class="summary-plan">{{ alliance.plan.name }} · {{ planStateLabel(alliance.plan.status) }}</text>
            </view>
            <text class="summary-role">{{ alliance.role_label || roleLabel(alliance.role) }}</text>
          </view>
          <view class="metrics">
            <view class="metric"><text class="metric-value">{{ alliance.clan_count || 0 }}</text><text class="metric-label">部落</text></view>
            <view class="metric"><text class="metric-value">{{ activeMemberCount }}</text><text class="metric-label">成员</text></view>
            <view class="metric"><text class="metric-value">{{ pendingRequestCount }}</text><text class="metric-label">待申请</text></view>
            <view class="metric"><text class="metric-value">{{ activeInviteCount }}</text><text class="metric-label">有效邀请</text></view>
          </view>
        </view>

        <view class="entry-card" @tap="openAllianceSettings">
          <view class="entry-icon icon-settings">设</view>
          <view class="grow"><text class="entry-name">联盟设置</text><text class="entry-sub">联盟名称、套餐信息、退出或删除联盟</text></view>
          <text class="arrow">›</text>
        </view>

        <view class="entry-card" @tap="openClanManagement">
          <view class="entry-icon icon-clan">部</view>
          <view class="grow"><text class="entry-name">管理部落</text><text class="entry-sub">添加、移除、排序、标签与认证</text></view>
          <text class="entry-count">{{ alliance.clan_count || 0 }} 个</text><text class="arrow">›</text>
        </view>

        <view class="entry-card" @tap="openCwlSettings">
          <view class="entry-icon icon-cwl">赛</view>
          <view class="grow"><text class="entry-name">管理联赛部落</text><text class="entry-sub">配置本月和下月的联赛队伍</text></view>
          <text class="arrow">›</text>
        </view>

        <view class="entry-card" @tap="openMemberManagement">
          <view class="entry-icon icon-members">员</view>
          <view class="grow"><text class="entry-name">管理联盟成员</text><text class="entry-sub">添加、搜索成员并设置联盟权限</text></view>
          <text class="entry-count">{{ activeMemberCount }} 人</text><text class="arrow">›</text>
        </view>

        <view class="entry-card" @tap="openJoinRequests">
          <view class="entry-icon icon-request">申</view>
          <view class="grow"><text class="entry-name">加入申请</text><text class="entry-sub">集中查看并处理全部申请记录</text></view>
          <text :class="['entry-count', { attention: pendingRequestCount > 0 }]">{{ pendingRequestCount }} 条</text><text class="arrow">›</text>
        </view>

        <view class="entry-card" @tap="openInvitations">
          <view class="entry-icon icon-invite">邀</view>
          <view class="grow"><text class="entry-name">邀请管理</text><text class="entry-sub">生成联盟邀请并查看邀请记录</text></view>
          <text class="entry-count">{{ activeInviteCount }} 有效</text><text class="arrow">›</text>
        </view>
      </template>
      <view v-else class="state">请先创建或加入联盟</view>
      <view class="bottom-space"></view>
    </scroll-view>
  </view>
</template>

<script>
import TopBar from '@/components/TopBar.vue'
import { getAllianceJoinRequests, getAllianceShares, getAllianceUserMembers } from '@/utils/api.js'
import { getCurrentAlliance, loadAllianceContext } from '@/utils/alliance.js'

export default {
  components: { TopBar },
  data() {
    return { loading: true, alliance: null, members: [], joinRequests: [], shareLinks: [] }
  },
  computed: {
    activeMemberCount() { return this.members.filter(item => item.status === 'active').length },
    pendingRequestCount() { return this.joinRequests.filter(item => item.status === 'pending').length },
    activeInviteCount() { return this.shareLinks.filter(item => item.status === 'active').length }
  },
  async onShow() { await this.loadData() },
  methods: {
    openAllianceSettings() { uni.navigateTo({ url: '/pages/settings/alliance-settings' }) },
    openClanManagement() { uni.navigateTo({ url: '/pages/settings/clan-management' }) },
    openCwlSettings() { uni.navigateTo({ url: '/pages/settings/cwl-settings' }) },
    openMemberManagement() { uni.navigateTo({ url: '/pages/settings/alliance-members' }) },
    openJoinRequests() { uni.navigateTo({ url: '/pages/settings/alliance-join-requests' }) },
    openInvitations() { uni.navigateTo({ url: '/pages/settings/alliance-invitations' }) },
    async loadData() {
      this.loading = true
      try {
        const loaded = await loadAllianceContext()
        this.alliance = loaded.current || getCurrentAlliance()
        if (!this.alliance) return
        if (['admin', 'leader'].indexOf(this.alliance.role) < 0) {
          uni.showToast({ title: '没有联盟管理权限', icon: 'none' })
          setTimeout(() => uni.navigateBack(), 500)
          return
        }
        const results = await Promise.all([
          getAllianceShares(this.alliance.id),
          getAllianceUserMembers(this.alliance.id),
          getAllianceJoinRequests(this.alliance.id)
        ])
        this.shareLinks = results[0].links || []
        this.members = results[1].members || []
        this.joinRequests = results[2].requests || []
      } catch (err) {
        uni.showToast({ title: err.message || '加载失败', icon: 'none' })
      } finally { this.loading = false }
    },
    roleLabel(value) { return ({ leader: '首领', admin: '管理', member: '成员' }[value] || value) },
    planStateLabel(value) { return ({ active: '有效', grace: '7天只读宽限期', legacy: '兼容权益', expired: '已到期', revoked: '已撤销' }[value] || value || '有效') }
  }
}
</script>

<style>
.page { height: 100vh; display: flex; flex-direction: column; color: #dce1ed; background: #0f0f23; }
.content { flex: 1; min-height: 0; padding: 24rpx; box-sizing: border-box; }
.state { padding: 180rpx 24rpx; color: #717b91; font-size: 25rpx; text-align: center; }
.summary-card, .entry-card { border: 1rpx solid #292945; border-radius: 14rpx; background: #18182d; }
.summary-card { overflow: hidden; }.summary-head { padding: 24rpx; display: flex; align-items: center; }.grow { flex: 1; min-width: 0; }
.summary-name, .summary-plan, .entry-name, .entry-sub, .metric-value, .metric-label { display: block; }
.summary-name { color: #f2f3f8; font-size: 31rpx; font-weight: 700; }.summary-plan { margin-top: 8rpx; color: #737d92; font-size: 21rpx; }.summary-role { margin-left: 16rpx; color: #68a8e9; font-size: 22rpx; }
.metrics { display: flex; border-top: 1rpx solid #292945; }.metric { width: 25%; padding: 18rpx 4rpx; box-sizing: border-box; text-align: center; border-right: 1rpx solid #292945; }.metric:last-child { border-right: 0; }.metric-value { color: #e8ebf3; font-size: 27rpx; font-weight: 700; }.metric-label { margin-top: 5rpx; color: #747e94; font-size: 19rpx; }
.entry-card { min-height: 116rpx; margin-top: 16rpx; padding: 16rpx 20rpx; box-sizing: border-box; display: flex; align-items: center; }
.entry-icon { width: 58rpx; height: 58rpx; margin-right: 18rpx; display: flex; align-items: center; justify-content: center; flex-shrink: 0; border-radius: 13rpx; font-size: 23rpx; font-weight: 700; }
.icon-settings { color: #73afe7; background: #20304d; }.icon-clan { color: #91b4d4; background: #243044; }.icon-cwl { color: #d4aa67; background: #332d38; }.icon-members { color: #72b6aa; background: #243936; }.icon-request { color: #c9a06d; background: #352f35; }.icon-invite { color: #ad9edb; background: #302d45; }
.entry-name { color: #e8ebf3; font-size: 26rpx; font-weight: 600; }.entry-sub { margin-top: 7rpx; color: #778198; font-size: 21rpx; line-height: 1.5; }
.entry-count { margin-left: 12rpx; color: #7e89a1; font-size: 20rpx; white-space: nowrap; }.entry-count.attention { color: #d2a666; }.arrow { margin-left: 12rpx; color: #606b83; font-size: 36rpx; }.bottom-space { height: 80rpx; }
</style>
