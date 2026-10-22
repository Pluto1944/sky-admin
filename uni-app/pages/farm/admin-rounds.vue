<template>
  <view class="farm-page">
    <view v-if="loading" class="page-state">正在加载...</view>
    <view v-else-if="error" class="page-state">
      <text class="state-error">{{ error }}</text>
      <button class="small-button" @tap="load">重新加载</button>
    </view>
    <view v-else class="round-admin-card">
      <view class="section-head">
        <view>
          <text class="section-title">当前互刷场次</text>
          <text class="section-desc">管理全联盟统一开始搜战时间与登记结果</text>
        </view>
        <text v-if="roundSummary.round" class="section-count">{{ roundStatus(roundSummary.round.status) }}</text>
      </view>

      <view v-if="roundSummary.round && !creatingNextRound" class="round-current">
        <view v-if="!editingTime">
          <text class="round-label">开始搜战时间 · 北京时间</text>
          <text class="round-time">{{ formatRoundTime(roundSummary.round.scheduled_at_beijing) }}</text>
          <text v-if="!roundSummary.round.time_locked_at" class="action-link edit-time" @tap="startEditTime">修改时间</text>
        </view>
        <view v-else class="time-editor">
          <text class="form-title">修改开始搜战时间</text>
          <view class="datetime-row">
            <picker mode="date" :value="roundDate" @change="roundDate = $event.detail.value">
              <view class="picker-field">{{ roundDate }}</view>
            </picker>
            <picker mode="time" :value="roundTime" @change="roundTime = $event.detail.value">
              <view class="picker-field">{{ roundTime }}</view>
            </picker>
          </view>
          <view class="editor-actions">
            <button class="secondary-button" @tap="editingTime = false">取消</button>
            <button class="primary-button" :loading="saving" @tap="saveRoundTime">保存时间</button>
          </view>
        </view>
        <text class="round-progress">全联盟登记 {{ roundSummary.registered_count }}/{{ roundSummary.total_count }}</text>
        <text class="round-progress">本轮参与部落 {{ roundSummary.total_count }} 个</text>
        <text class="snapshot-tip">场次创建后新增、启用或转移的部落只参加下一场。</text>
        <button v-if="roundSummary.round.status === 'scheduled'" class="primary-button round-button" :loading="saving" @tap="openRound">开放本轮</button>
        <button v-if="roundSummary.round.status === 'completed'" class="primary-button round-button" @tap="creatingNextRound = true">创建下一场</button>
        <button v-if="isCreator && roundSummary.round.status !== 'cancelled'" class="danger-button" @tap="cancelRound">撤销整场</button>
        <text class="form-tip">登记功能是否可用由独立灰度开关控制；所有撤销都会保留原始流水。</text>

        <view v-if="roundMatches.length" class="round-results">
          <text class="result-section-title">本场匹配结果</text>
          <view v-for="item in roundMatches" :key="item.match_id" class="round-result-row">
            <view>
              <text class="result-title">{{ item.clan_name }} · {{ registrationLabel(item.registration_status) }}</text>
              <text class="result-meta">匹配 #{{ item.match_id }} · {{ item.opponent_name || item.opponent_tag || '-' }}</text>
            </view>
            <text v-if="isCreator && item.registration_status !== 'revoked'" class="action-link" @tap="revokeMatch(item)">撤销</text>
            <text v-else-if="isCreator" class="action-link" @tap="reopenMatch(item)">重新开放</text>
          </view>
        </view>
      </view>

      <view v-else class="round-create">
        <text class="form-title">{{ roundSummary.round ? '创建下一场' : '创建首场互刷场次' }}</text>
        <view class="datetime-row">
          <picker mode="date" :value="roundDate" @change="roundDate = $event.detail.value">
            <view class="picker-field">{{ roundDate || '选择日期' }}</view>
          </picker>
          <picker mode="time" :value="roundTime" @change="roundTime = $event.detail.value">
            <view class="picker-field">{{ roundTime || '选择时间' }}</view>
          </picker>
        </view>
        <button class="primary-button" :loading="saving" :disabled="saving" @tap="createRound">创建场次</button>
        <text class="form-tip">预计纳入 {{ eligibleClanCount }} 个启用部落。请按北京时间录入全联盟统一开始搜战的时间。</text>
        <text class="snapshot-tip">创建后会固定本轮参与部落；之后新增、启用或转移的部落只参加下一场。</text>
      </view>
    </view>
    <view class="bottom-space"></view>
  </view>
