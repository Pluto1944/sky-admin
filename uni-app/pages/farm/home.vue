<template>
  <view class="farm-home">
    <view v-if="loading" class="state">正在加载...</view>
    <view v-else-if="error" class="state">
      <text class="error">{{ error }}</text>
      <text class="retry" @tap="load">点击重试</text>
    </view>
    <view v-else>
      <view v-if="isManager" class="admin-entry" @tap="openAdmin">
        <view class="admin-entry-copy">
          <text class="admin-entry-title">互刷联盟管理</text>
          <text class="admin-entry-desc">账号、部落与场次设置</text>
        </view>
        <view class="admin-entry-action">
          <text>进入管理</text>
          <text class="admin-entry-arrow">›</text>
        </view>
      </view>

      <view class="account-strip">
        <view class="account-copy">
          <text class="account-label">当前登录账号</text>
          <text class="account-name">{{ me.display_name }} · {{ roleLabel(me.role) }}</text>
          <text class="account-meta">{{ me.username }}</text>
        </view>
        <text class="logout" @tap="logout">退出登录</text>
      </view>

      <view v-if="!dashboard.registration_enabled" class="registration-notice">
        <text class="registration-notice-title">登记功能暂未开放</text>
        <text class="registration-notice-desc">目前可以查看场次、部落和积分，开放后才能执行登记。</text>
      </view>

      <view v-if="dashboard.round" class="round-card">
        <view class="round-top">
          <view>
            <text class="eyebrow">开始搜战时间 · 北京时间</text>
            <text class="round-time">{{ formatTime(dashboard.round.scheduled_at_beijing) }}</text>
          </view>
          <text class="round-status">{{ roundStatus(dashboard.round.status) }}</text>
        </view>
        <view class="countdown">{{ countdown }}</view>
        <view class="progress-row">
          <text>登记进度</text>
          <text>{{ dashboard.registered_count }}/{{ dashboard.total_count }}</text>
        </view>
        <view class="progress-track">
          <view class="progress-fill" :style="{ width: progressWidth }"></view>
        </view>
        <button
          class="register-all"
          :class="{ active: canRegisterAll }"
          :disabled="!canRegisterAll || registerAllRunning"
          :loading="registerAllRunning"
          @tap="registerAll"
        >{{ registerAllLabel }}</button>
      </view>
      <view v-else class="empty-round">
        <text class="empty-title">暂无互刷场次</text>
        <text class="empty-desc">管理员设置下一轮统一时间后会显示在这里</text>
      </view>

      <view class="section-head">
        <text>已绑定互刷部落</text>
        <text>{{ dashboard.clans.length }} 个</text>
      </view>
      <view v-if="!dashboard.clans.length" class="empty-clans">当前账号暂未绑定本轮互刷部落</view>
      <view v-for="clan in dashboard.clans" :key="clan.clan_id" class="clan-card">
        <view class="clan-detail-entry" @tap="openClanDetail(clan)">
          <view class="clan-row">
          <view class="clan-copy">
            <text class="clan-name">{{ clan.clan_name }}</text>
            <text class="clan-tag">{{ clan.clan_tag }}</text>
          </view>
          <view class="score-copy">
            <text class="score-label">当前积分</text>
            <text class="score-value">{{ clan.current_score }}</text>
          </view>
          </view>
          <view class="clan-status">本轮状态：{{ registrationStatus(clan.registration_status) }} <text class="detail-arrow">›</text></view>
          <view class="match-info">
          <view class="match-row">
            <text class="match-label">对手部落</text>
            <view v-if="clan.opponent_name || clan.opponent_tag" class="opponent-copy">
              <text class="opponent-name">{{ clan.opponent_name || '未知名称' }}</text>
              <text class="opponent-tag">{{ clan.opponent_tag || '标签未知' }}</text>
            </view>
            <text v-else class="match-empty">登记后显示</text>
          </view>
          <view v-if="clan.registration_status === 'internal_matched'" class="match-row result-row">
            <text class="match-label">本轮胜负</text>
            <text class="match-result" :class="clan.result === 'win' ? 'win' : 'loss'">{{ clan.result === 'win' ? '胜' : '负' }}</text>
          </view>
          <view v-if="clan.registration_status === 'internal_matched'" class="match-row score-change-row">
            <text class="match-label">积分</text>
            <text class="score-change">{{ clan.score_before }} → {{ clan.score_after }}</text>
          </view>
        </view>
        </view>
        <button
          class="register-one"
          :class="{ active: canRegister(clan) }"
          :disabled="!canRegister(clan) || registeringClanId === clan.clan_id"
          :loading="registeringClanId === clan.clan_id"
          @tap="registerClan(clan)"
        >{{ registerLabel(clan) }}</button>
      </view>
    </view>
    <view class="bottom-space"></view>
  </view>
