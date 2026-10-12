<template>
  <view class="clan-overview-root">
    <view v-if="loading" class="clan-overview-state"><text>加载部落概览...</text></view>
    <view v-else-if="error" class="clan-overview-state">
      <text class="clan-overview-error">{{ error }}</text>
      <text class="clan-overview-retry" @tap="fetchData">点击重试</text>
    </view>
    <scroll-view v-else scroll-y class="clan-overview-scroll">
      <view class="clan-overview-inner">
        <view class="clan-overview-summary">
          <text>自有部落 · {{ clans.length }} 个</text>
          <text v-if="updatedAt">更新于 {{ formatTime(updatedAt) }}</text>
        </view>
        <view v-if="!clans.length" class="clan-overview-empty">
          <text class="clan-overview-empty-title">当前联盟还没有部落</text>
          <text class="clan-overview-empty-tip">添加后会进入后台同步队列，首次数据可能需要等待。</text>
          <button v-if="canManageClans" class="clan-overview-manage primary" @tap="openClanManagement">添加第一个部落</button>
          <text v-else class="clan-overview-empty-tip">请联系联盟管理员添加部落</text>
        </view>
        <view
          v-for="clan in clans"
          :key="clan.clan_tag"
          class="clan-overview-card"
          @tap="$emit('open-detail', clan.clan_tag)"
        >
          <view class="clan-overview-card-head">
            <view class="clan-overview-title-wrap">
              <text class="clan-overview-name">{{ clan.clan_name }}</text>
              <text class="clan-overview-tag">{{ clan.clan_tag }}</text>
              <text class="clan-overview-badge">{{ clan.category_label }}</text>
            </view>
            <text class="clan-overview-count">{{ clan.member_count }}/{{ clan.capacity || 50 }} 人</text>
          </view>
          <view class="clan-overview-grid">
            <view class="clan-overview-metric"><text class="clan-overview-label">平均大本</text><text class="clan-overview-value">{{ clan.member_count ? clan.average_town_hall : '-' }}</text></view>
            <view class="clan-overview-metric"><text class="clan-overview-label">人均奖杯</text><text class="clan-overview-value">{{ clan.member_count ? clan.average_trophies : '-' }}</text></view>
            <view class="clan-overview-metric"><text class="clan-overview-label">赛季捐兵</text><text class="clan-overview-value">{{ clan.total_donations || 0 }}</text></view>
            <view class="clan-overview-metric"><text class="clan-overview-label">首领</text><text class="clan-overview-value clan-overview-ellipsis">{{ clan.leader_name || '-' }}</text></view>
          </view>
          <view class="clan-overview-operating-status">
            <view class="clan-overview-status-item">
              <text class="clan-overview-status-label">部落战</text>
              <text :class="['clan-overview-status-value', statusTone('war', clan.war_status)]">{{ statusLabel('war', clan.war_status) }}</text>
            </view>
            <view class="clan-overview-status-item">
              <text class="clan-overview-status-label">都城</text>
              <text :class="['clan-overview-status-value', statusTone('capital', clan.capital_status)]">{{ statusLabel('capital', clan.capital_status) }}</text>
            </view>
          </view>
          <view class="clan-overview-sync">
            <view class="clan-overview-sync-meta">
              <text>{{ clan.updated_at ? '同步于 ' + formatTime(clan.updated_at) : '等待首次同步' }}</text>
              <text v-if="clan.verification_status && clan.verification_status !== 'verified'" class="clan-overview-verification">{{ verificationLabel(clan.verification_status) }}</text>
            </view>
            <text class="clan-overview-detail-hint">查看详情</text>
          </view>
        </view>
        <button v-if="clans.length && canManageClans" class="clan-overview-manage" @tap="openClanManagement">管理部落</button>
        <view class="clan-overview-bottom"></view>
      </view>
    </scroll-view>
  </view>
</template>

