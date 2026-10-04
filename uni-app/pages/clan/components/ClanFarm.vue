<template>
  <view class="clan-farm-root">
    <view class="clan-farm-tabs"><view class="clan-farm-tab" :class="{ active: tab === 'clans' }" @tap="tab = 'clans'">部落</view><view class="clan-farm-tab" :class="{ active: tab === 'members' }" @tap="tab = 'members'">成员</view></view>
    <view v-if="loading" class="clan-farm-state"><text>加载中...</text></view>
    <view v-else-if="error" class="clan-farm-state"><text class="clan-farm-error">{{ error }}</text><text class="clan-farm-retry" @tap="fetchData">点击重试</text></view>
    <view v-else-if="tab === 'clans' && !clans.length" class="clan-farm-state"><text>暂无互刷部落</text></view>
    <scroll-view v-else scroll-y class="clan-farm-scroll">
      <view class="clan-farm-inner">
        <view class="clan-farm-update"><text v-if="displayUpdatedAt">数据更新于 {{ displayUpdatedAt }}</text><text v-if="tab === 'members'" class="clan-farm-threshold">速本阈值：&gt; {{ rushedDegreeThreshold }} · 不活跃名单仅供清退参考</text></view>
        <template v-if="tab === 'clans'">
          <view v-for="clan in clans" :key="clan.clan_tag" class="clan-farm-card">
            <view class="clan-farm-header"><text class="clan-farm-name">{{ clan.clan_name }}</text><text class="clan-farm-tag">{{ clan.clan_tag }}</text><text class="clan-farm-badge">互刷</text><text class="clan-farm-count">{{ clan.member_count }}/50人</text></view>
            <view class="clan-farm-section"><view class="clan-farm-section-title">部落实时配置（大本数目）</view><view class="clan-farm-table"><view class="clan-farm-tr clan-farm-head"><text class="clan-farm-td clan-farm-avg">平均</text><text v-for="level in thLevels" :key="level" class="clan-farm-td">{{ level }}</text><text class="clan-farm-td">其他</text></view><view class="clan-farm-tr"><text class="clan-farm-td clan-farm-avg">{{ clan.realtime.avg_th }}</text><text v-for="level in thLevels" :key="level" class="clan-farm-td">{{ clan.realtime.distribution[level] || 0 }}</text><text class="clan-farm-td">{{ otherCount(clan.realtime.distribution) }}</text></view></view></view>
            <view class="clan-farm-section"><view class="clan-farm-section-title">去速本后实时配置（大本数目）</view><view v-if="clan.despeed.has_war" class="clan-farm-table"><view class="clan-farm-tr clan-farm-head"><text class="clan-farm-td clan-farm-avg">平均</text><text v-for="level in thLevels" :key="level" class="clan-farm-td">{{ level }}</text><text class="clan-farm-td">其他</text></view><view class="clan-farm-tr"><text class="clan-farm-td clan-farm-avg">{{ clan.despeed.avg_th }}</text><text v-for="level in thLevels" :key="level" class="clan-farm-td">{{ clan.despeed.distribution[level] || 0 }}</text><text class="clan-farm-td">{{ otherCount(clan.despeed.distribution) }}</text></view></view><view v-else class="clan-farm-no-war">{{ clan.despeed.error ? '部落战数据获取失败，请重新同步' : '当前无部落战' }}</view></view>
          </view>
        </template>
        <template v-else>
          <view v-for="clan in memberClans" :key="clan.tag" class="clan-farm-card">
            <view class="clan-farm-header"><text class="clan-farm-name">{{ clan.name }}</text><text class="clan-farm-tag">{{ clan.tag }}</text><text class="clan-farm-count">速本 {{ clan.members.length }} · 填坑 {{ clan.fillAccounts.length }} · 不活跃 {{ clan.inactiveMembers.length }}</text></view>
            <view class="clan-farm-list-section">
              <view class="clan-farm-list-title"><text>去速本候选</text><text>{{ clan.members.length }}人</text></view>
              <view v-if="clan.members.length" class="clan-farm-member-table"><view class="clan-farm-member-row clan-farm-member-head"><text>昵称</text><text>当前本</text><text>去速本</text><text>速本度</text><text>排名</text></view><view v-for="member in clan.members" :key="member.player_tag" class="clan-farm-member-row"><text>{{ member.account_name }}</text><text>{{ member.town_hall_level || '-' }}</text><text>{{ member.despeed_town_hall || '-' }}</text><text>{{ member.rushed_degree || 0 }}</text><text>{{ member.map_position || '-' }}</text></view></view>
              <view v-else class="clan-farm-members-empty">{{ clan.emptyMessage }}</view>
            </view>
            <view class="clan-farm-list-section">
              <view class="clan-farm-list-title"><text>填坑号</text><text>{{ clan.fillAccounts.length }}人</text></view>
              <view v-if="clan.fillAccounts.length" class="clan-farm-detail-list"><view class="clan-farm-detail-head"><text>成员</text><text>身份</text></view><view v-for="member in clan.fillAccounts" :key="member.player_tag" class="clan-farm-detail-row"><view class="clan-farm-detail-main"><text class="clan-farm-detail-name">{{ member.account_name || '-' }}</text><text class="clan-farm-detail-meta">{{ member.player_tag || '-' }}</text></view><view class="clan-farm-detail-side"><text>TH{{ member.town_hall_level || '-' }} · {{ formatRole(member.clan_role) }}</text><text class="clan-farm-detail-meta">编号 {{ fillNumbers(member) }}</text></view></view></view>
              <view v-else class="clan-farm-members-empty">当前部落暂无填坑号</view>
            </view>
            <view class="clan-farm-list-section">
              <view class="clan-farm-list-title"><text>最不活跃成员</text><text>{{ clan.inactiveMembers.length }}/5人</text></view>
              <view v-if="clan.inactiveMembers.length" class="clan-farm-detail-list"><view class="clan-farm-detail-head"><text>成员</text><text>活动情况</text></view><view v-for="member in clan.inactiveMembers" :key="member.player_tag" class="clan-farm-detail-row"><view class="clan-farm-detail-main"><text class="clan-farm-detail-name">{{ member.account_name || '-' }}</text><text class="clan-farm-detail-meta">{{ member.player_tag || '-' }} · TH{{ member.town_hall_level || '-' }} · {{ formatRole(member.clan_role) }}</text></view><view class="clan-farm-detail-side"><text>{{ inactiveText(member) }}</text><text class="clan-farm-detail-meta">{{ activityReason(member) }}</text></view></view></view>
              <view v-else class="clan-farm-members-empty">暂无可供比较的普通成员</view>
            </view>
          </view>
        </template>
        <view class="clan-farm-bottom"></view>
      </view>
    </scroll-view>
  </view>
