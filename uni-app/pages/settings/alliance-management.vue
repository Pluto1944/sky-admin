<template>
  <view class="page">
    <TopBar title="管理联盟" :show-back="true" back-fallback="/pages/settings/settings" />
    <scroll-view scroll-y class="content">
      <view v-if="loading" class="empty">正在加载...</view>
      <template v-else-if="alliance">
        <view class="card summary-card">
          <view class="title-row">
            <text class="title">{{ alliance.name }}</text>
            <text class="role">{{ alliance.role_label || roleLabel(alliance.role) }}</text>
          </view>
          <text class="meta">{{ alliance.plan.name }} · {{ alliance.clan_count }} 个部落</text>
          <text class="meta">权益：{{ planStateLabel(alliance.plan.status) }}<text v-if="alliance.plan.expires_at"> · 至 {{ shortDate(alliance.plan.expires_at) }}</text></text>
          <view v-if="alliance.role === 'leader'" class="rename-row">
            <input v-model="allianceName" class="input grow" maxlength="30" />
            <button class="mini-save" @tap="saveName">保存名称</button>
          </view>
        </view>

        <view class="section-title">业务管理</view>
        <view class="card management-card">
          <view class="management-row" @tap="openClanManagement">
            <view class="management-icon management-icon-clan">部</view>
            <view class="grow">
              <text class="name">管理部落</text>
              <text class="sub">添加、移除、排序、标签与认证</text>
            </view>
            <text class="management-arrow">›</text>
          </view>
          <view class="management-row" @tap="openCwlSettings">
            <view class="management-icon management-icon-league">赛</view>
            <view class="grow">
              <text class="name">管理联赛部落</text>
              <text class="sub">配置本月和下月的联赛队伍</text>
            </view>
            <text class="management-arrow">›</text>
          </view>
        </view>

        <template v-if="canManageMembers">
          <view class="section-title">联盟成员</view>
          <view class="card list-entry-card">
            <view class="list-entry-copy">
              <view class="grow">
                <text class="name">有效成员 {{ activeMemberCount }} 人</text>
                <text class="sub">通过 OpenID 添加、搜索成员并设置联盟权限</text>
              </view>
              <button class="list-entry-btn" @tap="openMemberManagement">管理成员</button>
            </view>
          </view>
        </template>

        <view class="section-title">加入申请</view>
        <view class="card list-entry-card">
          <view class="list-entry-copy">
            <view class="grow">
              <text class="name">待处理 {{ joinRequests.length }} 条</text>
              <text class="sub">集中查看并处理全部加入申请记录</text>
            </view>
            <button class="list-entry-btn" @tap="openJoinRequests">查看申请</button>
          </view>
        </view>

        <view class="section-title">邀请加入</view>
        <view class="card">
          <text class="body">生成联盟邀请后，其他用户登录打开分享将以普通成员身份加入，不会继承分享人的管理权限。</text>
          <button class="primary-btn" :loading="shareBusy" @tap="generateShare">生成30天邀请</button>
          <template v-if="shareToken">
            <button class="secondary-btn" open-type="share">分享联盟</button>
            <button class="text-btn" @tap="copySharePath">复制邀请参数</button>
            <text class="tip">有效期至 {{ shortDate(shareExpiresAt) }}</text>
          </template>
          <view class="list-entry-copy share-record-entry">
            <view class="grow">
              <text class="name">邀请记录</text>
              <text class="sub">共 {{ shareLinks.length }} 条，查看状态、使用人数和有效期</text>
            </view>
            <button class="list-entry-btn" @tap="openShareHistory">查看记录</button>
          </view>
        </view>

        <view v-if="alliance.role !== 'leader'" class="leave-section">
          <button class="danger-btn" @tap="confirmLeave">退出当前联盟</button>
          <text class="tip">退出后将失去当前联盟访问权限；以后可由新的有效邀请重新加入。</text>
        </view>
        <view v-else-if="alliance.plan.code !== 'internal'" class="leave-section">
          <button class="danger-btn" @tap="confirmArchive">删除当前联盟</button>
          <text class="tip">需要输入完整联盟名称确认；公共历史数据不会删除。</text>
        </view>
      </template>
      <view v-else class="empty">请先创建或加入联盟</view>
      <view class="bottom-space"></view>
    </scroll-view>
  </view>
</template>

<script>
import TopBar from '@/components/TopBar.vue'
import {
  archiveAlliance,
  createAllianceShare,
  getAllianceJoinRequests,
  getAllianceShares,
  getAllianceUserMembers,
  leaveAlliance,
  renameAlliance
} from '@/utils/api.js'
import { getCurrentAlliance, loadAllianceContext, rememberAllianceShareToken } from '@/utils/alliance.js'