<script>
import { getClanOverview } from '@/utils/api.js'
import { getCurrentAlliance, getCurrentAllianceId } from '@/utils/alliance.js'

const overviewCache = Object.create(null)

export default {
  name: 'ClanOverview',
  data() {
    return { loading: true, refreshing: false, error: '', clans: [], updatedAt: '' }
  },
  created() {
    const cache = overviewCache[getCurrentAllianceId() || 'public']
    if (cache) {
      this.applyResponse(cache)
      this.loading = false
      this.fetchData(false)
    } else {
      this.fetchData()
    }
  },
  computed: {
    canManageClans() {
      const alliance = getCurrentAlliance()
      if (!alliance || ['admin', 'leader'].indexOf(alliance.role) < 0) return false
      const code = alliance.plan && alliance.plan.code
      const state = alliance.plan && alliance.plan.status
      return code === 'free' || (code === 'paid' && ['active', 'legacy'].indexOf(state) >= 0)
    }
  },
  methods: {
    openClanManagement() {
      uni.navigateTo({ url: '/pages/settings/clan-management' })
    },
    applyResponse(res) {
      this.clans = res.clans || []
      this.updatedAt = res.updated_at || ''
    },
    refresh() {
      this.fetchData(false)
    },
    async fetchData(showLoading = true) {
      if (this.refreshing) return
      const cacheKey = getCurrentAllianceId() || 'public'
      this.refreshing = true
      if (showLoading && !this.clans.length) this.loading = true
      this.error = ''
      try {
        const res = await getClanOverview()
        overviewCache[cacheKey] = res
        this.applyResponse(res)
      } catch (e) {
        this.error = e.message || '加载失败'
      } finally {
        this.loading = false
        this.refreshing = false
      }
    },
    formatTime(value) {
      if (!value) return '-'
      const date = new Date(String(value).replace('+00:00', 'Z'))
      if (isNaN(date.getTime())) return String(value)
      const month = String(date.getMonth() + 1).padStart(2, '0')
      const day = String(date.getDate()).padStart(2, '0')
      const hour = String(date.getHours()).padStart(2, '0')
      const minute = String(date.getMinutes()).padStart(2, '0')
      return `${month}-${day} ${hour}:${minute}`
    },
    statusMeta(type, value) {
      if (!value || value.error) return { label: '状态未知', highlighted: false }
      const status = value.status || 'sync_pending'
      const maps = {
        war: {
          preparation: { label: '准备日', highlighted: true },
          in_war: { label: '战斗日', highlighted: true },
          cwl: { label: '联赛中', highlighted: true },
          war_ended: { label: '已结束', highlighted: false },
          not_in_war: { label: '无战争', highlighted: false }
        },
        capital: {
          not_started: { label: '未开启', highlighted: false },
          ongoing: { label: '突袭中', highlighted: true },
          ended: { label: '未到时间', highlighted: true },
          missed: { label: '未到时间', highlighted: true }
        }
      }
      return (maps[type] && maps[type][status]) || { label: '状态未知', highlighted: false }
    },
    statusLabel(type, value) {
      return this.statusMeta(type, value).label
    },
    statusTone(type, value) {
      return this.statusMeta(type, value).highlighted ? 'is-highlighted' : 'is-muted'
    },
    verificationLabel(value) {
      return ({ unverified: '未认证', pending: '认证中', disputed: '有争议' })[value] || '未认证'
    }
  }
}
</script>

