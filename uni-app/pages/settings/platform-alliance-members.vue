<template>
  <view class="page">
    <TopBar title="管理联盟成员" :show-back="true" :back-fallback="backFallback" />
    <scroll-view scroll-y class="content">
      <view v-if="loading" class="state">正在加载...</view>
      <template v-else-if="detail">
        <view class="summary-card">
          <view><text class="summary-title">{{ detail.alliance.name }}</text><text class="summary-sub">有效成员 {{ activeCount }} 人 · 全部记录 {{ members.length }} 条</text></view>
          <text class="summary-role">超级管理</text>
        </view>

        <view class="section-title">通过 OpenID 添加成员</view>
        <view class="card add-card">
          <text class="body">平台管理员可向该联盟添加成员、管理员或新首领；设置新首领时，原首领自动变为管理员。</text>
          <input v-model="memberOpenid" class="input" maxlength="200" placeholder="输入或粘贴用户 OpenID" placeholder-style="color:#59637a" />
          <view class="add-actions">
            <picker class="role-picker" :range="roleOptions" range-key="label" :value="addRoleIndex" @change="addRoleIndex = Number($event.detail.value) || 0">
              <view class="picker-field">添加为：{{ roleOptions[addRoleIndex].label }}⌄</view>
            </picker>
            <button class="add-btn" :loading="busy" :disabled="busy || !memberOpenid.trim()" @tap="addMember">添加成员</button>
          </view>
        </view>

        <view class="section-title">全部成员</view>
        <view class="search-box">
          <text class="search-icon">⌕</text>
          <input v-model="query" class="search-input" placeholder="搜索昵称、玩家标签、成员 ID 或权限" placeholder-style="color:#59637a" />
          <text v-if="query" class="search-clear" @tap="query = ''">清除</text>
        </view>
        <text class="result-count">显示 {{ filteredMembers.length }} 条</text>

        <view v-if="filteredMembers.length" class="member-list">
          <view v-for="member in filteredMembers" :key="member.id" class="member-card">
            <view class="member-head">
              <view class="grow">
                <text class="member-name">{{ displayName(member) }}</text>
                <text class="member-meta">{{ member.player_tag || '未绑定游戏账号' }} · 成员 ID {{ member.id }}</text>
              </view>
              <text :class="['member-status', 'member-status-' + member.status]">{{ statusLabel(member.status) }}</text>
            </view>
            <view class="member-actions">
              <picker v-if="member.status === 'active'" class="permission-picker" :range="roleOptions" range-key="label" :value="roleIndex(member.role)" @change="changeRole(member, $event)">
                <view class="permission-btn">权限：{{ roleLabel(member.role) }}⌄</view>
              </picker>
              <view v-else class="permission-btn passive">权限：{{ roleLabel(member.role) }}</view>
              <button v-if="member.status === 'active' && member.role !== 'leader'" class="remove-btn" @tap="confirmRemove(member)">移除成员</button>
            </view>
          </view>
        </view>
        <view v-else class="state compact">{{ query ? '没有匹配的成员' : '暂无成员记录' }}</view>
      </template>
      <view class="bottom-space"></view>
    </scroll-view>
  </view>
</template>

<script>
import TopBar from '@/components/TopBar.vue'
import { addPlatformAllianceMember, getPlatformAlliance, removePlatformAllianceMember, updatePlatformAllianceMemberRole } from '@/utils/api.js'

export default {
  components: { TopBar },
  data() {
    return {
      allianceId: null, loading: true, busy: false, detail: null, query: '', memberOpenid: '', addRoleIndex: 0,
      roleOptions: [{ key: 'member', label: '成员' }, { key: 'admin', label: '管理员' }, { key: 'leader', label: '首领' }]
    }
  },
  computed: {
    backFallback() { return `/pages/settings/platform-alliance-detail?id=${this.allianceId}` },
    members() { return this.detail ? this.detail.members : [] },
    activeCount() { return this.members.filter(item => item.status === 'active').length },
    filteredMembers() {
      const query = this.query.trim().toLowerCase()
      if (!query) return this.members
      return this.members.filter(member => [this.displayName(member), member.player_tag, String(member.id), this.roleLabel(member.role), this.statusLabel(member.status)]
        .some(value => String(value || '').toLowerCase().indexOf(query) >= 0))
    }
  },
  onLoad(options) { this.allianceId = Number(options && options.id) || null },
  async onShow() { if (this.allianceId) await this.loadData() },
  methods: {
    async loadData() {
      this.loading = true
      try { this.detail = await getPlatformAlliance(this.allianceId) }
      catch (err) { uni.showModal({ title: '成员加载失败', content: err.message || '请稍后重试', showCancel: false }) }
      finally { this.loading = false }
    },
    async addMember() {
      const openid = this.memberOpenid.trim()
      if (!openid || this.busy) return
      this.busy = true
      try {
        await addPlatformAllianceMember(this.allianceId, openid, this.roleOptions[this.addRoleIndex].key)
        this.memberOpenid = ''; this.addRoleIndex = 0; await this.loadData()
        uni.showToast({ title: '成员已添加', icon: 'success' })
      } catch (err) { uni.showToast({ title: err.message || '添加失败', icon: 'none' }) }
      finally { this.busy = false }
    },
    changeRole(member, event) {
      const selected = this.roleOptions[Number(event.detail.value) || 0]
      if (!selected || selected.key === member.role) return
      const apply = async () => {
        try { await updatePlatformAllianceMemberRole(this.allianceId, member.id, selected.key); await this.loadData(); uni.showToast({ title: '权限已更新', icon: 'success' }) }
        catch (err) { uni.showModal({ title: '更新失败', content: err.message || '请稍后重试', showCancel: false }) }
      }
      if (selected.key !== 'leader') return apply()
      uni.showModal({ title: '移交联盟首领', content: `确认将${this.displayName(member)}设为联盟首领？原首领将变为管理员。`, success: result => { if (result.confirm) apply() } })
    },
    confirmRemove(member) {
      uni.showModal({
        title: '移除联盟成员', content: `确认移除${this.displayName(member)}？`, confirmColor: '#c9797f',
        success: async result => {
          if (!result.confirm) return
          try { await removePlatformAllianceMember(this.allianceId, member.id); await this.loadData(); uni.showToast({ title: '成员已移除', icon: 'success' }) }
          catch (err) { uni.showToast({ title: err.message || '移除失败', icon: 'none' }) }
        }
      })
    },
    displayName(member) { return member.nickname || member.account_name || `微信用户${member.id}` },
    roleIndex(value) { const index = this.roleOptions.findIndex(item => item.key === value); return index < 0 ? 0 : index },
    roleLabel(value) { return ({ leader: '首领', admin: '管理员', member: '成员' }[value] || value) },
    statusLabel(value) { return ({ active: '有效', removed: '已移除', blocked: '已封禁', left: '已离开', invited: '待加入' }[value] || value) }
  }
}
</script>