</template>

<script>
import { farmLogout, getFarmDashboard, getFarmMe, registerFarmClan } from '@/utils/api.js'

export default {
  data() {
    return {
      loading: true,
      hasLoaded: false,
      error: '',
      me: {},
      dashboard: { round: null, registered_count: 0, total_count: 0, clans: [], registration_enabled: false },
      now: Date.now(),
      timer: null,
      registeringClanId: null,
      registerAllRunning: false,
      batchDone: 0,
      batchTotal: 0
    }
  },
  computed: {
    isManager() { return this.me.role === 'creator' || this.me.role === 'admin' },
    progressWidth() {
      const total = this.dashboard.total_count || 0
      return total ? `${Math.round(this.dashboard.registered_count * 100 / total)}%` : '0%'
    },
    canRegisterAll() {
      return this.dashboard.registration_enabled && !this.registerAllRunning && this.dashboard.clans.some(this.canRegister)
    },
    registerAllLabel() {
      if (this.registerAllRunning) return `正在登记 ${this.batchDone}/${this.batchTotal}`
      if (!this.dashboard.registration_enabled) return '登记功能暂未开放'
      const count = this.dashboard.clans.filter(this.canRegister).length
      if (!count) return '暂无可登记部落'
      return `一键登记 ${count} 个部落`
    },
    countdown() {
      if (!this.dashboard.round) return ''
      const target = new Date(this.dashboard.round.scheduled_at).getTime()
      const diff = target - this.now
      if (diff <= 0) return '已到统一时间'
      const minutes = Math.floor(diff / 60000)
      const days = Math.floor(minutes / 1440)
      const hours = Math.floor((minutes % 1440) / 60)
      const mins = minutes % 60
      return `距离统一时间 ${days ? days + '天 ' : ''}${hours}小时 ${mins}分`
    }
  },
  onShow() {
    this.load()
    this.startClock()
  },
  onHide() { this.stopClock() },
  onUnload() { this.stopClock() },
  onPullDownRefresh() { this.load().finally(() => uni.stopPullDownRefresh()) },
  methods: {
    openClanDetail(clan) {
      uni.navigateTo({ url: `/pages/farm/admin-clan-detail?clan_tag=${encodeURIComponent(clan.clan_tag)}` })
    },
    roleLabel(role) { return ({ creator: '创建者', admin: '管理员', member: '成员' })[role] || '成员' },
    roundStatus(status) { return ({ scheduled: '待开放', open: '可登记', partially_registered: '登记中', completed: '已完成' })[status] || status },
    registrationStatus(status) {
      return ({ not_registered: '未登记', registering: '登记中', not_in_war: '尚未搜到对手', war_mismatch: '场次不匹配', fetch_failed: '获取失败', internal_matched: '内部匹配成功', match_failed: '匹配失败', revoked: '已撤销' })[status] || status
    },
    canRegister(clan) {
      if (!this.dashboard.registration_enabled) return false
      if (!this.dashboard.round || this.dashboard.round.business_time_kind !== 'preparation_start') return false
      if (!['open', 'partially_registered'].includes(this.dashboard.round.status)) return false
      return !['internal_matched', 'match_failed', 'revoked'].includes(clan.registration_status)
    },
    registerLabel(clan) {
      if (['internal_matched', 'match_failed'].includes(clan.registration_status)) return '已登记'
      if (clan.registration_status === 'revoked') return '已撤销，等待重新开放'
      if (!this.dashboard.registration_enabled) return '登记功能暂未开放'
      if (!this.dashboard.round) return '暂无可登记场次'
      if (this.dashboard.round.business_time_kind !== 'preparation_start') return '本轮时间配置异常'
      return '登记本场'
    },
    formatTime(value) {
      if (!value) return '-'
      const date = new Date(value)
      const pad = n => String(n).padStart(2, '0')
      return `${date.getMonth() + 1}月${date.getDate()}日 ${pad(date.getHours())}:${pad(date.getMinutes())}`
    },
    async load() {
      const initialLoad = !this.hasLoaded
      if (initialLoad) {
        this.loading = true
        this.error = ''
      }
      try {
        const result = await Promise.all([getFarmMe(), getFarmDashboard()])
        this.me = result[0]
        this.dashboard = result[1]
        uni.setStorageSync('farm_account', this.me)
        this.error = ''
        this.hasLoaded = true
      } catch (e) {
        if (initialLoad) this.error = e.message || '加载失败'
        else uni.showToast({ title: e.message || '刷新失败', icon: 'none' })
      } finally {
        if (initialLoad) this.loading = false
      }
    },
    startClock() {
      this.stopClock()
      this.now = Date.now()
      this.timer = setInterval(() => { this.now = Date.now() }, 30000)
    },
    stopClock() { if (this.timer) clearInterval(this.timer); this.timer = null },
    async registerClan(clan) {
      if (!this.canRegister(clan) || this.registeringClanId || this.registerAllRunning) return
      this.registeringClanId = clan.clan_id
      try {
        const result = await registerFarmClan(this.dashboard.round.id, clan.clan_tag)
        await this.load()
        const messages = {
          internal_matched: result.result === 'win' ? '内部匹配成功，本场预定胜' : '内部匹配成功，本场预定负',
          match_failed: '对手不在互刷联盟，积分不变',
          not_in_war: '尚未搜到对手，可稍后重试',
          war_mismatch: '当前战争不属于本轮，可稍后重试',
          fetch_failed: result.last_error || '获取战争数据失败'
        }
        uni.showModal({ title: '登记结果', content: messages[result.registration_status] || '登记完成', showCancel: false })
      } catch (e) {
        uni.showModal({ title: '登记失败', content: e.message || '请稍后重试', showCancel: false })
      } finally { this.registeringClanId = null }
    },
    async registerAll() {
      if (!this.canRegisterAll) return
      const targets = this.dashboard.clans.filter(this.canRegister)
      this.registerAllRunning = true
      this.batchDone = 0
      this.batchTotal = targets.length
      const counts = { internal: 0, failed: 0, waiting: 0, errors: 0 }
      for (const clan of targets) {
        this.registeringClanId = clan.clan_id
        try {
          const result = await registerFarmClan(this.dashboard.round.id, clan.clan_tag)
          if (result.registration_status === 'internal_matched') counts.internal += 1
          else if (result.registration_status === 'match_failed') counts.failed += 1
          else if (['not_in_war', 'war_mismatch'].includes(result.registration_status)) counts.waiting += 1
          else counts.errors += 1
          this.dashboard = await getFarmDashboard()
        } catch (e) {
          counts.errors += 1
        } finally {
          this.batchDone += 1
        }
      }
      this.registeringClanId = null
      this.registerAllRunning = false
      await this.load()
      uni.showModal({
        title: '一键登记完成',
        content: `内部匹配 ${counts.internal} 个\n匹配失败 ${counts.failed} 个\n等待重试 ${counts.waiting} 个\n获取失败 ${counts.errors} 个`,
        showCancel: false
      })
    },
    openAdmin() { uni.navigateTo({ url: '/pages/farm/admin' }) },
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
.farm-home { min-height: 100vh; padding: 26rpx; box-sizing: border-box; background: #0f0f23; color: #eef2fa; }
.state { display: flex; min-height: 70vh; flex-direction: column; align-items: center; justify-content: center; gap: 22rpx; color: #778198; font-size: 26rpx; }.error { color: #d47d80; }.retry { color: #70a9e0; }
.admin-entry { display: flex; align-items: center; justify-content: space-between; padding: 26rpx; border: 1rpx solid #31527b; border-radius: 18rpx; background: linear-gradient(145deg, #19243d, #171a32); }.admin-entry-copy, .admin-entry-title, .admin-entry-desc { display: block; }.admin-entry-title { font-size: 30rpx; font-weight: 700; }.admin-entry-desc { margin-top: 8rpx; color: #8391aa; font-size: 22rpx; }.admin-entry-action { display: flex; flex-shrink: 0; align-items: center; margin-left: 24rpx; color: #7cb6eb; font-size: 23rpx; }.admin-entry-arrow { margin-left: 8rpx; font-size: 34rpx; line-height: 1; }
.account-strip { display: flex; align-items: center; justify-content: space-between; padding: 24rpx 4rpx 4rpx; }.account-copy, .account-label, .account-name, .account-meta { display: block; }.account-label { color: #69748b; font-size: 20rpx; }.account-name { margin-top: 6rpx; font-size: 25rpx; font-weight: 600; }.account-meta { margin-top: 5rpx; color: #69748b; font-size: 20rpx; }.logout { flex-shrink: 0; margin-left: 24rpx; color: #b87478; font-size: 22rpx; }
.registration-notice { margin-top: 22rpx; padding: 22rpx 24rpx; border: 1rpx solid #4b3f55; border-radius: 16rpx; background: #1d1a2d; }.registration-notice-title, .registration-notice-desc { display: block; }.registration-notice-title { color: #d7ad72; font-size: 24rpx; font-weight: 600; }.registration-notice-desc { margin-top: 7rpx; color: #827c91; font-size: 21rpx; line-height: 1.5; }
.round-card { margin-top: 24rpx; padding: 28rpx; border: 1rpx solid #31527b; border-radius: 20rpx; background: linear-gradient(145deg, #19243d, #171a32); }.round-top { display: flex; justify-content: space-between; }.eyebrow { display: block; color: #7988a5; font-size: 21rpx; }.round-time { display: block; margin-top: 8rpx; font-size: 37rpx; font-weight: 700; }.time-kind { display: block; margin-top: 7rpx; color: #6f819e; font-size: 20rpx; }.round-status { height: 40rpx; padding: 0 14rpx; border-radius: 20rpx; background: rgba(68,137,204,.16); color: #7cb6eb; font-size: 21rpx; line-height: 40rpx; }.countdown { margin: 22rpx 0 26rpx; color: #93bfe9; font-size: 25rpx; }.progress-row { display: flex; justify-content: space-between; color: #7d879d; font-size: 22rpx; }.progress-track { height: 10rpx; margin-top: 12rpx; overflow: hidden; border-radius: 8rpx; background: #292e49; }.progress-fill { height: 100%; border-radius: 8rpx; background: #3f87c8; }.register-all, .register-one { display: flex; align-items: center; justify-content: center; border: 0; color: #768197 !important; }.register-all { height: 76rpx; margin-top: 26rpx; border-radius: 12rpx; background: #242941 !important; font-size: 25rpx; }.register-all.active { background: #397fc0 !important; color: #fff !important; }.register-all::after, .register-one::after { border: 0; }
.empty-round, .empty-clans { margin-top: 24rpx; padding: 58rpx 24rpx; border: 1rpx dashed #2c3354; border-radius: 18rpx; text-align: center; }.empty-title, .empty-desc { display: block; }.empty-title { font-size: 28rpx; }.empty-desc { margin-top: 10rpx; color: #687289; font-size: 22rpx; }.section-head { display: flex; justify-content: space-between; padding: 34rpx 4rpx 18rpx; color: #dbe0ec; font-size: 27rpx; font-weight: 600; }.section-head text:last-child { color: #687289; font-size: 22rpx; font-weight: 400; }.empty-clans { margin-top: 0; color: #6c758c; font-size: 24rpx; }
.clan-card { margin-bottom: 20rpx; overflow: hidden; border: 1rpx solid #2a3151; border-radius: 18rpx; background: #191a31; }.clan-row { display: flex; align-items: center; justify-content: space-between; padding: 26rpx; }.clan-copy { min-width: 0; }.clan-name, .clan-tag, .score-label, .score-value { display: block; }.clan-name { overflow: hidden; font-size: 29rpx; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }.clan-tag { margin-top: 7rpx; color: #707b93; font-size: 21rpx; }.score-copy { flex-shrink: 0; margin-left: 20rpx; text-align: right; }.score-label { color: #707b93; font-size: 20rpx; }.score-value { margin-top: 2rpx; color: #8cbbea; font-size: 32rpx; font-weight: 700; }.clan-status { display: flex; align-items: center; justify-content: space-between; padding: 18rpx 26rpx; border-top: 1rpx solid #282e4c; color: #8893aa; font-size: 22rpx; }.detail-arrow { color: #66728a; font-size: 32rpx; }.match-info { padding: 17rpx 26rpx; border-top: 1rpx solid #282e4c; }.match-row { display: flex; min-height: 48rpx; align-items: center; justify-content: space-between; }.result-row { margin-top: 8rpx; }.score-change-row { margin-top: 4rpx; }.match-label { flex-shrink: 0; color: #78849b; font-size: 21rpx; }.opponent-copy { min-width: 0; margin-left: 20rpx; text-align: right; }.opponent-name, .opponent-tag { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.opponent-name { color: #dce1ec; font-size: 23rpx; }.opponent-tag { margin-top: 4rpx; color: #707b93; font-size: 20rpx; }.match-empty { color: #616c84; font-size: 21rpx; }.match-result { font-size: 22rpx; font-weight: 600; }.match-result.win { color: #72c497; }.match-result.loss { color: #c98286; }.score-change { color: #9aa7bd; font-size: 22rpx; font-weight: 600; }.register-one { height: 68rpx; border-radius: 0; background: #20243b !important; font-size: 23rpx; }.register-one.active { background: #397fc0 !important; color: #fff !important; }.bottom-space { height: 40rpx; }
</style>
