<template>
  <view class="clan-detail-root">
    <view v-if="loading" class="clan-detail-state"><text>加载部落详情...</text></view>
    <view v-else-if="error" class="clan-detail-state">
      <text class="clan-detail-error">{{ error }}</text>
      <text class="clan-detail-retry" @tap="fetchData">点击重试</text>
    </view>
    <scroll-view v-else scroll-y class="clan-detail-scroll">
      <view class="clan-detail-inner">
        <view class="clan-detail-back" @tap="$emit('back-overview')">‹ 返回部落概览</view>

        <view class="clan-detail-card clan-detail-hero">
          <view class="clan-detail-profile-row">
            <view class="clan-detail-emblem-wrap">
              <image v-if="badgeUrl && !badgeLoadError" class="clan-detail-emblem" :src="badgeUrl" mode="aspectFit" @error="badgeLoadError = true" />
              <view v-else class="clan-detail-emblem-fallback">🛡️</view>
              <text v-if="profile.clan_level" class="clan-detail-level">LV.{{ profile.clan_level }}</text>
            </view>
            <view class="clan-detail-profile-main">
              <view class="clan-detail-title-row">
                <text class="clan-detail-name">{{ profile.name || detail.clan_name }}</text>
                <text class="clan-detail-badge">{{ detail.category_label }}</text>
              </view>
              <text class="clan-detail-tag">{{ detail.clan_tag }}</text>
              <view class="clan-detail-member-line">
                <text>👥 {{ displayMemberCount }}/{{ detail.capacity || 50 }}</text>
                <text class="clan-detail-separator">·</text>
                <text>{{ joinTypeLabel(profile.join_type) }}</text>
              </view>
            </view>
          </view>
          <view class="clan-detail-facts">
            <view><text class="clan-detail-fact-label">平均大本</text><text class="clan-detail-fact-value">{{ detail.member_count ? detail.average_town_hall : '-' }}</text></view>
            <view><text class="clan-detail-fact-label">人均奖杯</text><text class="clan-detail-fact-value">{{ detail.member_count ? formatNumber(detail.average_trophies) : '-' }}</text></view>
            <view><text class="clan-detail-fact-label">首领</text><text class="clan-detail-fact-value">{{ detail.leader_name || '-' }}</text></view>
          </view>
          <text v-if="detail.profile_status === 'stale'" class="clan-detail-stale">官方资料本次同步失败，正在显示上次缓存</text>
          <text v-else-if="!hasProfile" class="clan-detail-stale">官方资料等待同步</text>
          <text class="clan-detail-updated">{{ detail.profile_updated_at ? '官方资料更新于 ' + formatTime(detail.profile_updated_at) : (detail.updated_at ? '成员更新于 ' + formatTime(detail.updated_at) : '等待首次同步') }}</text>
        </view>

        <view v-if="hasProfile" class="clan-detail-card">
          <text class="clan-detail-card-title">部落战</text>
          <view class="clan-detail-war-grid">
            <view><text class="clan-detail-war-value clan-detail-win">{{ profile.war_wins }}</text><text>胜场</text></view>
            <view><text class="clan-detail-war-value clan-detail-tie">{{ profile.war_ties }}</text><text>平局</text></view>
            <view><text class="clan-detail-war-value clan-detail-loss">{{ profile.war_losses }}</text><text>败场</text></view>
            <view><text class="clan-detail-war-value">{{ profile.war_win_streak }}</text><text>当前连胜</text></view>
          </view>
          <view class="clan-detail-info-row"><text>部落战联赛</text><text>{{ namedValue(profile.war_league) }}</text></view>
          <view class="clan-detail-info-row"><text>开战频率</text><text>{{ warFrequencyLabel(profile.war_frequency) }}</text></view>
        </view>

        <view v-if="hasProfile" class="clan-detail-card">
          <text class="clan-detail-card-title">部落积分</text>
          <view class="clan-detail-points-grid">
            <view><text>🏆 部落奖杯</text><text>{{ formatNumber(profile.clan_points) }}</text></view>
            <view><text>🏛️ 夜世界</text><text>{{ formatNumber(profile.builder_base_points) }}</text></view>
            <view><text>🎖️ 都城奖杯</text><text>{{ formatNumber(profile.capital_points) }}</text></view>
          </view>
          <view class="clan-detail-info-row"><text>都城联赛</text><text>{{ namedValue(profile.capital_league) }}</text></view>
        </view>

        <view v-if="hasProfile" class="clan-detail-card">
          <text class="clan-detail-card-title">基础资料</text>
          <view class="clan-detail-info-row"><text>所在地</text><text>{{ locationLabel }}</text></view>
          <view class="clan-detail-info-row"><text>加入门槛</text><text>{{ requirementLabel }}</text></view>
          <view class="clan-detail-info-row"><text>战争日志</text><text>{{ profile.is_war_log_public ? '公开' : '不公开' }}</text></view>
          <view class="clan-detail-info-row"><text>家庭友好</text><text>{{ profile.is_family_friendly ? '是' : '否' }}</text></view>
          <view v-if="profile.labels && profile.labels.length" class="clan-detail-labels">
            <text v-for="label in profile.labels" :key="label.id" class="clan-detail-label">{{ labelName(label.name) }}</text>
          </view>
        </view>

        <view v-if="profile.description" class="clan-detail-card">
          <text class="clan-detail-card-title">部落描述</text>
          <text class="clan-detail-description">{{ profile.description }}</text>
        </view>

        <view class="clan-detail-card">
          <text class="clan-detail-card-title">大本分布</text>
          <view v-if="detail.town_hall_distribution && detail.town_hall_distribution.length" class="clan-detail-distribution">
            <view v-for="item in detail.town_hall_distribution" :key="item.level" class="clan-detail-dist-item">
              <text class="clan-detail-dist-label">{{ item.level }}本</text><text class="clan-detail-dist-value">{{ item.count }}</text>
            </view>
          </view>
          <text v-else class="clan-detail-empty">暂无数据</text>
        </view>

        <view class="clan-detail-card">
          <text class="clan-detail-card-title">职位分布</text>
          <view class="clan-detail-role-list">
            <view v-for="role in roleRows" :key="role.key" class="clan-detail-role-row"><text>{{ role.label }}</text><text>{{ role.count }} 人</text></view>
          </view>
        </view>

        <view class="clan-detail-card">
          <text class="clan-detail-card-title">本赛季捐兵</text>
          <view class="clan-detail-donation-grid">
            <view><text>捐出</text><text>{{ formatNumber(detail.total_donations) }}</text></view>
            <view><text>收到</text><text>{{ formatNumber(detail.total_donations_received) }}</text></view>
            <view><text>人均捐出</text><text>{{ formatNumber(detail.average_donations) }}</text></view>
          </view>
        </view>

        <view class="clan-detail-actions">
          <view class="clan-detail-action clan-detail-primary" @tap="$emit('open-members', detail.clan_tag)">👥 查看该部落成员</view>
          <view v-if="canOpenStats" class="clan-detail-action" @tap="$emit('open-stats')">⚔️ 查看战营数据</view>
          <view v-if="detail.category === 'farm'" class="clan-detail-action" @tap="$emit('open-farm')">🔄 查看互刷数据</view>
        </view>
        <view class="clan-detail-bottom"></view>
      </view>
    </scroll-view>
  </view>
