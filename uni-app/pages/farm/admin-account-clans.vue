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

      <view v-if="isCreator" class="registration-card">
        <view class="registration-head">
          <view>
            <text class="registration-title">本轮代登记</text>
            <text class="registration-desc">以超级管理员身份为该账号登记互刷部落</text>
          </view>
          <text v-if="dashboard.round" class="round-badge">{{ roundStatus(dashboard.round.status) }}</text>
        </view>
        <view v-if="dashboard.round">
          <view class="round-meta">
            <text>开始搜战时间</text>
            <text>{{ formatTime(dashboard.round.scheduled_at_beijing) }}</text>
          </view>
          <view class="round-meta">
            <text>该账号登记进度</text>
            <text>{{ dashboard.registered_count }}/{{ dashboard.total_count }}</text>
          </view>
          <button
            class="register-all"
            :class="{ active: canRegisterAll }"
            :disabled="!canRegisterAll"
            :loading="registerAllRunning"
            @tap="registerAll"
          >{{ registerAllLabel }}</button>
          <text v-if="!dashboard.registration_enabled" class="registration-notice">登记功能暂未开放</text>
        </view>
        <view v-else class="round-empty">暂无可登记场次</view>
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
          <template v-if="clan.status !== 'snapshot'">
            <text class="clan-status" :class="{ disabled: clan.status !== 'active' }">{{ clan.status === 'active' ? '部落启用' : '部落停用' }}</text>
            <text class="action-link" :class="{ danger: clan.status === 'active' }" @tap="confirmToggleClan(clan)">{{ clan.status === 'active' ? '停用部落' : '启用部落' }}</text>
          </template>
          <template v-else>
            <text class="clan-status snapshot">本轮账号快照</text>
            <text class="snapshot-hint">归属变更下轮生效</text>
          </template>
        </view>
        <view v-if="isCreator && dashboard.round" class="registration-action">
          <view class="registration-status-copy">
            <text class="registration-status-label">本轮状态</text>
            <text class="registration-status-value">{{ clanRegistrationStatus(clan) }}</text>
          </view>
          <button
            class="register-one"
            :class="{ active: canRegister(clan) }"
            :disabled="!canRegister(clan) || registeringClanId === clan.id || registerAllRunning"
            :loading="registeringClanId === clan.id"
            @tap="registerClan(clan)"
          >{{ registerLabel(clan) }}</button>
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
  getFarmCreatorAccountDashboard,
  getFarmMe,
  registerFarmClanForAccount,
  updateFarmClan
} from '@/utils/api.js'

