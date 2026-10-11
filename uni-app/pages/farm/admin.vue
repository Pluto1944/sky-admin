<template>
  <view class="farm-page">
    <view v-if="loading" class="page-state">正在加载...</view>
    <view v-else-if="error" class="page-state">
      <text class="state-error">{{ error }}</text>
      <button class="small-button" @tap="load">重新加载</button>
    </view>
    <view v-else>
      <view class="identity-card">
        <view>
          <text class="identity-name">{{ me.display_name }}</text>
          <text class="identity-meta">{{ roleLabel(me.role) }} · {{ me.username }}</text>
        </view>
        <text class="logout-link" @tap="logout">退出</text>
      </view>

      <view v-if="isManager" class="round-admin-card">
        <view class="section-head round-head">
          <text class="section-title">当前互刷场次</text>
          <text v-if="roundSummary.round" class="section-count">{{ roundStatus(roundSummary.round.status) }}</text>
        </view>
        <view v-if="roundSummary.round && !creatingNextRound" class="round-current">
          <text class="round-time">{{ formatRoundTime(roundSummary.round.scheduled_at_beijing) }}</text>
          <text class="round-progress">开始搜战时间</text>
          <text class="round-progress">全联盟登记 {{ roundSummary.registered_count }}/{{ roundSummary.total_count }}</text>
          <button v-if="roundSummary.round.status === 'scheduled'" class="primary-button round-button" :loading="saving" @tap="openRound">开放本轮</button>
          <button v-if="roundSummary.round.status === 'completed'" class="primary-button round-button" @tap="creatingNextRound = true">创建下一场</button>
          <button v-if="isCreator && roundSummary.round.status !== 'cancelled'" class="danger-button" @tap="cancelRound">撤销整场</button>
          <text class="form-tip">登记功能是否可用由独立灰度开关控制；所有撤销都会保留原始流水。</text>
          <view v-if="roundMatches.length" class="round-results">
            <view v-for="item in roundMatches" :key="item.match_id" class="round-result-row">
              <view>
                <text class="result-title">{{ item.clan_name }} · {{ registrationLabel(item.registration_status) }}</text>
                <text class="result-meta">匹配 #{{ item.match_id }} · {{ item.opponent_name || item.opponent_tag || '-' }}</text>
              </view>
              <text v-if="isCreator && item.registration_status !== 'revoked'" class="action-link" @tap="revokeMatch(item)">撤销</text>
            </view>
          </view>
        </view>
        <view v-else class="round-create">
          <view class="datetime-row">
            <picker mode="date" :value="roundDate" @change="roundDate = $event.detail.value">
              <view class="picker-field">{{ roundDate || '选择日期' }}</view>
            </picker>
            <picker mode="time" :value="roundTime" @change="roundTime = $event.detail.value">
              <view class="picker-field">{{ roundTime || '选择时间' }}</view>
            </picker>
          </view>
          <button class="primary-button" :loading="saving" :disabled="saving" @tap="createRound">创建场次</button>
          <text class="form-tip">请按北京时间录入联盟统一开始搜战的时间。</text>
        </view>
      </view>

      <view v-if="isManager" class="tabs">
        <view class="tab" :class="{ active: tab === 'clans' }" @tap="tab = 'clans'">部落归属</view>
        <view class="tab" :class="{ active: tab === 'accounts' }" @tap="tab = 'accounts'">账号管理</view>
      </view>

      <view v-if="!isManager || tab === 'clans'">
        <view class="section-head">
          <text class="section-title">{{ isManager ? '全部互刷部落' : '我的互刷部落' }}</text>
          <text class="section-count">{{ clans.length }} 个</text>
        </view>

        <view v-if="isManager" class="form-card">
          <text class="form-title">添加互刷部落</text>
          <input v-model="newClan.clan_tag" class="input" placeholder="部落标签，例如 #ABC123" maxlength="16" />
          <picker :range="activeAccountNames" :value="newClanAccountIndex" @change="onNewClanAccount">
            <view class="picker-field">{{ selectedNewClanAccountName || '选择归属账号' }}<text>⌄</text></view>
          </picker>
          <button class="primary-button" :loading="saving" :disabled="saving" @tap="createClan">添加并验证</button>
          <text class="form-tip">部落名称来自服务器已同步的官方资料，不接受手工伪造。</text>
        </view>

        <view v-if="!clans.length" class="empty-card">暂未绑定互刷部落</view>
        <view v-for="clan in clans" :key="clan.id" class="data-card">
          <view class="card-main">
            <view class="card-copy">
              <text class="card-title">{{ clan.clan_name }}</text>
              <text class="card-meta">{{ clan.clan_tag }} · 当前积分 {{ clan.score }}</text>
            </view>
            <text class="status-badge" :class="{ disabled: clan.status !== 'active' }">{{ clan.status === 'active' ? '启用' : '停用' }}</text>
          </view>
          <view v-if="isManager" class="card-actions">
            <picker :range="activeAccountNames" :value="accountIndex(clan.account_id)" @change="transferClan(clan, $event)">
              <view class="action-field">归属：{{ accountName(clan.account_id) }}<text>⌄</text></view>
            </picker>
            <text class="action-link" @tap="toggleClan(clan)">{{ clan.status === 'active' ? '停用' : '启用' }}</text>
          </view>
        </view>
      </view>

      <view v-if="isManager && tab === 'accounts'">
        <view class="section-head">
          <text class="section-title">部落联盟账号</text>
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

        <view v-for="account in accounts" :key="account.id" class="data-card">
          <view class="card-main">
            <view class="card-copy">
              <text class="card-title">{{ account.display_name }}</text>
              <text class="card-meta">{{ account.username }} · {{ roleLabel(account.role) }}</text>
            </view>
            <text class="status-badge" :class="{ disabled: account.status !== 'active' }">{{ account.status === 'active' ? '启用' : '停用' }}</text>
          </view>
          <view v-if="canEditAccount(account)" class="card-actions">
            <picker v-if="isCreator" :range="roleNames" :value="roleIndex(account.role)" @change="changeRole(account, $event)">
              <view class="action-field">调整角色<text>⌄</text></view>
            </picker>
            <text class="action-link" @tap="toggleAccount(account)">{{ account.status === 'active' ? '停用' : '启用' }}</text>
            <text v-if="isCreator" class="action-link" @tap="resetPassword(account)">重置密码</text>
          </view>
        </view>
      </view>
    </view>
    <view class="bottom-space"></view>
  </view>
