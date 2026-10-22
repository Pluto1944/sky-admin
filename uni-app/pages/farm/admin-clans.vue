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
          <text class="section-title">全部互刷部落</text>
          <text class="section-desc">管理部落资料、账号归属和启用状态</text>
        </view>
        <text class="section-count">{{ clans.length }} 个</text>
      </view>

      <view class="form-card">
        <text class="form-title">添加互刷部落</text>
        <input v-model="newClan.clan_tag" class="input" placeholder="部落标签，例如 #ABC123" maxlength="16" />
        <picker :range="activeAccountNames" :value="newClanAccountIndex" @change="onNewClanAccount">
          <view class="picker-field">{{ selectedNewClanAccountName || '选择归属账号' }}<text>⌄</text></view>
        </picker>
        <button class="primary-button" :loading="saving" :disabled="saving" @tap="createClan">添加并验证</button>
        <text class="form-tip">部落名称来自服务器已同步的官方资料，不接受手工伪造。</text>
      </view>

      <view v-if="!clans.length" class="empty-card">暂未添加互刷部落</view>
      <view v-for="clan in clans" :key="clan.id" class="data-card">
        <view class="card-main">
          <view class="card-copy">
            <text class="card-title">{{ clan.clan_name }}</text>
            <text class="card-meta">{{ clan.clan_tag }} · 当前积分 {{ clan.score }}</text>
          </view>
          <text class="status-badge" :class="{ disabled: clan.status !== 'active' }">{{ clan.status === 'active' ? '启用' : '停用' }}</text>
        </view>
        <view class="card-actions">
          <picker :range="activeAccountNames" :value="accountIndex(clan.account_id)" @change="transferClan(clan, $event)">
            <view class="action-field">归属：{{ accountName(clan.account_id) }}<text>⌄</text></view>
          </picker>
          <text class="action-link" @tap="toggleClan(clan)">{{ clan.status === 'active' ? '停用' : '启用' }}</text>
        </view>
      </view>
    </view>
    <view class="bottom-space"></view>
  </view>
</template>

<script>
import {
  createFarmClan,
  getFarmAdminAccounts,
  getFarmAdminClans,
  getFarmMe,
  transferFarmClan,
  updateFarmClan
} from '@/utils/api.js'

export default {
  data() {
    return {
      loading: true,
      saving: false,
      error: '',
      accounts: [],
      clans: [],
      newClan: { clan_tag: '', account_id: null }
    }
  },
  computed: {
    activeAccounts() { return this.accounts.filter(item => item.status === 'active') },
    activeAccountNames() { return this.activeAccounts.map(item => item.display_name) },
    newClanAccountIndex() {
      return Math.max(0, this.activeAccounts.findIndex(item => Number(item.id) === Number(this.newClan.account_id)))
    },
    selectedNewClanAccountName() {
      const item = this.activeAccounts[this.newClanAccountIndex]
      return item ? item.display_name : ''
    }
  },
  onShow() { this.load() },
  methods: {
    accountName(id) {
      const item = this.accounts.find(account => Number(account.id) === Number(id))
      return item ? item.display_name : '未知账号'
    },
    accountIndex(id) { return Math.max(0, this.activeAccounts.findIndex(item => Number(item.id) === Number(id))) },
    async load() {
      this.loading = true
      this.error = ''
      try {
        const me = await getFarmMe()
        if (!['creator', 'admin'].includes(me.role)) throw new Error('当前账号没有部落管理权限')
        const result = await Promise.all([getFarmAdminAccounts(), getFarmAdminClans()])
        this.accounts = result[0].accounts || []
        this.clans = result[1].clans || []
        if (!this.newClan.account_id && this.activeAccounts.length) this.newClan.account_id = this.activeAccounts[0].id
      } catch (e) {
        this.error = e.message || '加载失败'
      } finally {
        this.loading = false
      }
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
    }
  }
}
</script>

<style>
.farm-page { min-height: 100vh; padding: 28rpx 26rpx; box-sizing: border-box; background: #0f0f23; color: #eef1f8; }.page-state { display: flex; min-height: 70vh; flex-direction: column; align-items: center; justify-content: center; gap: 24rpx; color: #7f899f; font-size: 26rpx; }.state-error { color: #d78383; }.small-button { padding: 0 32rpx; border: 1rpx solid #31537d; border-radius: 12rpx; background: transparent; color: #76aee6; font-size: 24rpx; }
.section-head { display: flex; align-items: flex-start; justify-content: space-between; padding: 30rpx 4rpx 18rpx; }.first-head { padding-top: 4rpx; }.section-title, .section-desc { display: block; }.section-title { font-size: 29rpx; font-weight: 650; }.section-desc { margin-top: 7rpx; color: #717c93; font-size: 21rpx; }.section-count { flex-shrink: 0; margin-left: 18rpx; color: #687188; font-size: 22rpx; }
.form-card, .data-card, .empty-card { margin-bottom: 20rpx; border: 1rpx solid #2a3152; border-radius: 18rpx; background: #191a31; }.form-card { padding: 26rpx; }.form-title { display: block; margin-bottom: 20rpx; font-size: 27rpx; font-weight: 600; }.input, .picker-field { height: 76rpx; margin-bottom: 16rpx; padding: 0 20rpx; border: 1rpx solid #30375b; border-radius: 12rpx; box-sizing: border-box; background: #121326; color: #e9edf6; font-size: 25rpx; }.picker-field { display: flex; align-items: center; justify-content: space-between; color: #aeb7ca; }
.primary-button { display: flex; height: 78rpx; align-items: center; justify-content: center; border-radius: 12rpx; background: #397fc0; color: #fff; font-size: 26rpx; font-weight: 600; }.primary-button::after { border: 0; }.form-tip { display: block; margin-top: 16rpx; color: #626c84; font-size: 21rpx; line-height: 1.55; }
.empty-card { padding: 70rpx 20rpx; color: #677087; font-size: 25rpx; text-align: center; }.data-card { overflow: hidden; }.card-main { display: flex; align-items: center; justify-content: space-between; padding: 25rpx; }.card-copy { min-width: 0; }.card-title, .card-meta { display: block; }.card-title { overflow: hidden; font-size: 28rpx; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }.card-meta { margin-top: 8rpx; color: #747e96; font-size: 21rpx; }.status-badge { flex-shrink: 0; margin-left: 18rpx; padding: 6rpx 14rpx; border-radius: 18rpx; background: rgba(67,170,115,.14); color: #6fc595; font-size: 21rpx; }.status-badge.disabled { background: rgba(193,107,110,.12); color: #be777b; }
.card-actions { display: flex; min-height: 70rpx; align-items: center; justify-content: space-between; padding: 0 25rpx; border-top: 1rpx solid #282e4d; color: #8190ab; font-size: 23rpx; }.action-field { display: flex; align-items: center; gap: 12rpx; padding: 16rpx 0; }.action-link { padding: 18rpx 0 18rpx 30rpx; color: #77aee3; }.bottom-space { height: 50rpx; }
</style>