export default {
  data() {
    return {
      accountId: null,
      account: {},
      clans: [],
      operator: {},
      dashboard: {
        round: null,
        registered_count: 0,
        total_count: 0,
        clans: [],
        registration_enabled: false
      },
      loading: true,
      hasLoaded: false,
      error: '',
      savingClanId: null,
      registeringClanId: null,
      registerAllRunning: false,
      batchDone: 0,
      batchTotal: 0
    }
  },
  computed: {
    isCreator() { return this.operator.role === 'creator' },
    canRegisterAll() {
      return this.isCreator && !this.registerAllRunning && this.dashboard.clans.some(clan => this.canRegisterRoundClan(clan))
    },
    registerAllLabel() {
      if (this.registerAllRunning) return `正在登记 ${this.batchDone}/${this.batchTotal}`
      if (this.account.status !== 'active') return '账号已停用'
      if (!this.dashboard.registration_enabled) return '登记功能暂未开放'
      if (!this.dashboard.round) return '暂无可登记场次'
      const count = this.dashboard.clans.filter(clan => this.canRegisterRoundClan(clan)).length
      return count ? `一键登记 ${count} 个部落` : '暂无可登记部落'
    }
  },
  onLoad(options) { this.accountId = Number(options && options.account_id) || null },
  onShow() { this.load() },
  methods: {
    openClanDetail(clan) {
      uni.navigateTo({ url: `/pages/farm/admin-clan-detail?clan_tag=${encodeURIComponent(clan.clan_tag)}` })
    },
    roleLabel(role) { return ({ creator: '超级管理员', admin: '管理员', member: '成员' })[role] || '成员' },
    roundStatus(status) { return ({ scheduled: '待开放', open: '可登记', partially_registered: '登记中', completed: '已完成' })[status] || status },
    registrationStatus(status) {
      return ({ not_registered: '未登记', registering: '登记中', not_in_war: '尚未搜到对手', war_mismatch: '场次不匹配', fetch_failed: '获取失败', internal_matched: '内部匹配成功', match_failed: '匹配失败', revoked: '已撤销' })[status] || status
    },
    formatTime(value) {
      if (!value) return '-'
      const date = new Date(value)
      const pad = number => String(number).padStart(2, '0')
      return `${date.getMonth() + 1}月${date.getDate()}日 ${pad(date.getHours())}:${pad(date.getMinutes())}`
    },
    roundClan(clan) {
      return this.dashboard.clans.find(item => Number(item.clan_id) === Number(clan.id)) || null
    },
    clanRegistrationStatus(clan) {
      const roundClan = this.roundClan(clan)
      return roundClan ? this.registrationStatus(roundClan.registration_status) : '本轮不参与'
    },
    canRegisterRoundClan(clan) {
      if (!this.isCreator || this.account.status !== 'active') return false
      if (!this.dashboard.registration_enabled || !this.dashboard.round) return false
      if (this.dashboard.round.business_time_kind !== 'preparation_start') return false
      if (!['open', 'partially_registered'].includes(this.dashboard.round.status)) return false
      return !['internal_matched', 'match_failed', 'revoked'].includes(clan.registration_status)
    },
    canRegister(clan) {
      const roundClan = this.roundClan(clan)
      return Boolean(roundClan && this.canRegisterRoundClan(roundClan))
    },
    registerLabel(clan) {
      const roundClan = this.roundClan(clan)
      if (!roundClan) return '本轮不参与'
      if (['internal_matched', 'match_failed'].includes(roundClan.registration_status)) return '已登记'
      if (roundClan.registration_status === 'revoked') return '等待重新开放'
      if (this.account.status !== 'active') return '账号已停用'
      if (!this.dashboard.registration_enabled) return '登记暂未开放'
      if (!['open', 'partially_registered'].includes(this.dashboard.round.status)) return '场次未开放'
      return '登记本场'
    },
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
        this.operator = result[0]
        const accounts = result[1].accounts || []
        const account = accounts.find(item => Number(item.id) === this.accountId)
        if (!account) throw new Error('互刷账号不存在')
        this.account = account
        const currentClans = (result[2].clans || []).filter(item => Number(item.account_id) === this.accountId)
        if (this.isCreator) {
          this.dashboard = await getFarmCreatorAccountDashboard(this.accountId)
        }
        const merged = new Map(currentClans.map(item => [Number(item.id), item]))
        ;(this.dashboard.clans || []).forEach(item => {
          if (!merged.has(Number(item.clan_id))) {
            merged.set(Number(item.clan_id), {
              id: item.clan_id,
              clan_tag: item.clan_tag,
              clan_name: item.clan_name,
              account_id: item.account_id,
              score: item.current_score,
              status: 'snapshot'
            })
          }
        })
        this.clans = Array.from(merged.values())
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
    },
    async registerClan(clan) {
      if (!this.canRegister(clan) || this.registeringClanId || this.registerAllRunning) return
      this.registeringClanId = clan.id
      try {
        const result = await registerFarmClanForAccount(
          this.accountId, this.dashboard.round.id, clan.clan_tag
        )
        await this.load()
        this.showRegistrationResult(result)
      } catch (e) {
        uni.showModal({ title: '登记失败', content: e.message || '请稍后重试', showCancel: false })
      } finally {
        this.registeringClanId = null
      }
    },
    async registerAll() {
      if (!this.canRegisterAll) return
      const clans = this.dashboard.clans.filter(clan => this.canRegisterRoundClan(clan))
      this.registerAllRunning = true
      this.batchDone = 0
      this.batchTotal = clans.length
      const summary = { internal: 0, failed: 0, waiting: 0, errors: 0 }
      for (const clan of clans) {
        this.registeringClanId = clan.clan_id
        try {
          const result = await registerFarmClanForAccount(
            this.accountId, this.dashboard.round.id, clan.clan_tag
          )
          if (result.registration_status === 'internal_matched') summary.internal += 1
          else if (result.registration_status === 'match_failed') summary.failed += 1
          else if (['not_in_war', 'war_mismatch'].includes(result.registration_status)) summary.waiting += 1
          else summary.errors += 1
          this.dashboard = await getFarmCreatorAccountDashboard(this.accountId)
        } catch (e) {
          summary.errors += 1
        } finally {
          this.batchDone += 1
        }
      }
      this.registeringClanId = null
      this.registerAllRunning = false
      await this.load()
      uni.showModal({
        title: '一键登记完成',
        content: `内部匹配 ${summary.internal} 个\n匹配失败 ${summary.failed} 个\n等待重试 ${summary.waiting} 个\n获取失败 ${summary.errors} 个`,
        showCancel: false
      })
    },
    showRegistrationResult(result) {
      const messages = {
        internal_matched: result.result === 'win' ? '内部匹配成功，本场预定胜' : '内部匹配成功，本场预定负',
        match_failed: '对手不在互刷联盟，积分不变',
        not_in_war: '尚未搜到对手，可稍后重试',
        war_mismatch: '当前战争不属于本轮，可稍后重试',
        fetch_failed: result.last_error || '获取战争数据失败'
      }
      uni.showModal({ title: '登记结果', content: messages[result.registration_status] || '登记完成', showCancel: false })
    }
  }
}
</script>