</template>

<script>
import {
  createFarmAccount,
  createFarmClan,
  createFarmRound,
  cancelFarmRound,
  farmLogout,
  getFarmAdminAccounts,
  getFarmAdminClans,
  getFarmClans,
  getFarmDashboard,
  getFarmMe,
  getFarmRoundResults,
  resetFarmAccountPassword,
  revokeFarmMatch,
  transferFarmClan,
  updateFarmAccount,
  updateFarmClan,
  updateFarmRound
} from '@/utils/api.js'

const ROLES = ['member', 'admin']

export default {
  data() {
    return {
      loading: true,
      saving: false,
      error: '',
      tab: 'clans',
      me: {},
      accounts: [],
      clans: [],
      roundSummary: { round: null, registered_count: 0, total_count: 0, clans: [] },
      roundDate: '',
      roundTime: '11:00',
      creatingNextRound: false,
      newAccount: { username: '', display_name: '', password: '', role: 'member' },
      newClan: { clan_tag: '', account_id: null }
    }
  },
  computed: {
    isManager() { return this.me.role === 'creator' || this.me.role === 'admin' },
    isCreator() { return this.me.role === 'creator' },
    activeAccounts() { return this.accounts.filter(item => item.status === 'active') },
    activeAccountNames() { return this.activeAccounts.map(item => item.display_name) },
    newClanAccountIndex() {
      return Math.max(0, this.activeAccounts.findIndex(item => Number(item.id) === Number(this.newClan.account_id)))
    },
    selectedNewClanAccountName() {
      const item = this.activeAccounts[this.newClanAccountIndex]
      return item ? item.display_name : ''
    },
    roleNames() { return ROLES.map(this.roleLabel) },
    newAccountRoleIndex() { return this.roleIndex(this.newAccount.role) },
    roundMatches() {
      const seen = {}
      return (this.roundSummary.clans || []).filter(item => {
        if (!item.match_id || seen[item.match_id]) return false
        seen[item.match_id] = true
        return true
      })
    }
  },
  onShow() { this.load() },
  methods: {
    roleLabel(role) { return ({ creator: '创建者', admin: '管理员', member: '成员' })[role] || '成员' },
    roundStatus(status) { return ({ scheduled: '待开放', open: '可登记', partially_registered: '登记中', completed: '已完成', cancelled: '已撤销' })[status] || status },
    registrationLabel(status) { return ({ internal_matched: '内部匹配', match_failed: '匹配失败', revoked: '已撤销' })[status] || status },
    formatRoundTime(value) {
      if (!value) return '-'
      const date = new Date(value)
      const pad = n => String(n).padStart(2, '0')
      return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
    },
    roleIndex(role) { return Math.max(0, ROLES.indexOf(role)) },
    accountName(id) {
      const item = this.accounts.find(account => Number(account.id) === Number(id))
      return item ? item.display_name : '未知账号'
    },
    accountIndex(id) { return Math.max(0, this.activeAccounts.findIndex(item => Number(item.id) === Number(id))) },
    canEditAccount(account) {
      if (account.role === 'creator') return false
      if (this.isCreator) return true
      return account.role !== 'creator'
    },
    async load() {
      this.loading = true
      this.error = ''
      try {
        this.me = await getFarmMe()
        uni.setStorageSync('farm_account', this.me)
        const dashboard = await getFarmDashboard()
        this.roundSummary = dashboard
        if (this.me.role === 'creator' || this.me.role === 'admin') {
          const requests = [getFarmAdminAccounts(), getFarmAdminClans()]
          if (dashboard.round) requests.push(getFarmRoundResults(dashboard.round.id))
          const result = await Promise.all(requests)
          this.accounts = result[0].accounts || []
          this.clans = result[1].clans || []
          if (result[2]) this.roundSummary = result[2]
          if (!this.newClan.account_id && this.activeAccounts.length) this.newClan.account_id = this.activeAccounts[0].id
        } else {
          const result = await getFarmClans()
          this.accounts = []
          this.clans = result.clans || []
        }
      } catch (e) {
        this.error = e.message || '加载失败'
      } finally {
        this.loading = false
      }
    },
    defaultRoundDate() {
      const date = new Date(Date.now() + 24 * 60 * 60 * 1000)
      const pad = n => String(n).padStart(2, '0')
      return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
    },
    async createRound() {
      if (this.saving) return
      const date = this.roundDate || this.defaultRoundDate()
      this.roundDate = date
      this.saving = true
      try {
        await createFarmRound({ scheduled_at: `${date}T${this.roundTime}:00+08:00`, business_time_kind: 'preparation_start' })
        this.creatingNextRound = false
        await this.load()
        uni.showToast({ title: '场次已创建', icon: 'success' })
      } catch (e) {
        uni.showModal({ title: '创建失败', content: e.message, showCancel: false })
      } finally { this.saving = false }
    },
    async openRound() {
      if (!this.roundSummary.round || this.saving) return
      await this.runUpdate(() => updateFarmRound(this.roundSummary.round.id, { status: 'open' }))
    },
    promptValue(title, placeholder, onConfirm) {
      uni.showModal({
        title,
        editable: true,
        placeholderText: placeholder,
        success: result => {
          if (result.confirm && result.content) onConfirm(result.content.trim())
        }
      })
    },
    cancelRound() {
      if (!this.roundSummary.round) return
      this.promptValue('撤销整场', '请输入撤销原因（至少 3 个字）', reason => {
        this.runUpdate(() => cancelFarmRound(this.roundSummary.round.id, reason))
      })
    },
    revokeMatch(item) {
      this.promptValue('撤销匹配', '请输入撤销原因（至少 3 个字）', reason => {
        this.runUpdate(() => revokeFarmMatch(item.match_id, reason))
      })
    },
    resetPassword(account) {
      this.promptValue(`重置 ${account.display_name} 密码`, '输入至少 8 位的新密码', password => {
        this.runUpdate(() => resetFarmAccountPassword(account.id, password))
      })
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
        this.tab = 'accounts'
        uni.showToast({ title: '账号已创建', icon: 'success' })
      } catch (e) {
        uni.showModal({ title: '创建失败', content: e.message, showCancel: false })
      } finally { this.saving = false }
    },
    async createClan() {
      if (this.saving) return
      const clanTag = this.newClan.clan_tag.trim()
      const account = this.activeAccounts[this.newClanAccountIndex]
      if (!clanTag || !account) {
        uni.showToast({ title: '请填写标签并选择归属账号', icon: 'none' })
        return
      }
      this.saving = true
      try {
        await createFarmClan({ clan_tag: clanTag, account_id: account.id })
        this.newClan.clan_tag = ''
        await this.load()
        uni.showToast({ title: '部落已添加', icon: 'success' })
      } catch (e) {
        uni.showModal({ title: '添加失败', content: e.message, showCancel: false })
      } finally { this.saving = false }
    },
    onNewClanAccount(event) {
      const account = this.activeAccounts[Number(event.detail.value)]
      if (account) this.newClan.account_id = account.id
    },
    onNewAccountRole(event) { this.newAccount.role = ROLES[Number(event.detail.value)] || 'member' },
    async changeRole(account, event) {
      const role = ROLES[Number(event.detail.value)]
      if (!role || role === account.role) return
      await this.runUpdate(() => updateFarmAccount(account.id, { role }))
    },
    async toggleAccount(account) {
      await this.runUpdate(() => updateFarmAccount(account.id, { status: account.status === 'active' ? 'disabled' : 'active' }))
    },
    async toggleClan(clan) {
      await this.runUpdate(() => updateFarmClan(clan.clan_tag, { status: clan.status === 'active' ? 'disabled' : 'active' }))
    },
    async transferClan(clan, event) {
      const target = this.activeAccounts[Number(event.detail.value)]
      if (!target || Number(target.id) === Number(clan.account_id)) return
      await this.runUpdate(() => transferFarmClan(clan.clan_tag, target.id))
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
    },
    async logout() {
      try { await farmLogout() } catch (e) {}
      uni.removeStorageSync('farm_token')
      uni.removeStorageSync('farm_account')
      uni.redirectTo({ url: '/pages/farm/login' })
    }
  }
}
</script>