</template>

<script>
import { getFarmConfig } from '@/utils/api.js'

const RUSHED_DEGREE_THRESHOLD = 1
let farmCache = null

export default {
  name: 'ClanFarm',
  data() { return { loading: true, error: '', clans: [], updatedAt: '', memberUpdatedAt: '', thLevels: ['18', '17', '16', '15', '14', '13', '12', '11'], tab: 'clans', rushedDegreeThreshold: RUSHED_DEGREE_THRESHOLD } },
  computed: {
    displayUpdatedAt() { return this.tab === 'members' ? (this.memberUpdatedAt || this.updatedAt) : this.updatedAt },
    memberClans() {
      return this.clans.map(clan => {
        const despeed = clan.despeed || {}
        const fillAccounts = clan.fill_accounts || []
        const members = (clan.replace_candidates || []).filter(member => Number(member.rushed_degree) > this.rushedDegreeThreshold)
        let emptyMessage = `暂无速本度大于 ${this.rushedDegreeThreshold} 的成员`
        if (clan.error || despeed.error) emptyMessage = '部落战数据获取失败，请重新同步'
        else if (!despeed.has_war) emptyMessage = '当前无部落战，暂无成员速本数据'
        return { tag: clan.clan_tag, name: clan.clan_name || clan.clan_tag, members, fillAccounts, inactiveMembers: clan.inactive_members || [], emptyMessage }
      })
    }
  },
  created() { if (farmCache) { this.applyResponse(farmCache); this.loading = false } else this.fetchData() },
  methods: {
    applyResponse(response) { this.clans = response.clans || []; this.updatedAt = response.updated_at ? this.formatTime(response.updated_at) : ''; this.memberUpdatedAt = response.member_updated_at ? this.formatTime(response.member_updated_at) : '' },
    async fetchData() { this.loading = true; this.error = ''; try { const response = await getFarmConfig(); farmCache = response; this.applyResponse(response) } catch (e) { this.error = e.message || '加载失败' } finally { this.loading = false } },
    formatTime(value) { if (!value) return ''; const date = new Date(value.replace('+00:00', 'Z')); if (isNaN(date.getTime())) return value; return `${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}` },
    otherCount(distribution) { return (distribution['10'] || 0) + (distribution.below_10 || 0) },
    formatRole(value) { return ({ leader: '首领', coLeader: '副首领', admin: '长老', member: '成员' }[value] || value || '-') },
    fillNumbers(member) { return (member.account_numbers || []).join('、') || '-' },
    inactiveText(member) {
      const value = member.activity_reference_at
      if (!value) return '暂无观察数据'
      const date = new Date(String(value).replace('+00:00', 'Z'))
      if (isNaN(date.getTime())) return '活动时间未知'
      const hours = Math.max(0, Math.floor((Date.now() - date.getTime()) / 3600000))
      const elapsed = hours < 24 ? `${hours}小时` : `${Math.floor(hours / 24)}天`
      return member.never_observed_activity ? `观察${elapsed}未检测活动` : `${elapsed}未检测活动`
    },
    activityReason(member) {
      if (member.never_observed_activity) return '观察以来无有效变化'
      const labels = { donations: '捐兵', donations_received: '收兵', exp_level: '经验升级', town_hall_level: '大本升级', season_attack_wins: '赛季进攻', name: '改名', player_house: '玩家小屋', war_attack: '部落战出刀', cwl_attack: '联赛出刀' }
      const values = (member.last_activity_reasons || []).map(item => labels[item] || item)
      return values.length ? `最近依据：${values.join('、')}` : '最近活动依据未记录'
    }
  }
}
</script>

