<template>
  <view class="farm-page">
    <view v-if="loading" class="page-state">正在加载...</view>
    <view v-else-if="error" class="page-state">
      <text class="state-error">{{ error }}</text>
      <button class="small-button" @tap="load">重新加载</button>
    </view>
    <view v-else>
      <view class="section-head first-head">
        <view>
          <text class="section-title">部落联盟账号</text>
          <text class="section-desc">管理互刷系统的独立登录账号与角色</text>
        </view>
        <text class="section-count">{{ accounts.length }} 个</text>
      </view>

      <view class="form-card">
        <text class="form-title">创建独立账号</text>
        <input v-model="newAccount.username" class="input" placeholder="登录邮箱" maxlength="254" />
        <input v-model="newAccount.display_name" class="input" placeholder="部落联盟名称" maxlength="80" />
        <input v-model="newAccount.password" class="input" password placeholder="初始密码（至少 8 位）" maxlength="128" />
        <picker v-if="isCreator" :range="roleNames" :value="newAccountRoleIndex" @change="onNewAccountRole">
          <view class="picker-field">角色：{{ roleLabel(newAccount.role) }}<text>⌄</text></view>
        </picker>
        <button class="primary-button" :loading="saving" :disabled="saving" @tap="createAccount">创建账号</button>
      </view>

      <view class="search-box">
        <text class="search-icon">⌕</text>
        <input v-model="searchQuery" class="search-input" placeholder="搜索联盟名称、登录邮箱或角色" placeholder-style="color:#59637a" />
        <text v-if="searchQuery" class="search-clear" @tap="searchQuery = ''">清除</text>
      </view>
      <text v-if="searchQuery" class="result-count">找到 {{ filteredAccounts.length }} 个账号</text>

      <view v-if="!filteredAccounts.length" class="empty-card">{{ searchQuery ? '没有匹配的账号' : '暂未创建独立账号' }}</view>
      <view v-for="account in filteredAccounts" :key="account.id" class="data-card">
        <view class="card-main" @tap="openAccountClans(account)">
          <view class="card-copy">
            <text class="card-title">{{ account.display_name }}</text>
            <text class="card-meta">{{ account.username }} · {{ roleLabel(account.role) }}</text>
          </view>
          <view class="card-side">
            <text class="status-badge" :class="{ disabled: account.status !== 'active' }">{{ account.status === 'active' ? '启用' : '停用' }}</text>
            <text class="detail-arrow">›</text>
          </view>
        </view>
        <view v-if="canEditAccount(account)" class="card-actions">
          <picker v-if="canEditAccount(account) && isCreator" :range="roleNames" :value="roleIndex(account.role)" @change="changeRole(account, $event)">
            <view class="action-field">调整角色<text>⌄</text></view>
          </picker>
          <text v-if="canEditAccount(account)" class="action-link" @tap="toggleAccount(account)">{{ account.status === 'active' ? '停用' : '启用' }}</text>
          <text v-if="canEditAccount(account) && isCreator" class="action-link" @tap="resetPassword(account)">重置密码</text>
        </view>
      </view>
    </view>
    <view class="bottom-space"></view>
  </view>
</template>

<script>
import {
  createFarmAccount,
  getFarmAdminAccounts,
  getFarmMe,
  resetFarmAccountPassword,
  updateFarmAccount
} from '@/utils/api.js'

const ROLES = ['member', 'admin']

export default {
  data() {
    return {
      loading: true,
      hasLoaded: false,
      saving: false,
      error: '',
      me: {},
      accounts: [],
      searchQuery: '',
      newAccount: { username: '', display_name: '', password: '', role: 'member' }
    }
  },
  computed: {
    isCreator() { return this.me.role === 'creator' },
    roleNames() { return ROLES.map(this.roleLabel) },
    newAccountRoleIndex() { return this.roleIndex(this.newAccount.role) },
    filteredAccounts() {
      const query = this.searchQuery.trim().toLowerCase()
      if (!query) return this.accounts
      return this.accounts.filter(account => [
        account.display_name,
        account.username,
        this.roleLabel(account.role),
        account.status === 'active' ? '启用' : '停用'
      ].some(value => String(value || '').toLowerCase().includes(query)))
    }
  },
  onShow() { this.load() },
  methods: {
    roleLabel(role) { return ({ creator: '创建者', admin: '管理员', member: '成员' })[role] || '成员' },
    roleIndex(role) { return Math.max(0, ROLES.indexOf(role)) },
    canEditAccount(account) {
      if (account.role === 'creator') return false
      if (this.isCreator) return true
      return account.role !== 'creator'
    },
    async load() {
      const initialLoad = !this.hasLoaded
      if (initialLoad) {
        this.loading = true
        this.error = ''
      }
      try {
        this.me = await getFarmMe()
        if (!['creator', 'admin'].includes(this.me.role)) throw new Error('当前账号没有账号管理权限')
        const result = await getFarmAdminAccounts()
        this.accounts = result.accounts || []
        this.error = ''
        this.hasLoaded = true
      } catch (e) {
        if (initialLoad) this.error = e.message || '加载失败'
        else uni.showToast({ title: e.message || '刷新失败', icon: 'none' })
      } finally {
        if (initialLoad) this.loading = false
      }
    },
    async createAccount() {
      if (this.saving) return
      const payload = {
        username: this.newAccount.username.trim(),
        display_name: this.newAccount.display_name.trim(),
        password: this.newAccount.password,
        role: this.isCreator ? this.newAccount.role : 'member'
      }
      if (!payload.username || !payload.display_name || !payload.password) {
        uni.showToast({ title: '请填写完整账号信息', icon: 'none' })
        return
      }
      this.saving = true
      try {
        await createFarmAccount(payload)
        this.newAccount = { username: '', display_name: '', password: '', role: 'member' }
        await this.load()
        uni.showToast({ title: '账号已创建', icon: 'success' })
      } catch (e) {
        uni.showModal({ title: '创建失败', content: e.message, showCancel: false })
      } finally { this.saving = false }
    },
    onNewAccountRole(event) { this.newAccount.role = ROLES[Number(event.detail.value)] || 'member' },
    openAccountClans(account) {
      uni.navigateTo({ url: `/pages/farm/admin-account-clans?account_id=${encodeURIComponent(account.id)}` })
    },
    async changeRole(account, event) {
      const role = ROLES[Number(event.detail.value)]
      if (!role || role === account.role) return
      await this.runUpdate(() => updateFarmAccount(account.id, { role }))
    },
    async toggleAccount(account) {
      await this.runUpdate(() => updateFarmAccount(account.id, { status: account.status === 'active' ? 'disabled' : 'active' }))
    },
    resetPassword(account) {
      uni.showModal({
        title: `重置 ${account.display_name} 密码`,
        editable: true,
        placeholderText: '输入至少 8 位的新密码',
        success: result => {
          if (result.confirm && result.content) this.runUpdate(() => resetFarmAccountPassword(account.id, result.content.trim()))
        }
      })
    },
    async runUpdate(action) {
      if (this.saving) return
      this.saving = true
      try {
        await action()
        await this.load()
      } catch (e) {
        uni.showModal({ title: '操作失败', content: e.message, showCancel: false })
      } finally { this.saving = false }
    }
  }
}
</script>

