<template>
  <view v-if="visible" class="page-refresh" @tap.stop="requestRefresh">
    <text :class="['page-refresh-text', { disabled: disabled }]">{{ label }}</text>
  </view>
</template>

<script>
import { requestAlliancePageRefresh } from '@/utils/api.js'
import { getCurrentAllianceId } from '@/utils/alliance.js'

const OPEN_STATES = ['pending', 'running', 'retry_wait']

export default {
  name: 'PageRefreshButton',
  props: {
    clanTag: { type: String, required: true },
    resourceTypes: { type: Array, required: true },
    period: { type: String, default: '' },
    refresh: { type: Object, default: () => ({ allowed: false, resources: [] }) }
  },
  data() {
    return { submitting: false, localRefresh: null, pollTimer: null, pollCount: 0, nowMs: Date.now() }
  },
  computed: {
    state() { return this.localRefresh || this.refresh || { allowed: false, resources: [] } },
    resources() { return this.state.resources || [] },
    visible() { return Boolean(this.state.allowed && this.clanTag) },
    hasOpenTask() {
      return this.resources.some(item => OPEN_STATES.indexOf(item.task_status || item.state) >= 0)
    },
    canRequest() {
      return this.resources.some(item => item.can_request)
    },
    nextAllowedAt() {
      const times = this.resources
        .map(item => item.next_allowed_at ? Date.parse(item.next_allowed_at) : 0)
        .filter(value => value > this.nowMs)
      return times.length ? Math.min.apply(null, times) : 0
    },
    failed() {
      return this.resources.some(item => ['failed', 'dead'].indexOf(item.task_status || item.state) >= 0)
    },
    disabled() { return this.submitting || this.hasOpenTask || !this.canRequest },
    label() {
      if (this.submitting || this.hasOpenTask) return '正在刷新…'
      if (this.canRequest) return this.failed ? '重新刷新' : '刷新'
      if (this.nextAllowedAt) {
        const minutes = Math.max(1, Math.ceil((this.nextAllowedAt - this.nowMs) / 60000))
        return `${minutes}分钟后可刷新`
      }
      if (this.failed) return '刷新失败，显示上次缓存'
      return '暂不可刷新'
    }
  },
  watch: {
    refresh: {
      deep: true,
      immediate: true,
      handler(value) {
        this.localRefresh = value || null
        if (this.hasOpenTask) this.startPolling()
        else this.stopPolling()
      }
    }
  },
  beforeDestroy() { this.stopPolling() },
  methods: {
    async requestRefresh() {
      if (this.disabled) return
      this.submitting = true
      try {
        const result = await requestAlliancePageRefresh(
          getCurrentAllianceId(), this.clanTag, this.resourceTypes, this.period
        )
        this.localRefresh = result.refresh || this.localRefresh
        this.$emit('reload')
        if (this.hasOpenTask) this.startPolling()
      } catch (e) {
        uni.showToast({ title: e.message || '刷新请求失败', icon: 'none' })
      } finally {
        this.submitting = false
      }
    },
    startPolling() {
      if (this.pollTimer) return
      this.pollCount = 0
      this.pollTimer = setInterval(() => {
        this.pollCount += 1
        this.nowMs = Date.now()
        this.$emit('reload')
        if (this.pollCount >= 24) this.stopPolling()
      }, 5000)
    },
    stopPolling() {
      if (this.pollTimer) clearInterval(this.pollTimer)
      this.pollTimer = null
      this.pollCount = 0
      this.nowMs = Date.now()
    }
  }
}
</script>

<style>
.page-refresh { flex-shrink: 0; margin-left: 14rpx; padding: 10rpx 16rpx; border: 1rpx solid #315386; border-radius: 10rpx; background: #1b2943; }
.page-refresh-text { color: #73b6ff; font-size: 21rpx; white-space: nowrap; }
.page-refresh-text.disabled { color: #687086; }
</style>