export default {
  components: { TopBar },
  data() {
    return {
      loading: true,
      alliance: null,
      allianceName: '',
      members: [],
      joinRequests: [],
      shareLinks: [],
      shareToken: '',
      shareExpiresAt: '',
      shareBusy: false
    }
  },
  computed: {
    canManageMembers() {
      return this.alliance && ['admin', 'leader'].indexOf(this.alliance.role) >= 0
    },
    activeMemberCount() {
      return this.members.filter(item => item.status === 'active').length
    }
  },
  async onLoad() { await this.loadData() },
  async onShow() { if (!this.loading) await this.loadData() },
  onShareAppMessage() {
    if (!this.shareToken || !this.alliance) {
      return { title: '联盟邀请', path: '/pages/settings/settings' }
    }
    return {
      title: `${this.alliance.name}邀请你加入`,
      path: `/pages/clan/clan?share_token=${encodeURIComponent(this.shareToken)}`
    }
  },
  methods: {
    openClanManagement() {
      uni.navigateTo({ url: '/pages/settings/clan-management' })
    },
    openCwlSettings() {
      uni.navigateTo({ url: '/pages/settings/cwl-settings' })
    },
    openJoinRequests() {
      uni.navigateTo({ url: '/pages/settings/alliance-join-requests' })
    },
    openShareHistory() {
      uni.navigateTo({ url: '/pages/settings/alliance-invite-history' })
    },
    openMemberManagement() {
      uni.navigateTo({ url: '/pages/settings/alliance-members' })
    },
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
        this.allianceName = this.alliance.name
        const results = await Promise.all([
          getAllianceShares(this.alliance.id),
          getAllianceUserMembers(this.alliance.id),
          getAllianceJoinRequests(this.alliance.id)
        ])
        this.shareLinks = results[0].links || []
        this.members = results[1].members || []
        this.joinRequests = (results[2].requests || []).filter(item => item.status === 'pending')
      } catch (err) {
        uni.showToast({ title: err.message || '加载失败', icon: 'none' })
      } finally {
        this.loading = false
      }
    },
    async saveName() {
      const name = this.allianceName.trim()
      if (!name || !this.alliance) return
      try {
        await renameAlliance(this.alliance.id, name)
        await loadAllianceContext(this.alliance.id, true)
        await this.loadData()
        uni.showToast({ title: '名称已保存', icon: 'success' })
      } catch (err) {
        uni.showToast({ title: err.message || '保存失败', icon: 'none' })
      }
    },
    async generateShare() {
      if (!this.alliance || this.shareBusy) return
      this.shareBusy = true
      try {
        const result = await createAllianceShare(this.alliance.id, 30)
        this.shareToken = result.token
        this.shareExpiresAt = result.expires_at
        rememberAllianceShareToken(this.alliance.id, result.token, result.expires_at, 'invite')
        const links = await getAllianceShares(this.alliance.id)
        this.shareLinks = links.links || []
        uni.showToast({ title: '邀请已生成', icon: 'success' })
      } catch (err) {
        uni.showToast({ title: err.message || '生成失败', icon: 'none' })
      } finally {
        this.shareBusy = false
      }
    },
    copySharePath() {
      if (!this.shareToken) return
      uni.setClipboardData({
        data: `share_token=${this.shareToken}`,
        success: () => uni.showToast({ title: '邀请参数已复制', icon: 'success' })
      })
    },
    confirmLeave() {
      uni.showModal({
        title: '退出当前联盟',
        content: `确认退出${this.alliance.name}？`,
        confirmColor: '#d56b72',
        success: async res => {
          if (!res.confirm) return
          try {
            await leaveAlliance(this.alliance.id)
            const loaded = await loadAllianceContext(null, true)
            if (loaded.current) uni.switchTab({ url: '/pages/clan/clan' })
            else uni.switchTab({ url: '/pages/settings/settings' })
          } catch (err) {
            uni.showToast({ title: err.message || '退出失败', icon: 'none' })
          }
        }
      })
    },
    confirmArchive() {
      if (!this.alliance || this.alliance.role !== 'leader') return
      uni.showModal({
        title: '删除当前联盟',
        content: `请输入联盟名称“${this.alliance.name}”确认删除`,
        editable: true,
        placeholderText: '联盟名称',
        confirmColor: '#d56b72',
        success: async result => {
          if (!result.confirm) return
          try {
            await archiveAlliance(this.alliance.id, result.content)
            const loaded = await loadAllianceContext(null, true)
            if (loaded.current) uni.switchTab({ url: '/pages/clan/clan' })
            else uni.switchTab({ url: '/pages/settings/settings' })
            uni.showToast({ title: '联盟已删除', icon: 'success' })
          } catch (err) {
            uni.showToast({ title: err.message || '删除失败', icon: 'none' })
          }
        }
      })
    },
    roleLabel(value) { return ({ leader: '首领', admin: '管理', member: '成员' }[value] || value) },
    planStateLabel(value) { return ({ active: '有效', grace: '7天只读宽限期', legacy: '兼容权益', expired: '已到期', revoked: '已撤销' }[value] || value || '有效') },
    shortDate(value) { return value ? String(value).replace('T', ' ').slice(0, 16) : '' }
  }
}
</script>