</template>

<script>
import {
  cancelFarmRound,
  createFarmRound,
  getFarmAdminAccounts,
  getFarmAdminClans,
  getFarmDashboard,
  getFarmMe,
  getFarmRoundResults,
  reopenFarmMatch,
  revokeFarmMatch,
  updateFarmRound
} from '@/utils/api.js'

export default {
  data() {
    return {
      loading: true,
      saving: false,
      error: '',
      me: {},
      roundSummary: { round: null, registered_count: 0, total_count: 0, clans: [] },
      roundDate: '',
      roundTime: '11:00',
      creatingNextRound: false,
      editingTime: false,
      eligibleClanCount: 0
    }
  },
  computed: {
    isCreator() { return this.me.role === 'creator' },
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
    roundStatus(status) { return ({ scheduled: '待开放', open: '可登记', partially_registered: '登记中', completed: '已完成', cancelled: '已撤销' })[status] || status },
    registrationLabel(status) { return ({ internal_matched: '内部匹配', match_failed: '匹配失败', revoked: '已撤销' })[status] || status },
    formatRoundTime(value) {
      if (!value) return '-'
      const date = new Date(value)
      const pad = n => String(n).padStart(2, '0')
      return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
    },
    async load() {
      this.loading = true
      this.error = ''
      try {
        this.me = await getFarmMe()
        if (!['creator', 'admin'].includes(this.me.role)) throw new Error('当前账号没有场次管理权限')
        const result = await Promise.all([
          getFarmDashboard(),
          getFarmAdminClans(),
          getFarmAdminAccounts()
        ])
        const dashboard = result[0]
        const activeAccountIds = new Set(
          (result[2].accounts || [])
            .filter(item => item.status === 'active')
            .map(item => Number(item.id))
        )
        this.eligibleClanCount = (result[1].clans || []).filter(item => (
          item.status === 'active' && activeAccountIds.has(Number(item.account_id))
        )).length
        this.roundSummary = dashboard.round ? await getFarmRoundResults(dashboard.round.id) : dashboard
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
    createRound() {
      if (this.saving) return
      const date = this.roundDate || this.defaultRoundDate()
      this.roundDate = date
      uni.showModal({
        title: '确认创建场次',
        content: `开始搜战时间：${date} ${this.roundTime}\n参与部落：${this.eligibleClanCount} 个\n创建后部落名单将固定。`,
        success: result => { if (result.confirm) this.submitCreateRound(date) }
      })
    },
    async submitCreateRound(date) {
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
      uni.showModal({
        title: '确认开放本轮',
        content: `开放后，${this.roundSummary.total_count} 个参与部落可以开始登记。确认时间和名单均正确吗？`,
        success: result => {
          if (result.confirm) this.runUpdate(() => updateFarmRound(this.roundSummary.round.id, { status: 'open' }))
        }
      })
    },
    startEditTime() {
      const value = this.roundSummary.round.scheduled_at_beijing || ''
      this.roundDate = value.slice(0, 10)
      this.roundTime = value.slice(11, 16)
      this.editingTime = true
    },
    saveRoundTime() {
      if (!this.roundDate || !this.roundTime || this.saving) return
      uni.showModal({
        title: '确认修改时间',
        content: `新的开始搜战时间：${this.roundDate} ${this.roundTime}\n首次有效登记后将不能再修改。`,
        success: result => {
          if (!result.confirm) return
          this.runUpdate(() => updateFarmRound(this.roundSummary.round.id, {
            scheduled_at: `${this.roundDate}T${this.roundTime}:00+08:00`
          })).then(succeeded => { if (succeeded) this.editingTime = false })
        }
      })
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
    reopenMatch(item) {
      uni.showModal({
        title: '重新开放匹配',
        content: '双方将恢复为未登记状态，可以再次调用 COC API 登记；原匹配和冲销流水会继续保留。',
        success: result => {
          if (result.confirm) this.runUpdate(() => reopenFarmMatch(item.match_id))
        }
      })
    },
    async runUpdate(action) {
      if (this.saving) return false
      this.saving = true
      try {
        await action()
        await this.load()
        return true
      } catch (e) {
        uni.showModal({ title: '操作失败', content: e.message, showCancel: false })
        return false
      } finally { this.saving = false }
    }
  }
}
</script>

<style>
.farm-page { min-height: 100vh; padding: 28rpx 26rpx; box-sizing: border-box; background: #0f0f23; color: #eef1f8; }.page-state { display: flex; min-height: 70vh; flex-direction: column; align-items: center; justify-content: center; gap: 24rpx; color: #7f899f; font-size: 26rpx; }.state-error { color: #d78383; }.small-button { padding: 0 32rpx; border: 1rpx solid #31537d; border-radius: 12rpx; background: transparent; color: #76aee6; font-size: 24rpx; }
.round-admin-card { padding: 0 24rpx 24rpx; border: 1rpx solid #2a3152; border-radius: 18rpx; background: #191a31; }.section-head { display: flex; align-items: flex-start; justify-content: space-between; padding: 28rpx 0 24rpx; }.section-title, .section-desc { display: block; }.section-title { font-size: 30rpx; font-weight: 650; }.section-desc { margin-top: 8rpx; color: #717c93; font-size: 21rpx; }.section-count { flex-shrink: 0; margin-left: 20rpx; padding: 7rpx 14rpx; border-radius: 18rpx; background: rgba(68,137,204,.16); color: #7cb6eb; font-size: 20rpx; }
.round-label, .round-time, .round-progress { display: block; }.round-label { color: #75839d; font-size: 21rpx; }.round-time { margin-top: 8rpx; font-size: 32rpx; font-weight: 650; }.round-progress { margin-top: 10rpx; color: #7f899f; font-size: 22rpx; }.edit-time { display: inline-block; padding: 14rpx 0 4rpx; }.time-editor { padding: 20rpx; border: 1rpx solid #30375b; border-radius: 14rpx; background: #14162a; }.editor-actions { display: flex; gap: 14rpx; }.editor-actions button { flex: 1; }.round-button { margin-top: 22rpx; }.form-title { display: block; margin-bottom: 20rpx; font-size: 27rpx; font-weight: 600; }.datetime-row { display: flex; gap: 14rpx; }.datetime-row picker { flex: 1; min-width: 0; }.picker-field { display: flex; height: 76rpx; align-items: center; justify-content: center; margin-bottom: 16rpx; padding: 0 20rpx; border: 1rpx solid #30375b; border-radius: 12rpx; box-sizing: border-box; background: #121326; color: #aeb7ca; font-size: 25rpx; }
.primary-button, .secondary-button { display: flex; height: 78rpx; align-items: center; justify-content: center; border-radius: 12rpx; font-size: 26rpx; font-weight: 600; }.primary-button { background: #397fc0; color: #fff; }.secondary-button { border: 1rpx solid #35405f; background: transparent; color: #8793aa; }.primary-button::after, .secondary-button::after { border: 0; }.danger-button { display: flex; height: 72rpx; align-items: center; justify-content: center; margin-top: 16rpx; border: 1rpx solid #663a48; border-radius: 12rpx; background: transparent; color: #cf7e82; font-size: 24rpx; }.danger-button::after { border: 0; }.form-tip, .snapshot-tip { display: block; margin-top: 16rpx; color: #626c84; font-size: 21rpx; line-height: 1.55; }.snapshot-tip { color: #8d7f6c; }
.round-results { margin-top: 26rpx; border-top: 1rpx solid #292f4e; }.result-section-title { display: block; padding: 24rpx 0 8rpx; color: #a9b3c7; font-size: 23rpx; font-weight: 600; }.round-result-row { display: flex; min-height: 82rpx; align-items: center; justify-content: space-between; border-bottom: 1rpx solid #292f4e; }.round-result-row:last-child { border-bottom: 0; }.result-title, .result-meta { display: block; }.result-title { font-size: 23rpx; }.result-meta { margin-top: 5rpx; color: #707a91; font-size: 20rpx; }.action-link { padding: 18rpx 0 18rpx 30rpx; color: #77aee3; font-size: 23rpx; }.bottom-space { height: 50rpx; }
</style>