<style>
.farm-page { min-height: 100vh; padding: 28rpx 26rpx; box-sizing: border-box; background: #0f0f23; color: #eef1f8; }.page-state { display: flex; min-height: 70vh; flex-direction: column; align-items: center; justify-content: center; gap: 24rpx; color: #7f899f; font-size: 26rpx; }.state-error { color: #d78383; }.small-button { padding: 0 32rpx; border: 1rpx solid #31537d; border-radius: 12rpx; background: transparent; color: #76aee6; font-size: 24rpx; }
.section-head { display: flex; align-items: flex-start; justify-content: space-between; padding: 30rpx 4rpx 18rpx; }.first-head { padding-top: 4rpx; }.section-title, .section-desc { display: block; }.section-title { font-size: 29rpx; font-weight: 650; }.section-desc { margin-top: 7rpx; color: #717c93; font-size: 21rpx; }.section-count { flex-shrink: 0; margin-left: 18rpx; color: #687188; font-size: 22rpx; }
.form-card, .data-card, .empty-card { margin-bottom: 20rpx; border: 1rpx solid #2a3152; border-radius: 18rpx; background: #191a31; }.form-card { padding: 26rpx; }.form-title { display: block; margin-bottom: 20rpx; font-size: 27rpx; font-weight: 600; }.input, .picker-field { height: 76rpx; margin-bottom: 16rpx; padding: 0 20rpx; border: 1rpx solid #30375b; border-radius: 12rpx; box-sizing: border-box; background: #121326; color: #e9edf6; font-size: 25rpx; }.picker-field { display: flex; align-items: center; justify-content: space-between; color: #aeb7ca; }
.search-box { display: flex; height: 82rpx; align-items: center; margin-bottom: 20rpx; padding: 0 18rpx; border: 1rpx solid #2a3152; border-radius: 14rpx; box-sizing: border-box; background: #15162b; }.search-icon { flex-shrink: 0; margin-right: 12rpx; color: #71809a; font-size: 30rpx; }.search-input { flex: 1; min-width: 0; color: #e6eaf3; font-size: 23rpx; }.search-clear { flex-shrink: 0; margin-left: 14rpx; color: #74a9df; font-size: 21rpx; }.result-count { display: block; margin: -8rpx 8rpx 18rpx; color: #657087; font-size: 20rpx; }.empty-card { padding: 60rpx 20rpx; color: #677087; font-size: 24rpx; text-align: center; }
.primary-button { display: flex; height: 78rpx; align-items: center; justify-content: center; border-radius: 12rpx; background: #397fc0; color: #fff; font-size: 26rpx; font-weight: 600; }.primary-button::after { border: 0; }.data-card { overflow: hidden; }.card-main { display: flex; align-items: center; justify-content: space-between; padding: 25rpx; }.card-copy { min-width: 0; }.card-title, .card-meta { display: block; }.card-title { overflow: hidden; font-size: 28rpx; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }.card-meta { margin-top: 8rpx; color: #747e96; font-size: 21rpx; }.card-side { display: flex; flex-shrink: 0; align-items: center; margin-left: 18rpx; }.status-badge { flex-shrink: 0; padding: 6rpx 14rpx; border-radius: 18rpx; background: rgba(67,170,115,.14); color: #6fc595; font-size: 21rpx; }.status-badge.disabled { background: rgba(193,107,110,.12); color: #be777b; }.detail-arrow { margin-left: 14rpx; color: #606b83; font-size: 34rpx; line-height: 1; }
.card-actions { display: flex; min-height: 70rpx; align-items: center; justify-content: flex-end; gap: 24rpx; padding: 0 25rpx; border-top: 1rpx solid #282e4d; color: #8190ab; font-size: 23rpx; }.action-field { display: flex; align-items: center; gap: 12rpx; padding: 16rpx 0; }.action-link { padding: 18rpx 0; color: #77aee3; }.bottom-space { height: 50rpx; }
</style>