<style>
.clan-farm-root { flex: 1; min-height: 0; display: flex; flex-direction: column; background: #0f0f23; }
.clan-farm-tabs { display: flex; flex-shrink: 0; height: 72rpx; background: #141428; border-bottom: 1rpx solid #1a1a2e; }
.clan-farm-tab { flex: 1; display: flex; align-items: center; justify-content: center; color: #66708a; font-size: 28rpx; }.clan-farm-tab.active { color: #4a90d9; font-weight: 600; border-bottom: 4rpx solid #4a90d9; }
.clan-farm-state { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; color: #8890a0; font-size: 28rpx; }.clan-farm-error { color: #e06060; margin-bottom: 20rpx; }.clan-farm-retry { color: #4a90d9; padding: 14rpx; }
.clan-farm-scroll { flex: 1; height: 0; }.clan-farm-inner { padding: 20rpx 24rpx 0; }.clan-farm-update { padding-bottom: 20rpx; color: #556078; font-size: 24rpx; text-align: center; }.clan-farm-threshold { display: block; margin-top: 8rpx; color: #aab4c8; }
.clan-farm-card { width: 100%; box-sizing: border-box; margin-bottom: 30rpx; background: #1a1a2e; border: 1rpx solid #2a2a4a; border-radius: 16rpx; overflow: hidden; }.clan-farm-header { display: flex; flex-wrap: wrap; align-items: center; padding: 24rpx; border-bottom: 1rpx solid #2a2a4a; }.clan-farm-name { color: #fff; font-size: 30rpx; font-weight: 600; }.clan-farm-tag { margin: 0 12rpx 0 8rpx; color: #8e8eb0; font-size: 21rpx; }.clan-farm-badge { padding: 4rpx 12rpx; color: #4a90d9; background: rgba(74,144,217,.15); border-radius: 8rpx; font-size: 21rpx; }.clan-farm-count { margin-left: auto; color: #8890a0; font-size: 23rpx; }
.clan-farm-section { padding: 20rpx 18rpx 24rpx; }.clan-farm-section-title { margin-bottom: 16rpx; color: #8890a0; font-size: 25rpx; }.clan-farm-table { background: rgba(74,144,217,.08); border-radius: 8rpx; overflow: hidden; }.clan-farm-tr { display: flex; align-items: center; height: 68rpx; }.clan-farm-head { color: #8890a0; }.clan-farm-td { flex: 1; min-width: 0; color: #d0d0d8; font-size: 21rpx; text-align: center; }.clan-farm-avg { color: #4a90d9; font-weight: 600; }.clan-farm-no-war { padding: 24rpx 0; color: #66708a; font-size: 24rpx; text-align: center; }
.clan-farm-member-table { margin: 0 18rpx 12rpx; background: #18182b; border: 1rpx solid #272743; border-radius: 8rpx; overflow: hidden; }.clan-farm-member-row { display: flex; min-height: 64rpx; align-items: center; border-bottom: 1rpx solid #272743; }.clan-farm-member-row:last-child { border-bottom: 0; }.clan-farm-member-row text { flex: 1; color: #aeb4c2; font-size: 22rpx; font-weight: 400; text-align: center; }.clan-farm-member-row text:first-child { flex: 2; padding-left: 12rpx; text-align: left; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }.clan-farm-member-head { background: #1d1d35; }.clan-farm-member-head text { color: #8f98aa; font-size: 21rpx; font-weight: 500; }.clan-farm-members-empty { padding: 80rpx 0; color: #626b80; font-size: 26rpx; text-align: center; }.clan-farm-card-empty { padding: 42rpx 20rpx; }.clan-farm-bottom { height: 30rpx; }
.clan-farm-list-section { padding: 20rpx 0 4rpx; border-bottom: 1rpx solid #252542; }.clan-farm-list-section:last-child { border-bottom: 0; padding-bottom: 20rpx; }.clan-farm-list-title { display: flex; justify-content: space-between; padding: 0 20rpx 16rpx; color: #9ca5b7; font-size: 25rpx; font-weight: 600; }.clan-farm-list-title text:last-child { color: #626b80; font-size: 22rpx; font-weight: 400; }.clan-farm-list-section .clan-farm-members-empty { padding: 28rpx 20rpx 36rpx; font-size: 23rpx; }.clan-farm-detail-list { margin: 0 18rpx 12rpx; background: #18182b; border: 1rpx solid #272743; border-radius: 8rpx; overflow: hidden; }.clan-farm-detail-head { display: flex; align-items: center; justify-content: space-between; height: 64rpx; padding: 0 16rpx; background: #1d1d35; box-sizing: border-box; color: #8f98aa; font-size: 21rpx; font-weight: 500; }.clan-farm-detail-row { display: flex; align-items: center; justify-content: space-between; gap: 16rpx; min-height: 88rpx; padding: 12rpx 16rpx; border-bottom: 1rpx solid #272743; box-sizing: border-box; }.clan-farm-detail-row:last-child { border-bottom: 0; }.clan-farm-detail-main, .clan-farm-detail-side { display: flex; min-width: 0; flex-direction: column; gap: 6rpx; color: #aeb4c2; font-size: 22rpx; font-weight: 400; }.clan-farm-detail-main { flex: 1; }.clan-farm-detail-side { flex: 1; align-items: flex-end; text-align: right; }.clan-farm-detail-name { color: #aeb4c2; font-size: 22rpx; font-weight: 400; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }.clan-farm-detail-meta { color: #626b80; font-size: 19rpx; font-weight: 400; }
</style>