<style>
.clan-overview-root { flex: 1; min-height: 0; display: flex; flex-direction: column; background: #0f0f23; }
.clan-overview-scroll { flex: 1; height: 0; }
.clan-overview-inner { padding: 20rpx 24rpx 0; }
.clan-overview-state { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; color: #8890a0; font-size: 28rpx; }
.clan-overview-error { color: #e06060; margin-bottom: 20rpx; }
.clan-overview-retry { color: #5fa8ff; padding: 16rpx 28rpx; }
.clan-overview-summary { display: flex; justify-content: space-between; margin: 0 4rpx 18rpx; color: #66708a; font-size: 22rpx; }
.clan-overview-empty { min-height: 430rpx; padding: 70rpx 36rpx; box-sizing: border-box; display: flex; flex-direction: column; align-items: center; justify-content: center; border: 1rpx solid #252542; border-radius: 16rpx; background: #18182d; text-align: center; }
.clan-overview-empty-title { color: #d7dbe6; font-size: 29rpx; font-weight: 600; }
.clan-overview-empty-tip { margin-top: 16rpx; color: #6f788e; font-size: 22rpx; line-height: 1.6; }
.clan-overview-manage { margin: 8rpx 0 0; border: 1rpx solid #303958; border-radius: 12rpx; color: #79b4f2; background: #1b2338; font-size: 25rpx; line-height: 2.6; }
.clan-overview-manage.primary { width: 360rpx; margin-top: 30rpx; color: #fff; border-color: #315f9a; background: #315f9a; }
.clan-overview-manage::after { border: 0; }
.clan-overview-card { margin-bottom: 22rpx; padding: 24rpx; box-sizing: border-box; background: #1a1a2e; border: 1rpx solid #2a2a4a; border-radius: 16rpx; }
.clan-overview-card:active { background: #20203a; }
.clan-overview-card-head { display: flex; align-items: center; justify-content: space-between; }
.clan-overview-title-wrap { flex: 1; min-width: 0; display: flex; align-items: center; }
.clan-overview-name { min-width: 0; max-width: 330rpx; color: #f4f4fa; font-size: 31rpx; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.clan-overview-tag { flex-shrink: 0; margin-left: 10rpx; color: #777f96; font-size: 21rpx; }
.clan-overview-badge { flex-shrink: 0; margin-left: 12rpx; padding: 5rpx 14rpx; color: #5fa8ff; background: rgba(74, 144, 217, 0.15); border-radius: 8rpx; font-size: 21rpx; }
.clan-overview-count { flex-shrink: 0; margin-left: 14rpx; color: #aab4c8; font-size: 24rpx; }
.clan-overview-grid { display: flex; margin-top: 20rpx; padding: 18rpx 0; border-top: 1rpx solid #2a2a4a; border-bottom: 1rpx solid #2a2a4a; }
.clan-overview-metric { flex: 1; min-width: 0; display: flex; flex-direction: column; align-items: center; border-right: 1rpx solid #2a2a4a; }
.clan-overview-metric:last-child { border-right: 0; }
.clan-overview-label { color: #66708a; font-size: 21rpx; }
.clan-overview-value { width: 100%; margin-top: 8rpx; color: #969daf; font-size: 27rpx; text-align: center; }
.clan-overview-ellipsis { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.clan-overview-operating-status { display: flex; padding-top: 14rpx; }
.clan-overview-status-item { flex: 1; min-width: 0; display: flex; align-items: center; justify-content: center; gap: 12rpx; }
.clan-overview-status-item + .clan-overview-status-item { border-left: 1rpx solid #2a2a4a; }
.clan-overview-status-label { color: #66708a; font-size: 21rpx; }
.clan-overview-status-value { font-size: 23rpx; font-weight: 500; }
.clan-overview-status-value.is-highlighted { color: #5fa8ff; }
.clan-overview-status-value.is-muted { color: #7f8799; }
.clan-overview-sync { display: flex; justify-content: space-between; padding-top: 16rpx; color: #5d6478; font-size: 21rpx; }
.clan-overview-sync-meta { display: flex; align-items: center; min-width: 0; }
.clan-overview-verification { flex-shrink: 0; margin-left: 10rpx; padding: 3rpx 9rpx; color: #c49a56; background: rgba(196, 154, 86, .10); border-radius: 7rpx; font-size: 18rpx; }
.clan-overview-detail-hint { color: #5fa8ff; }
.clan-overview-bottom { height: 32rpx; }
</style>