<style>
.page { height: 100vh; display: flex; flex-direction: column; color: #dce1ed; background: #0f0f23; }.content { flex: 1; min-height: 0; padding: 24rpx; box-sizing: border-box; }.state { padding: 180rpx 24rpx; color: #717b91; font-size: 25rpx; text-align: center; }.state.compact { padding: 80rpx 24rpx; }
.summary-card, .card { padding: 24rpx; border: 1rpx solid #292945; border-radius: 14rpx; background: #18182d; }.summary-card { display: flex; align-items: center; justify-content: space-between; }.summary-title, .summary-sub, .body, .member-name, .member-meta, .result-count { display: block; }.summary-title { color: #f2f3f8; font-size: 30rpx; font-weight: 700; }.summary-sub { margin-top: 8rpx; color: #737d92; font-size: 21rpx; }.summary-role { color: #68a8e9; font-size: 22rpx; }
.section-title { margin: 30rpx 8rpx 14rpx; color: #7f8aa2; font-size: 23rpx; }.body { color: #9ea7ba; font-size: 21rpx; line-height: 1.65; }.input, .picker-field, .search-box { border: 1rpx solid #30304d; border-radius: 10rpx; color: #dce1ed; background: #111126; }.input { height: 84rpx; margin-top: 18rpx; padding: 0 20rpx; box-sizing: border-box; font-size: 23rpx; }.add-actions { display: flex; gap: 16rpx; margin-top: 16rpx; }.role-picker, .permission-picker { flex: 1; min-width: 0; }.picker-field { height: 78rpx; padding: 0 18rpx; box-sizing: border-box; color: #9fa9bc; font-size: 22rpx; line-height: 78rpx; }.add-btn { width: 190rpx; height: 78rpx; margin: 0; border: 0; border-radius: 10rpx; color: #fff; background: #315f9a; font-size: 22rpx; line-height: 78rpx; }.add-btn::after { border: 0; }.add-btn[disabled] { color: #6f7890; background: #222b40; }
.search-box { height: 82rpx; display: flex; align-items: center; padding: 0 18rpx; box-sizing: border-box; }.search-icon { margin-right: 12rpx; color: #71809a; font-size: 30rpx; }.search-input { flex: 1; min-width: 0; color: #dce1ed; font-size: 23rpx; }.search-clear { margin-left: 14rpx; color: #74a9df; font-size: 21rpx; }.result-count { margin: 12rpx 8rpx 0; color: #657087; font-size: 20rpx; }
.member-list { margin-top: 16rpx; }.member-card { margin-bottom: 16rpx; padding: 24rpx; border: 1rpx solid #292945; border-radius: 14rpx; background: #18182d; }.member-head { display: flex; align-items: center; }.grow { flex: 1; min-width: 0; }.member-name { overflow: hidden; color: #e7e9f0; font-size: 27rpx; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }.member-meta { margin-top: 7rpx; color: #69738a; font-size: 20rpx; }.member-status { margin-left: 14rpx; padding: 8rpx 12rpx; border-radius: 8rpx; color: #8a93a5; background: #282a38; font-size: 19rpx; }.member-status-active { color: #62b49e; background: #203432; }.member-status-blocked, .member-status-removed { color: #bc7a80; background: #35252e; }
.member-actions { display: flex; gap: 20rpx; margin-top: 20rpx; padding-top: 18rpx; border-top: 1rpx solid #292945; }.permission-btn, .remove-btn { height: 70rpx; box-sizing: border-box; display: flex; align-items: center; justify-content: center; border: 1rpx solid #32445d; border-radius: 10rpx; font-size: 21rpx; }.permission-btn { padding: 0 18rpx; color: #82b7eb; background: #202b42; }.permission-btn.passive { flex: 1; color: #8792a7; background: #1c2131; }.remove-btn { width: 176rpx; margin: 0; color: #c9858b; background: rgba(120,45,54,.14); border-color: rgba(184,95,105,.34); line-height: 70rpx; }.remove-btn::after { border: 0; }.bottom-space { height: 80rpx; }
</style>