<style>
.farm-page { min-height: 100vh; padding: 28rpx 26rpx; box-sizing: border-box; background: #0f0f23; color: #eef1f8; }
.page-state { display: flex; min-height: 70vh; flex-direction: column; align-items: center; justify-content: center; gap: 24rpx; color: #7f899f; font-size: 26rpx; }
.state-error { color: #d78383; }
.small-button { padding: 0 32rpx; border: 1rpx solid #31537d; border-radius: 12rpx; background: transparent; color: #76aee6; font-size: 24rpx; }
.identity-card { display: flex; align-items: center; justify-content: space-between; padding: 28rpx; border: 1rpx solid #2a3152; border-radius: 18rpx; background: #191a31; }
.identity-name, .identity-meta { display: block; }.identity-name { font-size: 32rpx; font-weight: 700; }.identity-meta { margin-top: 8rpx; color: #7f899f; font-size: 22rpx; }.logout-link { padding: 14rpx 4rpx 14rpx 24rpx; color: #cf7e82; font-size: 24rpx; }
.round-admin-card { margin-top: 22rpx; padding: 0 24rpx 24rpx; border: 1rpx solid #2a3152; border-radius: 18rpx; background: #191a31; }.round-head { padding-left: 0; padding-right: 0; }.round-time, .round-progress { display: block; }.round-time { font-size: 30rpx; font-weight: 650; }.round-progress { margin-top: 9rpx; color: #7f899f; font-size: 22rpx; }.round-button { margin-top: 22rpx; }.datetime-row { display: flex; gap: 14rpx; }.datetime-row picker { flex: 1; min-width: 0; }.datetime-row .picker-field { justify-content: center; }
.danger-button { display: flex; height: 72rpx; align-items: center; justify-content: center; margin-top: 16rpx; border: 1rpx solid #663a48; border-radius: 12rpx; background: transparent; color: #cf7e82; font-size: 24rpx; }.danger-button::after { border: 0; }.round-results { margin-top: 22rpx; border-top: 1rpx solid #292f4e; }.round-result-row { display: flex; min-height: 82rpx; align-items: center; justify-content: space-between; border-bottom: 1rpx solid #292f4e; }.round-result-row:last-child { border-bottom: 0; }.result-title, .result-meta { display: block; }.result-title { font-size: 23rpx; }.result-meta { margin-top: 5rpx; color: #707a91; font-size: 20rpx; }
.tabs { display: flex; margin: 26rpx 0 10rpx; padding: 6rpx; border-radius: 14rpx; background: #17182d; }.tab { flex: 1; padding: 18rpx 0; border-radius: 10rpx; color: #778097; font-size: 25rpx; text-align: center; }.tab.active { background: #273657; color: #8dc2f2; font-weight: 600; }
.section-head { display: flex; align-items: center; justify-content: space-between; padding: 30rpx 4rpx 18rpx; }.section-title { font-size: 29rpx; font-weight: 650; }.section-count { color: #687188; font-size: 22rpx; }
.form-card, .data-card, .empty-card { margin-bottom: 20rpx; border: 1rpx solid #2a3152; border-radius: 18rpx; background: #191a31; }
.form-card { padding: 26rpx; }.form-title { display: block; margin-bottom: 20rpx; font-size: 27rpx; font-weight: 600; }.input, .picker-field { height: 76rpx; margin-bottom: 16rpx; padding: 0 20rpx; border: 1rpx solid #30375b; border-radius: 12rpx; box-sizing: border-box; background: #121326; color: #e9edf6; font-size: 25rpx; }.picker-field { display: flex; align-items: center; justify-content: space-between; color: #aeb7ca; }
.primary-button { display: flex; height: 78rpx; align-items: center; justify-content: center; border-radius: 12rpx; background: #397fc0; color: #fff; font-size: 26rpx; font-weight: 600; }.primary-button::after { border: 0; }.form-tip { display: block; margin-top: 16rpx; color: #626c84; font-size: 21rpx; line-height: 1.55; }
.empty-card { padding: 70rpx 20rpx; color: #677087; font-size: 25rpx; text-align: center; }.data-card { overflow: hidden; }.card-main { display: flex; align-items: center; justify-content: space-between; padding: 25rpx; }.card-copy { min-width: 0; }.card-title, .card-meta { display: block; }.card-title { overflow: hidden; font-size: 28rpx; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }.card-meta { margin-top: 8rpx; color: #747e96; font-size: 21rpx; }.status-badge { flex-shrink: 0; margin-left: 18rpx; padding: 6rpx 14rpx; border-radius: 18rpx; background: rgba(67,170,115,.14); color: #6fc595; font-size: 21rpx; }.status-badge.disabled { background: rgba(193,107,110,.12); color: #be777b; }
.card-actions { display: flex; min-height: 70rpx; align-items: center; justify-content: space-between; padding: 0 25rpx; border-top: 1rpx solid #282e4d; color: #8190ab; font-size: 23rpx; }.action-field { display: flex; align-items: center; gap: 12rpx; padding: 16rpx 0; }.action-link { padding: 18rpx 0 18rpx 30rpx; color: #77aee3; }.bottom-space { height: 50rpx; }
</style>
