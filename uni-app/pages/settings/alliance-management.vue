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

        <view class="section-title">加入申请</view>
        <view class="card">
          <view v-for="request in joinRequests" :key="request.id" class="request-row">
            <view class="grow">
              <text class="name">{{ request.display_name }}</text>
              <text class="sub">申请于 {{ shortDate(request.created_at) }}</text>
            </view>
            <text class="review reject" @tap="reviewRequest(request, 'reject')">拒绝</text>
            <text class="review approve" @tap="reviewRequest(request, 'approve')">同意</text>
          </view>
          <view v-if="!joinRequests.length" class="empty compact">暂无待处理申请</view>
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
          <view v-if="shareLinks.length" class="share-history">
            <view v-for="link in shareLinks" :key="link.id" class="share-row">
              <view class="grow">
                <text class="sub">邀请 #{{ link.id }} · {{ shareStatusLabel(link.status) }} · 已加入 {{ link.use_count }} 人</text>
                <text class="sub">有效期至 {{ shortDate(link.expires_at) }}</text>
              </view>
              <text v-if="link.can_revoke && link.status === 'active'" class="remove" @tap="confirmRevokeShare(link)">撤销</text>
            </view>
            <text class="tip">后台只保存令牌摘要，历史令牌不能再次显示。</text>
          </view>
        </view>

        <template v-if="canManageMembers">
          <view class="section-title">联盟成员</view>
          <view class="card member-card">
            <view class="openid-add">
              <text class="body">通过用户复制给你的 OpenID 添加成员。首领可直接添加管理员，管理员只能添加普通成员。</text>
              <input v-model="memberOpenid" class="input" maxlength="200" placeholder="粘贴用户 OpenID" placeholder-style="color:#59637a" />
              <view class="openid-actions">
                <picker :range="availableAddRoles" range-key="label" :value="addRoleIndex" @change="changeAddRole">
                  <view class="picker add-role-picker">添加为：{{ availableAddRoles[addRoleIndex].label }}⌄</view>
                </picker>
                <button class="mini-save add-member-btn" :loading="memberAddBusy" :disabled="memberAddBusy || !memberOpenid.trim()" @tap="addMemberByOpenid">添加</button>
              </view>
            </view>
            <view v-for="member in members" :key="member.id" class="member-row">
              <view class="grow">
                <text class="name">{{ member.display_name }}</text>
                <text class="sub">{{ member.player_tag || '未绑定游戏账号' }} · {{ statusLabel(member.status) }}</text>
              </view>
              <picker
                v-if="alliance.role === 'leader' && member.role !== 'leader' && member.status === 'active'"
                :range="roleOptions"
                range-key="label"
                :value="roleIndex(member.role)"
                @change="changeRole(member, $event)"
              >
                <text class="role-chip">{{ roleLabel(member.role) }}⌄</text>
              </picker>
              <text v-else class="role-chip passive">{{ roleLabel(member.role) }}</text>
              <text
                v-if="member.role !== 'leader' && member.status === 'active' && (alliance.role === 'leader' || member.role === 'member')"
                class="remove"
                @tap="confirmRemove(member)"
              >移除</text>
            </view>
            <view v-if="!members.length" class="empty compact">暂无成员</view>
          </view>
        </template>

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
  addAllianceUserMember,
  archiveAlliance,
  createAllianceShare,
  getAllianceJoinRequests,
  getAllianceShares,
  getAllianceUserMembers,
  leaveAlliance,
  removeAllianceUser,
  renameAlliance,
  reviewAllianceJoinRequest,
  revokeAllianceShare,
  updateAllianceUserRole
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
      shareBusy: false,
      memberOpenid: '',
      memberAddBusy: false,
      addRoleIndex: 0,
      roleOptions: [
        { key: 'member', label: '成员' },
        { key: 'admin', label: '管理' },
        { key: 'leader', label: '首领' }
      ]
    }
  },
  computed: {
    canManageMembers() {
      return this.alliance && ['admin', 'leader'].indexOf(this.alliance.role) >= 0
    },
    availableAddRoles() {
      const roles = [{ key: 'member', label: '成员' }]
      if (this.alliance && this.alliance.role === 'leader') roles.push({ key: 'admin', label: '管理员' })
      return roles
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
    async reviewRequest(request, action) {
      if (!request || !this.alliance) return
      try {
        await reviewAllianceJoinRequest(this.alliance.id, request.id, action)
        await this.loadData()
        uni.showToast({ title: action === 'approve' ? '已同意' : '已拒绝', icon: 'success' })
      } catch (err) {
        uni.showToast({ title: err.message || '处理失败', icon: 'none' })
      }
    },
    changeAddRole(event) {
      this.addRoleIndex = Number(event.detail.value) || 0
    },
    async addMemberByOpenid() {
      const targetOpenid = this.memberOpenid.trim()
      const selected = this.availableAddRoles[this.addRoleIndex] || this.availableAddRoles[0]
      if (!targetOpenid || !this.alliance || this.memberAddBusy) return
      this.memberAddBusy = true
      try {
        await addAllianceUserMember(this.alliance.id, targetOpenid, selected.key)
        this.memberOpenid = ''
        this.addRoleIndex = 0
        await this.loadData()
        uni.showToast({ title: '成员已添加', icon: 'success' })
      } catch (err) {
        uni.showToast({ title: err.message || '添加失败', icon: 'none' })
      } finally {
        this.memberAddBusy = false
      }
    },
    copySharePath() {
      if (!this.shareToken) return
      uni.setClipboardData({
        data: `share_token=${this.shareToken}`,
        success: () => uni.showToast({ title: '邀请参数已复制', icon: 'success' })
      })
    },
    confirmRevokeShare(link) {
      uni.showModal({
        title: '撤销联盟邀请',
        content: '撤销后，尚未使用该链接的人将不能再加入联盟。',
        confirmColor: '#d56b72',
        success: async res => {
          if (!res.confirm) return
          try {
            await revokeAllianceShare(this.alliance.id, link.id)
            const result = await getAllianceShares(this.alliance.id)
            this.shareLinks = result.links || []
            uni.showToast({ title: '邀请已撤销', icon: 'success' })
          } catch (err) {
            uni.showToast({ title: err.message || '撤销失败', icon: 'none' })
          }
        }
      })
    },
    async changeRole(member, event) {
      const selected = this.roleOptions[Number(event.detail.value) || 0]
      if (!selected || selected.key === member.role) return
      if (selected.key === 'leader') {
        const confirmed = await new Promise(resolve => {
          uni.showModal({
            title: '移交联盟首领',
            content: `确认将首领移交给${member.display_name}？你将变为管理员。`,
            success: res => resolve(Boolean(res.confirm))
          })
        })
        if (!confirmed) return
      }
      try {
        await updateAllianceUserRole(this.alliance.id, member.id, selected.key)
        await loadAllianceContext(this.alliance.id, true)
        await this.loadData()
        uni.showToast({ title: '角色已更新', icon: 'success' })
      } catch (err) {
        uni.showToast({ title: err.message || '更新失败', icon: 'none' })
      }
    },
    confirmRemove(member) {
      uni.showModal({
        title: '移除联盟成员',
        content: `确认移除${member.display_name}？被移除后不能通过旧分享自动恢复。`,
        confirmColor: '#d56b72',
        success: async res => {
          if (!res.confirm) return
          try {
            await removeAllianceUser(this.alliance.id, member.id, false)
            await this.loadData()
          } catch (err) {
            uni.showToast({ title: err.message || '移除失败', icon: 'none' })
          }
        }
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
    roleIndex(value) { const index = this.roleOptions.findIndex(item => item.key === value); return index < 0 ? 0 : index },
    roleLabel(value) { return ({ leader: '首领', admin: '管理', member: '成员' }[value] || value) },
    statusLabel(value) { return ({ active: '有效', removed: '已移除', blocked: '已封禁', left: '已离开', invited: '待加入' }[value] || value) },
    shareStatusLabel(value) { return ({ active: '有效', revoked: '已撤销', expired: '已过期' }[value] || value) },
    planStateLabel(value) { return ({ active: '有效', legacy: '兼容权益', expired: '已到期', revoked: '已撤销' }[value] || value || '有效') },
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
.title-row, .clan-row, .member-row, .request-row { display: flex; align-items: center; }
.title { color: #fff; font-size: 32rpx; font-weight: 700; }
.role { margin-left: 12rpx; color: #5fa8ff; font-size: 22rpx; }
.meta, .sub, .tip, .body { display: block; color: #788197; font-size: 22rpx; line-height: 1.6; }
.meta { margin-top: 8rpx; }
.clan-row, .member-row, .request-row { min-height: 92rpx; border-bottom: 1rpx solid #25253e; }
.clan-row:last-of-type, .member-row:last-of-type, .request-row:last-of-type { border-bottom: 0; }
.grow { flex: 1; min-width: 0; }
.name { display: block; overflow: hidden; color: #e5e8f0; font-size: 26rpx; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.state, .role-chip { margin-left: 12rpx; color: #91a0b9; font-size: 22rpx; }
.state-verified { color: #4bbda6; }.state-disputed { color: #d99a66; }.state-revoked { color: #c8797f; }
.primary-btn, .secondary-btn, .text-btn { margin-top: 20rpx; border: 0; border-radius: 10rpx; font-size: 24rpx; line-height: 2.4; }
.primary-btn { color: #fff; background: #315f9a; }.secondary-btn { color: #7eb8f6; background: #202b42; }.text-btn { color: #8995ad; background: transparent; }
.primary-btn::after, .secondary-btn::after, .text-btn::after { border: 0; }
.paid-add-form { margin-top: 18rpx; padding-top: 18rpx; border-top: 1rpx solid #25253e; }.input, .picker { margin-top: 12rpx; padding: 17rpx; border: 1rpx solid #30304d; border-radius: 9rpx; color: #dce1ed; background: #111126; font-size: 23rpx; }.picker { color: #a8b0c1; }
.rename-row { display: flex; align-items: center; margin-top: 14rpx; }.rename-row .input { margin-top: 0; }.mini-save { flex-shrink: 0; margin-left: 10rpx; padding: 5rpx 14rpx; border: 0; border-radius: 8rpx; color: #79b4f2; background: #202b42; font-size: 21rpx; line-height: 2.1; }.mini-save::after { border: 0; }
.tip { margin-top: 14rpx; }.body { color: #a6aec0; }
.role-chip { padding: 8rpx 12rpx; border-radius: 8rpx; background: #22223a; }.role-chip.passive { background: transparent; }
.remove { margin-left: 12rpx; color: #bd7479; font-size: 21rpx; }
.review { margin-left: 18rpx; font-size: 22rpx; }.review.reject { color: #a47d82; }.review.approve { color: #69a7e6; }
.openid-add { margin-bottom: 12rpx; padding-bottom: 20rpx; border-bottom: 1rpx solid #25253e; }.openid-actions { display: flex; align-items: center; margin-top: 12rpx; }.add-role-picker { min-width: 220rpx; margin-top: 0; }.add-member-btn { margin-top: 0; }
.restore { margin-left: 12rpx; color: #69a7e6; font-size: 21rpx; }
.share-history { margin-top: 20rpx; border-top: 1rpx solid #25253e; }.share-row { display: flex; align-items: center; min-height: 82rpx; border-bottom: 1rpx solid #25253e; }
.leave-section { margin-top: 36rpx; }.danger-btn { border: 1rpx solid #57363f; border-radius: 10rpx; color: #c9797f; background: transparent; font-size: 24rpx; line-height: 2.4; }.danger-btn::after { border: 0; }
.empty { padding: 120rpx 20rpx; color: #657087; font-size: 25rpx; text-align: center; }.empty.compact { padding: 36rpx 0; }
.bottom-space { height: 80rpx; }
</style>