<style>
.farm-page { min-height: 100vh; padding: 28rpx 26rpx; box-sizing: border-box; background: #0f0f23; color: #eef1f8; }
.page-state { display: flex; min-height: 70vh; flex-direction: column; align-items: center; justify-content: center; gap: 24rpx; color: #7f899f; font-size: 26rpx; }.state-error { color: #d78383; }.small-button { padding: 0 32rpx; border: 1rpx solid #31537d; border-radius: 12rpx; background: transparent; color: #76aee6; font-size: 24rpx; }
.account-card, .registration-card, .clan-card, .empty-card { margin-bottom: 20rpx; border: 1rpx solid #2a3152; border-radius: 18rpx; background: #191a31; }.account-card, .clan-card { overflow: hidden; }.account-main, .clan-main { display: flex; align-items: center; justify-content: space-between; padding: 25rpx; }.account-copy, .clan-copy { min-width: 0; }.account-name, .account-meta, .clan-name, .clan-tag, .score-label, .score-value, .registration-title, .registration-desc { display: block; }.account-name { font-size: 30rpx; font-weight: 650; }.account-meta { margin-top: 8rpx; color: #747e96; font-size: 21rpx; }
.registration-card { padding: 25rpx; }.registration-head, .round-meta { display: flex; align-items: center; justify-content: space-between; }.registration-title { font-size: 28rpx; font-weight: 650; }.registration-desc { margin-top: 7rpx; color: #737f97; font-size: 21rpx; }.round-badge { flex-shrink: 0; margin-left: 20rpx; padding: 6rpx 14rpx; border-radius: 18rpx; background: rgba(68,137,204,.16); color: #7cb6eb; font-size: 20rpx; }.round-meta { margin-top: 22rpx; color: #8792a9; font-size: 22rpx; }.round-meta text:last-child { color: #d8deea; }.register-all, .register-one { display: flex; align-items: center; justify-content: center; border: 0; color: #758198 !important; }.register-all { height: 72rpx; margin-top: 24rpx; border-radius: 12rpx; background: #242941 !important; font-size: 24rpx; }.register-all.active, .register-one.active { background: #397fc0 !important; color: #fff !important; }.register-all::after, .register-one::after { border: 0; }.registration-notice { display: block; margin-top: 14rpx; color: #d0a45f; font-size: 21rpx; text-align: center; }.round-empty { padding: 36rpx 0 12rpx; color: #687289; font-size: 23rpx; text-align: center; }
.status-badge { flex-shrink: 0; margin-left: 18rpx; padding: 6rpx 14rpx; border-radius: 18rpx; background: rgba(67,170,115,.14); color: #6fc595; font-size: 20rpx; }.status-badge.disabled { background: rgba(193,107,110,.12); color: #be777b; }.account-count { display: flex; align-items: center; justify-content: space-between; padding: 18rpx 25rpx; border-top: 1rpx solid #282e4d; color: #7f899f; font-size: 22rpx; }
.empty-card { padding: 70rpx 20rpx; color: #677087; font-size: 25rpx; text-align: center; }.clan-name { overflow: hidden; font-size: 28rpx; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }.clan-tag { margin-top: 8rpx; color: #747e96; font-size: 21rpx; }.score-side { display: flex; flex-shrink: 0; align-items: center; margin-left: 20rpx; }.score-copy { text-align: right; }.score-label { color: #707b93; font-size: 20rpx; }.score-value { margin-top: 2rpx; color: #8cbbea; font-size: 32rpx; font-weight: 700; }.detail-arrow { margin-left: 16rpx; color: #647089; font-size: 36rpx; }
.clan-actions { display: flex; min-height: 70rpx; align-items: center; justify-content: space-between; padding: 0 25rpx; border-top: 1rpx solid #282e4d; }.clan-status { color: #6fc595; font-size: 22rpx; }.clan-status.disabled { color: #be777b; }.clan-status.snapshot, .snapshot-hint { color: #7f8ba2; font-size: 21rpx; }.action-link { padding: 18rpx 0 18rpx 30rpx; color: #77aee3; font-size: 23rpx; }.action-link.danger { color: #c87a7e; }.bottom-space { height: 50rpx; }
.registration-action { display: flex; min-height: 88rpx; align-items: center; justify-content: space-between; padding: 0 25rpx; border-top: 1rpx solid #282e4d; background: #1d2038; }.registration-status-label, .registration-status-value { display: block; }.registration-status-label { color: #6e7991; font-size: 19rpx; }.registration-status-value { margin-top: 5rpx; color: #9aa6bc; font-size: 22rpx; }.register-one { min-width: 190rpx; height: 58rpx; margin: 0 0 0 20rpx; padding: 0 20rpx; border-radius: 10rpx; background: #272c45 !important; font-size: 21rpx; line-height: 58rpx; }
</style>
