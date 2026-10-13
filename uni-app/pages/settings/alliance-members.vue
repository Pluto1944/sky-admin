<template>
  <view class="page">
    <TopBar title="管理成员" :show-back="true" back-fallback="/pages/settings/alliance-management" />
    <scroll-view scroll-y class="content">
      <view v-if="loading" class="state">正在加载...</view>
      <template v-else-if="alliance">
        <view class="summary-card">
          <view>
            <text class="summary-title">{{ alliance.name }}</text>
            <text class="summary-sub">有效成员 {{ activeCount }} 人 · 全部记录 {{ members.length }} 条</text>
          </view>
          <text class="summary-role">{{ alliance.role_label || roleLabel(alliance.role) }}</text>
        </view>

        <view class="section-title">通过 OpenID 添加成员</view>
        <view class="card add-card">
          <text class="body">输入用户复制给你的 OpenID，并选择加入后的权限。首领可添加管理员，管理员只能添加普通成员。</text>
          <input v-model="memberOpenid" class="input" maxlength="200" placeholder="输入或粘贴用户 OpenID" placeholder-style="color:#59637a" />
          <view class="add-actions">
            <picker class="role-picker" :range="availableAddRoles" range-key="label" :value="addRoleIndex" @change="changeAddRole">
              <view class="picker-field">添加为：{{ availableAddRoles[addRoleIndex].label }}⌄</view>
            </picker>
            <button class="add-btn" :loading="memberAddBusy" :disabled="memberAddBusy || !memberOpenid.trim()" @tap="addMemberByOpenid">添加成员</button>
          </view>
        </view>

        <view class="section-title">全部成员</view>
        <view class="search-box">
          <text class="search-icon">⌕</text>
          <input v-model="memberQuery" class="search-input" placeholder="搜索昵称、玩家标签、成员 ID 或权限" placeholder-style="color:#59637a" />
          <text v-if="memberQuery" class="search-clear" @tap="memberQuery = ''">清除</text>
        </view>
        <text class="result-count">显示 {{ filteredMembers.length }} 条</text>

        <view v-if="filteredMembers.length" class="member-list">
          <view v-for="member in filteredMembers" :key="member.id" class="member-card">
            <view class="member-head">
              <view class="grow">
                <text class="member-name">{{ member.display_name }}</text>
                <text class="member-meta">{{ member.player_tag || '未绑定游戏账号' }} · 成员 ID {{ member.id }}</text>
              </view>
              <text :class="['member-status', 'member-status-' + member.status]">{{ statusLabel(member.status) }}</text>
            </view>
            <view class="member-actions">
              <picker
                v-if="alliance.role === 'leader' && member.role !== 'leader' && member.status === 'active'"
                class="permission-picker"
                :range="roleOptions"
                range-key="label"
                :value="roleIndex(member.role)"
                @change="changeRole(member, $event)"
              >
                <view class="permission-btn">权限：{{ roleLabel(member.role) }}⌄</view>
              </picker>
              <view v-else class="permission-btn passive">权限：{{ roleLabel(member.role) }}</view>
              <button
                v-if="member.role !== 'leader' && member.status === 'active' && (alliance.role === 'leader' || member.role === 'member')"
                class="remove-btn"
                @tap="confirmRemove(member)"
              >移除成员</button>
            </view>
          </view>
        </view>
        <view v-else class="state compact">{{ memberQuery ? '没有匹配的成员' : '暂无成员记录' }}</view>
      </template>
      <view v-else class="state">请先创建或加入联盟</view>
      <view class="bottom-space"></view>
    </scroll-view>
  </view>
</template>

<script>
import TopBar from '@/components/TopBar.vue'
import {
  addAllianceUserMember,
  getAllianceUserMembers,
  removeAllianceUser,
  updateAllianceUserRole
} from '@/utils/api.js'
import { getCurrentAlliance, loadAllianceContext } from '@/utils/alliance.js'

export default {
  components: { TopBar },
  data() {
    return {
      loading: true,
      alliance: null,
      members: [],
      memberQuery: '',
      memberOpenid: '',
      memberAddBusy: false,
      addRoleIndex: 0,
      roleOptions: [
        { key: 'member', label: '成员' },
        { key: 'admin', label: '管理员' },
        { key: 'leader', label: '首领' }
      ]
    }
  },
  computed: {
    activeCount() {
      return this.members.filter(item => item.status === 'active').length
    },
    availableAddRoles() {
      const roles = [{ key: 'member', label: '成员' }]
      if (this.alliance && this.alliance.role === 'leader') roles.push({ key: 'admin', label: '管理员' })
      return roles
    },
    filteredMembers() {
      const query = this.memberQuery.trim().toLowerCase()
      if (!query) return this.members
      return this.members.filter(member => {
        const fields = [
          member.display_name,
          member.player_tag,
          String(member.id),
          this.roleLabel(member.role),
          this.statusLabel(member.status)
        ]
        return fields.some(value => String(value || '').toLowerCase().indexOf(query) >= 0)
      })
    }
  },
  async onShow() {
    await this.loadData()
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
        const result = await getAllianceUserMembers(this.alliance.id)
        this.members = result.members || []
      } catch (err) {
        uni.showToast({ title: err.message || '加载失败', icon: 'none' })
      } finally {
        this.loading = false
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
    async changeRole(member, event) {
      const selected = this.roleOptions[Number(event.detail.value) || 0]
      if (!selected || selected.key === member.role) return
      if (selected.key === 'leader') {
        const confirmed = await new Promise(resolve => {
          uni.showModal({
            title: '移交联盟首领',
            content: `确认将首领移交给${member.display_name}？你将变为管理员。`,
            success: result => resolve(Boolean(result.confirm))
          })
        })
        if (!confirmed) return
      }
      try {
        await updateAllianceUserRole(this.alliance.id, member.id, selected.key)
        const loaded = await loadAllianceContext(this.alliance.id, true)
        this.alliance = loaded.current || getCurrentAlliance()
        await this.loadData()
        uni.showToast({ title: '权限已更新', icon: 'success' })
      } catch (err) {
        uni.showToast({ title: err.message || '更新失败', icon: 'none' })
      }
    },
    confirmRemove(member) {
      uni.showModal({
        title: '移除联盟成员',
        content: `确认移除${member.display_name}？被移除后不能通过旧分享自动恢复。`,
        confirmColor: '#c9797f',
        success: async result => {
          if (!result.confirm) return
          try {
            await removeAllianceUser(this.alliance.id, member.id, false)
            await this.loadData()
            uni.showToast({ title: '成员已移除', icon: 'success' })
          } catch (err) {
            uni.showToast({ title: err.message || '移除失败', icon: 'none' })
          }
        }
      })
    },
    roleIndex(value) {
      const index = this.roleOptions.findIndex(item => item.key === value)
      return index < 0 ? 0 : index
    },
    roleLabel(value) {
      return ({ leader: '首领', admin: '管理员', member: '成员' }[value] || value)
    },
    statusLabel(value) {
      return ({ active: '有效', removed: '已移除', blocked: '已封禁', left: '已离开', invited: '待加入' }[value] || value)
    }
  }
}
</script>