<style>
.page { height: 100vh; display: flex; flex-direction: column; background: #0f0f23; color: #dce1ed; }
.content { flex: 1; min-height: 0; padding: 24rpx; box-sizing: border-box; }
.section-title { margin: 30rpx 8rpx 14rpx; color: #7f8aa2; font-size: 23rpx; }
.card { padding: 24rpx; border: 1rpx solid #292945; border-radius: 14rpx; background: #18182d; }
.summary-card { margin-top: 4rpx; }
.management-card { padding-top: 0; padding-bottom: 0; }
.management-row { min-height: 112rpx; display: flex; align-items: center; border-bottom: 1rpx solid #25253e; }
.management-row:last-child { border-bottom: 0; }
.management-icon { width: 54rpx; height: 54rpx; margin-right: 18rpx; display: flex; align-items: center; justify-content: center; flex-shrink: 0; border-radius: 12rpx; color: #71aff1; background: #202b42; font-size: 23rpx; font-weight: 700; }
.management-icon-league { color: #c9a766; background: #302c35; }
.management-arrow { margin-left: 16rpx; color: #657087; font-size: 34rpx; }
.title-row, .clan-row { display: flex; align-items: center; }
.title { color: #fff; font-size: 32rpx; font-weight: 700; }
.role { margin-left: 12rpx; color: #5fa8ff; font-size: 22rpx; }
.meta, .sub, .tip, .body { display: block; color: #788197; font-size: 22rpx; line-height: 1.6; }
.meta { margin-top: 8rpx; }
.clan-row { min-height: 92rpx; border-bottom: 1rpx solid #25253e; }
.clan-row:last-of-type { border-bottom: 0; }
.grow { flex: 1; min-width: 0; }
.name { display: block; overflow: hidden; color: #e5e8f0; font-size: 26rpx; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.state { margin-left: 12rpx; color: #91a0b9; font-size: 22rpx; }
.state-verified { color: #4bbda6; }.state-disputed { color: #d99a66; }.state-revoked { color: #c8797f; }
.primary-btn, .secondary-btn, .text-btn { margin-top: 20rpx; border: 0; border-radius: 10rpx; font-size: 24rpx; line-height: 2.4; }
.primary-btn { color: #fff; background: #315f9a; }.secondary-btn { color: #7eb8f6; background: #202b42; }.text-btn { color: #8995ad; background: transparent; }
.primary-btn::after, .secondary-btn::after, .text-btn::after { border: 0; }
.paid-add-form { margin-top: 18rpx; padding-top: 18rpx; border-top: 1rpx solid #25253e; }.input, .picker { margin-top: 12rpx; padding: 17rpx; border: 1rpx solid #30304d; border-radius: 9rpx; color: #dce1ed; background: #111126; font-size: 23rpx; }.picker { color: #a8b0c1; }
.rename-row { display: flex; align-items: center; margin-top: 14rpx; }.rename-row .input { margin-top: 0; }.mini-save { flex-shrink: 0; margin-left: 10rpx; padding: 5rpx 14rpx; border: 0; border-radius: 8rpx; color: #79b4f2; background: #202b42; font-size: 21rpx; line-height: 2.1; }.mini-save::after { border: 0; }
.tip { margin-top: 14rpx; }.body { color: #a6aec0; }
.remove { margin-left: 12rpx; color: #bd7479; font-size: 21rpx; }
.restore { margin-left: 12rpx; color: #69a7e6; font-size: 21rpx; }
.list-entry-card { padding-top: 14rpx; padding-bottom: 14rpx; }.list-entry-copy { min-height: 88rpx; display: flex; align-items: center; }.list-entry-btn { flex-shrink: 0; margin: 0 0 0 20rpx; padding: 0 22rpx; border: 1rpx solid #324966; border-radius: 9rpx; color: #82b7eb; background: #202b42; font-size: 21rpx; line-height: 2.3; }.list-entry-btn::after { border: 0; }.share-record-entry { margin-top: 22rpx; padding-top: 18rpx; border-top: 1rpx solid #25253e; }
.leave-section { margin-top: 36rpx; }.danger-btn { border: 1rpx solid #57363f; border-radius: 10rpx; color: #c9797f; background: transparent; font-size: 24rpx; line-height: 2.4; }.danger-btn::after { border: 0; }
.empty { padding: 120rpx 20rpx; color: #657087; font-size: 25rpx; text-align: center; }.empty.compact { padding: 36rpx 0; }
.bottom-space { height: 80rpx; }
</style>
