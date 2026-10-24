<template>
  <view class="farm-page">
    <view v-if="loading" class="page-state">正在加载...</view>
    <view v-else-if="error" class="page-state">
      <text class="state-error">{{ error }}</text>
      <button class="small-button" @tap="load">重新加载</button>
    </view>
    <view v-else>
      <view class="account-card">
        <view class="account-main">
          <view class="account-copy">
            <text class="account-name">{{ account.display_name }}</text>
            <text class="account-meta">{{ account.username }} · {{ roleLabel(account.role) }}</text>
          </view>
          <text class="status-badge" :class="{ disabled: account.status !== 'active' }">{{ account.status === 'active' ? '账号启用' : '账号停用' }}</text>
        </view>
        <view class="account-count">
          <text>已绑定互刷部落</text>
          <text>{{ clans.length }} 个</text>
        </view>
      </view>

      <view v-if="!clans.length" class="empty-card">该账号暂未绑定互刷部落</view>
      <view v-for="clan in clans" :key="clan.id" class="clan-card">
        <view class="clan-main" @tap="openClanDetail(clan)">
          <view class="clan-copy">
            <text class="clan-name">{{ clan.clan_name }}</text>
            <text class="clan-tag">{{ clan.clan_tag }}</text>
          </view>
          <view class="score-side">
            <view class="score-copy">
              <text class="score-label">当前积分</text>
              <text class="score-value">{{ clan.score }}</text>
            </view>
            <text class="detail-arrow">›</text>
          </view>
        </view>
        <view class="clan-actions">
          <text class="clan-status" :class="{ disabled: clan.status !== 'active' }">{{ clan.status === 'active' ? '部落启用' : '部落停用' }}</text>
          <text class="action-link" :class="{ danger: clan.status === 'active' }" @tap="confirmToggleClan(clan)">{{ clan.status === 'active' ? '停用部落' : '启用部落' }}</text>
        </view>
      </view>
    </view>
    <view class="bottom-space"></view>
  </view>
</template>

<script>
import {
  getFarmAdminAccounts,
  getFarmAdminClans,
  getFarmMe,
  updateFarmClan
} from '@/utils/api.js'

export default {
  data() {
    return {
      accountId: null,
      account: {},
      clans: [],
      loading: true,
      hasLoaded: false,
      error: '',
      savingClanId: null
    }
  },
  onLoad(options) { this.accountId = Number(options && options.account_id) || null },
  onShow() { this.load() },
  methods: {
    openClanDetail(clan) {
      uni.navigateTo({ url: `/pages/farm/admin-clan-detail?clan_tag=${encodeURIComponent(clan.clan_tag)}` })
    },
    roleLabel(role) { return ({ creator: '创建者', admin: '管理员', member: '成员' })[role] || '成员' },
    async load() {
      const initialLoad = !this.hasLoaded
      if (initialLoad) {
        this.loading = true
        this.error = ''
      }
      try {
        if (!this.accountId) throw new Error('账号参数无效')
        const result = await Promise.all([getFarmMe(), getFarmAdminAccounts(), getFarmAdminClans()])
        if (!['creator', 'admin'].includes(result[0].role)) throw new Error('当前账号没有部落管理权限')
        const accounts = result[1].accounts || []
        const account = accounts.find(item => Number(item.id) === this.accountId)
        if (!account) throw new Error('互刷账号不存在')
        this.account = account
        this.clans = (result[2].clans || []).filter(item => Number(item.account_id) === this.accountId)
        this.error = ''
        this.hasLoaded = true
      } catch (e) {
        if (initialLoad) this.error = e.message || '加载失败'
        else uni.showToast({ title: e.message || '刷新失败', icon: 'none' })
      } finally {
        if (initialLoad) this.loading = false
      }
    },
    confirmToggleClan(clan) {
      if (this.savingClanId) return
      const disabling = clan.status === 'active'
      uni.showModal({
        title: disabling ? '停用互刷部落' : '启用互刷部落',
        content: disabling
          ? '停用后不再参加后续新建场次；已经创建的场次仍按原快照处理。'
          : '启用后将从下一场新建场次开始参加互刷。',
        success: result => {
          if (result.confirm) this.toggleClan(clan)
        }
      })
    },
    async toggleClan(clan) {
      this.savingClanId = clan.id
      try {
        await updateFarmClan(clan.clan_tag, {
          status: clan.status === 'active' ? 'disabled' : 'active'
        })
        await this.load()
        uni.showToast({ title: clan.status === 'active' ? '部落已停用' : '部落已启用', icon: 'success' })
      } catch (e) {
        uni.showModal({ title: '操作失败', content: e.message || '请稍后重试', showCancel: false })
      } finally {
        this.savingClanId = null
      }
    }
  }
}
</script>

<style>
.farm-page { min-height: 100vh; padding: 28rpx 26rpx; box-sizing: border-box; background: #0f0f23; color: #eef1f8; }
.page-state { display: flex; min-height: 70vh; flex-direction: column; align-items: center; justify-content: center; gap: 24rpx; color: #7f899f; font-size: 26rpx; }.state-error { color: #d78383; }.small-button { padding: 0 32rpx; border: 1rpx solid #31537d; border-radius: 12rpx; background: transparent; color: #76aee6; font-size: 24rpx; }
.account-card, .clan-card, .empty-card { margin-bottom: 20rpx; border: 1rpx solid #2a3152; border-radius: 18rpx; background: #191a31; }.account-card, .clan-card { overflow: hidden; }.account-main, .clan-main { display: flex; align-items: center; justify-content: space-between; padding: 25rpx; }.account-copy, .clan-copy { min-width: 0; }.account-name, .account-meta, .clan-name, .clan-tag, .score-label, .score-value { display: block; }.account-name { font-size: 30rpx; font-weight: 650; }.account-meta { margin-top: 8rpx; color: #747e96; font-size: 21rpx; }
.status-badge { flex-shrink: 0; margin-left: 18rpx; padding: 6rpx 14rpx; border-radius: 18rpx; background: rgba(67,170,115,.14); color: #6fc595; font-size: 20rpx; }.status-badge.disabled { background: rgba(193,107,110,.12); color: #be777b; }.account-count { display: flex; align-items: center; justify-content: space-between; padding: 18rpx 25rpx; border-top: 1rpx solid #282e4d; color: #7f899f; font-size: 22rpx; }
.empty-card { padding: 70rpx 20rpx; color: #677087; font-size: 25rpx; text-align: center; }.clan-name { overflow: hidden; font-size: 28rpx; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }.clan-tag { margin-top: 8rpx; color: #747e96; font-size: 21rpx; }.score-side { display: flex; flex-shrink: 0; align-items: center; margin-left: 20rpx; }.score-copy { text-align: right; }.score-label { color: #707b93; font-size: 20rpx; }.score-value { margin-top: 2rpx; color: #8cbbea; font-size: 32rpx; font-weight: 700; }.detail-arrow { margin-left: 16rpx; color: #647089; font-size: 36rpx; }
.clan-actions { display: flex; min-height: 70rpx; align-items: center; justify-content: space-between; padding: 0 25rpx; border-top: 1rpx solid #282e4d; }.clan-status { color: #6fc595; font-size: 22rpx; }.clan-status.disabled { color: #be777b; }.action-link { padding: 18rpx 0 18rpx 30rpx; color: #77aee3; font-size: 23rpx; }.action-link.danger { color: #c87a7e; }.bottom-space { height: 50rpx; }
</style>