<style>
.page { height: 100vh; display: flex; flex-direction: column; color: #dce1ed; background: #0f0f23; }.content { flex: 1; min-height: 0; padding: 24rpx; box-sizing: border-box; }.state { padding: 180rpx 24rpx; color: #717b91; font-size: 25rpx; text-align: center; }.state.compact { padding: 80rpx 24rpx; }
.summary-card, .card { padding: 24rpx; border: 1rpx solid #292945; border-radius: 14rpx; background: #18182d; }.summary-card { display: flex; align-items: center; justify-content: space-between; }.summary-title, .summary-sub, .body, .member-name, .member-meta, .result-count { display: block; }.summary-title { color: #f2f3f8; font-size: 30rpx; font-weight: 700; }.summary-sub { margin-top: 8rpx; color: #737d92; font-size: 21rpx; }.summary-role { color: #68a8e9; font-size: 22rpx; }
.section-title { margin: 30rpx 8rpx 14rpx; color: #7f8aa2; font-size: 23rpx; }.body { color: #9ea7ba; font-size: 21rpx; line-height: 1.65; }.input, .picker-field, .search-box { border: 1rpx solid #30304d; border-radius: 10rpx; color: #dce1ed; background: #111126; }.input { height: 84rpx; margin-top: 18rpx; padding: 0 20rpx; box-sizing: border-box; font-size: 23rpx; }.add-actions { display: flex; gap: 16rpx; margin-top: 16rpx; }.role-picker { flex: 1; min-width: 0; }.picker-field { height: 78rpx; padding: 0 18rpx; box-sizing: border-box; color: #9fa9bc; font-size: 22rpx; line-height: 78rpx; }.add-btn { width: 190rpx; height: 78rpx; margin: 0; border: 0; border-radius: 10rpx; color: #fff; background: #315f9a; font-size: 22rpx; line-height: 78rpx; }.add-btn::after { border: 0; }.add-btn[disabled] { color: #6f7890; background: #222b40; }
.search-box { height: 82rpx; display: flex; align-items: center; padding: 0 18rpx; box-sizing: border-box; }.search-icon { flex-shrink: 0; margin-right: 12rpx; color: #71809a; font-size: 30rpx; }.search-input { flex: 1; min-width: 0; color: #dce1ed; font-size: 23rpx; }.search-clear { flex-shrink: 0; margin-left: 14rpx; color: #74a9df; font-size: 21rpx; }.result-count { margin: 12rpx 8rpx 0; color: #657087; font-size: 20rpx; }
.member-list { margin-top: 16rpx; }.member-card { margin-bottom: 16rpx; padding: 24rpx; border: 1rpx solid #292945; border-radius: 14rpx; background: #18182d; }.member-head { display: flex; align-items: center; }.grow { flex: 1; min-width: 0; }.member-name { overflow: hidden; color: #e7e9f0; font-size: 27rpx; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }.member-meta { margin-top: 7rpx; color: #69738a; font-size: 20rpx; }.member-status { flex-shrink: 0; margin-left: 14rpx; padding: 8rpx 12rpx; border-radius: 8rpx; color: #8a93a5; background: #282a38; font-size: 19rpx; }.member-status-active { color: #62b49e; background: #203432; }.member-status-blocked, .member-status-removed { color: #bc7a80; background: #35252e; }
.member-actions { display: flex; gap: 20rpx; margin-top: 20rpx; padding-top: 18rpx; border-top: 1rpx solid #292945; }.permission-picker { flex: 1; min-width: 0; }.permission-btn, .remove-btn { height: 70rpx; box-sizing: border-box; display: flex; align-items: center; justify-content: center; border: 1rpx solid #32445d; border-radius: 10rpx; font-size: 21rpx; }.permission-btn { padding: 0 18rpx; color: #82b7eb; background: #202b42; }.permission-btn.passive { color: #8792a7; background: #1c2131; }.remove-btn { width: 176rpx; margin: 0; color: #c9858b; background: rgba(120, 45, 54, .14); border-color: rgba(184, 95, 105, .34); line-height: 70rpx; }.remove-btn::after { border: 0; }.bottom-space { height: 80rpx; }
</style>