</template>

<script>
import { getClanOverviewDetail } from '@/utils/api.js'

const detailCache = {}
const COMBAT_CLAN_TAG = '#2QQ'
const LABEL_NAMES = { 'Clan Wars': '部落战', 'Clan War League': '部落战联赛', 'Trophy Pushing': '冲杯', 'Clan Games': '部落竞赛', 'Clan Capital': '部落都城', Donations: '捐兵', Farming: '打资源', Relaxed: '休闲', Competitive: '竞技', 'Newbie Friendly': '新手友好', Talkative: '活跃聊天', International: '国际' }

export default {
  name: 'ClanDetail',
  props: { clanTag: { type: String, required: true } },
  data() { return { loading: true, error: '', detail: {}, badgeLoadError: false } },
  computed: {
    profile() { return this.detail.profile || {} },
    hasProfile() { return !!this.detail.profile },
    badgeUrl() { const urls = this.profile.badge_urls || {}; return urls.large || urls.medium || urls.small || '' },
    displayMemberCount() { return this.profile.official_member_count || this.detail.member_count || 0 },
    canOpenStats() { return this.detail.clan_tag === COMBAT_CLAN_TAG },
    locationLabel() { const location = this.profile.location || {}; return location.name || '-' },
    requirementLabel() {
      const items = []
      if (this.profile.required_town_hall_level) items.push(`${this.profile.required_town_hall_level}本`)
      if (this.profile.required_trophies) items.push(`${this.formatNumber(this.profile.required_trophies)}杯`)
      return items.length ? items.join(' · ') : '无要求'
    },
    roleRows() {
      const source = this.detail.role_distribution || {}
      return [
        { key: 'leader', label: '首领', count: source.leader || 0 },
        { key: 'coLeader', label: '副首领', count: source.coLeader || 0 },
        { key: 'admin', label: '长老', count: source.admin || 0 },
        { key: 'member', label: '成员', count: source.member || 0 }
      ]
    }
  },
  watch: { clanTag() { this.load() } },
  created() { this.load() },
  methods: {
    load() {
      this.badgeLoadError = false
      if (detailCache[this.clanTag]) { this.detail = detailCache[this.clanTag]; this.loading = false; this.$emit('loaded', this.detail) } else this.fetchData()
    },
    async fetchData() {
      this.loading = true; this.error = ''; this.badgeLoadError = false
      try { const detail = await getClanOverviewDetail(this.clanTag); detailCache[this.clanTag] = detail; this.detail = detail; this.$emit('loaded', detail) }
      catch (e) { this.error = e.message || '加载失败' }
      finally { this.loading = false }
    },
    formatNumber(value) {
      const number = Number(value || 0)
      return String(Math.round(number)).replace(/\B(?=(\d{3})+(?!\d))/g, ',')
    },
    namedValue(value) { return value && value.name ? value.name : '-' },
    labelName(value) { return LABEL_NAMES[value] || value || '-' },
    joinTypeLabel(value) { return ({ inviteOnly: '仅限受邀', open: '任何人可加入', closed: '不可加入' }[value] || '加入方式未知') },
    warFrequencyLabel(value) { return ({ always: '始终', moreThanOncePerWeek: '每周多次', oncePerWeek: '每周一次', lessThanOncePerWeek: '少于每周一次', never: '从不', unknown: '未设置' }[value] || '-') },
    formatTime(value) {
      if (!value) return '-'
      const date = new Date(String(value).replace('+00:00', 'Z'))
      if (isNaN(date.getTime())) return String(value)
      return `${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
    }
  }
}
</script>

<style>
.clan-detail-root { flex: 1; min-height: 0; display: flex; flex-direction: column; background: #0f0f23; }
.clan-detail-scroll { flex: 1; height: 0; }.clan-detail-inner { padding: 18rpx 24rpx 0; }
.clan-detail-state { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; color: #8890a0; font-size: 28rpx; }.clan-detail-error { color: #e06060; margin-bottom: 20rpx; }.clan-detail-retry { color: #5fa8ff; padding: 16rpx 28rpx; }
.clan-detail-back { display: flex; align-items: center; min-height: 80rpx; margin-bottom: 16rpx; padding: 0 24rpx; color: #5fa8ff; background: #1a1a2e; border-radius: 12rpx; font-size: 28rpx; }
.clan-detail-card { margin-bottom: 20rpx; padding: 24rpx; background: #1a1a2e; border: 1rpx solid #2a2a4a; border-radius: 16rpx; }
.clan-detail-profile-row { display: flex; align-items: center; }.clan-detail-emblem-wrap { width: 150rpx; flex-shrink: 0; display: flex; flex-direction: column; align-items: center; }.clan-detail-emblem { width: 132rpx; height: 132rpx; }.clan-detail-emblem-fallback { display: flex; width: 112rpx; height: 112rpx; align-items: center; justify-content: center; color: #66708a; background: #252540; border-radius: 50%; font-size: 58rpx; }.clan-detail-level { margin-top: 4rpx; color: #8992aa; font-size: 20rpx; }
.clan-detail-profile-main { flex: 1; min-width: 0; margin-left: 18rpx; }.clan-detail-title-row { display: flex; align-items: center; }.clan-detail-name { min-width: 0; color: #f4f4fa; font-size: 34rpx; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }.clan-detail-badge { flex-shrink: 0; margin-left: 12rpx; padding: 6rpx 14rpx; color: #5fa8ff; background: rgba(74,144,217,.15); border-radius: 8rpx; font-size: 22rpx; }.clan-detail-tag { display: block; margin-top: 10rpx; color: #777f96; font-size: 22rpx; }.clan-detail-member-line { display: flex; align-items: center; margin-top: 14rpx; color: #a7adbd; font-size: 25rpx; }.clan-detail-separator { margin: 0 12rpx; color: #555d72; }
.clan-detail-facts { display: flex; margin-top: 22rpx; padding-top: 20rpx; border-top: 1rpx solid #2a2a4a; }.clan-detail-facts > view { flex: 1; min-width: 0; display: flex; flex-direction: column; align-items: center; border-right: 1rpx solid #2a2a4a; }.clan-detail-facts > view:last-child { border-right: 0; }.clan-detail-fact-label { color: #66708a; font-size: 21rpx; }.clan-detail-fact-value { width: 100%; margin-top: 8rpx; color: #a2a9ba; font-size: 27rpx; text-align: center; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.clan-detail-stale { display: block; margin-top: 18rpx; color: #c49a56; font-size: 21rpx; text-align: center; }.clan-detail-updated { display: block; margin-top: 12rpx; color: #5d6478; font-size: 21rpx; text-align: center; }
.clan-detail-card-title { display: block; margin-bottom: 20rpx; color: #d6d9e2; font-size: 28rpx; font-weight: 600; }
.clan-detail-war-grid { display: flex; margin-bottom: 18rpx; }.clan-detail-war-grid > view { flex: 1; min-width: 0; display: flex; flex-direction: column; align-items: center; color: #737b90; font-size: 20rpx; }.clan-detail-war-value { margin-bottom: 6rpx; color: #aeb5c5; font-size: 30rpx; }.clan-detail-win { color: #65b886; }.clan-detail-tie { color: #62a6d8; }.clan-detail-loss { color: #d36e76; }
.clan-detail-points-grid { display: flex; margin-bottom: 18rpx; }.clan-detail-points-grid > view { flex: 1; min-width: 0; display: flex; flex-direction: column; align-items: center; color: #737b90; font-size: 20rpx; }.clan-detail-points-grid > view text:last-child { margin-top: 8rpx; color: #aeb5c5; font-size: 28rpx; }
.clan-detail-info-row { display: flex; justify-content: space-between; min-height: 60rpx; align-items: center; color: #777f96; font-size: 24rpx; border-top: 1rpx solid #252540; }.clan-detail-info-row text:last-child { max-width: 430rpx; color: #aeb5c5; text-align: right; }
.clan-detail-labels { display: flex; flex-wrap: wrap; margin-top: 18rpx; }.clan-detail-label { margin: 0 12rpx 12rpx 0; padding: 7rpx 14rpx; color: #7faee2; background: rgba(74,144,217,.12); border-radius: 8rpx; font-size: 22rpx; }
.clan-detail-description { display: block; color: #a6adbd; font-size: 25rpx; line-height: 1.7; white-space: pre-wrap; }
.clan-detail-distribution { display: flex; flex-wrap: wrap; }.clan-detail-dist-item { width: 25%; box-sizing: border-box; display: flex; flex-direction: column; align-items: center; margin-bottom: 20rpx; }.clan-detail-dist-label { color: #7d859c; font-size: 22rpx; }.clan-detail-dist-value { margin-top: 6rpx; color: #5fa8ff; font-size: 30rpx; }.clan-detail-empty { display: block; color: #66708a; font-size: 24rpx; text-align: center; }
.clan-detail-role-row { display: flex; justify-content: space-between; min-height: 58rpx; align-items: center; color: #a7adbd; font-size: 25rpx; border-bottom: 1rpx solid #252540; }.clan-detail-role-row:last-child { border-bottom: 0; }
.clan-detail-donation-grid { display: flex; }.clan-detail-donation-grid > view { flex: 1; display: flex; flex-direction: column; align-items: center; color: #7d859c; font-size: 22rpx; }.clan-detail-donation-grid > view text:last-child { margin-top: 8rpx; color: #aeb5c5; font-size: 29rpx; }
.clan-detail-actions { margin-top: 8rpx; }.clan-detail-action { display: flex; min-height: 84rpx; align-items: center; justify-content: center; margin-bottom: 16rpx; color: #c5cad8; background: #1a1a2e; border: 1rpx solid #2a2a4a; border-radius: 12rpx; font-size: 27rpx; }.clan-detail-action:active { background: #252540; }.clan-detail-primary { color: #fff; background: #306da8; border-color: #4a90d9; }.clan-detail-bottom { height: 28rpx; }
</style>
