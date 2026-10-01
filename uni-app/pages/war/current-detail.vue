<template>
  <view class="detail-page">
    <TopBar :title="isHistory ? '历史部落战' : '当前部落战'" :showBack="true" :backFallback="historyListFallback" />

    <view v-if="loading" class="state-box"><text class="state-text">加载战争详情...</text></view>
    <view v-else-if="loadError" class="state-box">
      <text class="error-text">{{ loadError }}</text><text class="retry-btn" @tap="fetchDetail">点击重试</text>
    </view>
    <view v-else-if="!war" class="state-box"><text class="state-text">暂无战争数据</text></view>
    <view v-else-if="war.status === 'cwl'" class="state-box">
      <text class="state-icon">🏆</text><text class="state-text">当前正在进行联赛</text><text class="state-hint">请前往“联赛 → 战斗日”查看</text>
    </view>
    <view v-else-if="war.status === 'not_in_war' || war.status === 'sync_pending'" class="state-box">
      <text class="state-icon">⚔️</text><text class="state-text">{{ war.status === 'sync_pending' ? '数据正在同步' : '当前无部落战' }}</text>
    </view>
    <view v-else-if="war.status === 'error'" class="state-box">
      <text class="error-text">{{ war.error || '无法获取当前部落战' }}</text>
    </view>

    <view v-else class="detail-content">
      <view v-if="war.is_stale" class="sync-warning">本次更新失败，当前显示 {{ formatFullTime(war.synced_at) }} 的缓存数据，系统将自动重试</view>
      <view class="war-overview">
        <view class="overview-title-row">
          <text class="overview-title">部落战 · {{ statusLabel(war.status) }}</text>
          <text class="result-label" :class="resultClass(war.result)">{{ resultLabel(war.result) }}</text>
          <button class="share-btn" open-type="share">分享</button>
        </view>
        <view class="match-row">
          <view class="match-side own-side"><text class="match-name">{{ war.clan.name }}</text><text class="match-tag">{{ war.clan.tag }}</text></view>
          <text class="versus">VS</text>
          <view class="match-side enemy-side"><text class="match-name">{{ war.opponent.name }}</text><text class="match-tag">{{ war.opponent.tag }}</text></view>
        </view>
        <view class="time-info">
          <text>开战：{{ formatFullTime(war.start_time) }}</text>
          <text>结束：{{ formatFullTime(war.end_time) }}</text>
          <text class="countdown">{{ countdownLabel() }}</text>
        </view>
        <view class="score-summary">
          <view class="score-side">
            <text>{{ war.clan.attacks }}/{{ war.clan.total_attacks }}刀</text><text>{{ war.clan.stars }}⭐</text><text>{{ formatPercent(war.clan.destruction_percentage) }}</text>
          </view>
          <text class="score-divider">—</text>
          <view class="score-side enemy-score">
            <text>{{ war.opponent.attacks }}/{{ war.opponent.total_attacks }}刀</text><text>{{ war.opponent.stars }}⭐</text><text>{{ formatPercent(war.opponent.destruction_percentage) }}</text>
          </view>
        </view>
        <text v-if="war.synced_at" class="updated-at">数据更新于 {{ formatFullTime(war.synced_at) }}</text>
      </view>

      <view class="table-note">左右滑动查看完整对战表</view>
      <scroll-view scroll-x class="war-table-scroll">
        <view class="table-inner">
          <view class="group-row">
            <view class="group-seq">序号</view>
            <view class="side-group own-group">我方 · {{ war.clan.name }}</view>
            <view class="side-group enemy-group">对方 · {{ war.opponent.name }}</view>
          </view>
          <view class="tr tr-head">
            <view class="td w-seq">序号</view>
            <view class="td w-name">己方名称</view><view class="td w-th">本</view><view class="td w-attack">第一刀</view><view class="td w-pos">对位</view><view class="td w-attack">第二刀</view><view class="td w-pos">对位</view><view class="td w-attack">防守</view><view class="td w-pos">对位</view><view class="td w-count">防守次数</view>
            <view class="td w-name enemy-head">对手名称</view><view class="td w-th enemy-head">本</view><view class="td w-attack enemy-head">第一刀</view><view class="td w-pos enemy-head">对位</view><view class="td w-attack enemy-head">第二刀</view><view class="td w-pos enemy-head">对位</view><view class="td w-attack enemy-head">防守</view><view class="td w-pos enemy-head">对位</view><view class="td w-count enemy-head">防守次数</view>
          </view>
          <view class="table-body">
            <view v-for="row in war.rows" :key="row.position" class="tr" :class="{ even: row.position % 2 === 0 }">
              <view class="td w-seq seq-cell">{{ row.position }}</view>
              <view class="td w-name name-cell">{{ memberName(row.clan_member) }}</view><view class="td w-th th-cell">{{ memberTh(row.clan_member) }}</view>
              <view class="td w-attack" :class="attackClass(attackAt(row.clan_member, 0), false)">{{ formatAttack(attackAt(row.clan_member, 0), '未出刀') }}</view><view class="td w-pos">{{ attackTarget(attackAt(row.clan_member, 0)) }}</view>
              <view class="td w-attack" :class="attackClass(attackAt(row.clan_member, 1), false)">{{ formatAttack(attackAt(row.clan_member, 1), '未出刀') }}</view><view class="td w-pos">{{ attackTarget(attackAt(row.clan_member, 1)) }}</view>
              <view class="td w-attack" :class="attackClass(defenseBest(row.clan_member), true)">{{ formatAttack(defenseBest(row.clan_member)) }}</view><view class="td w-pos">{{ defensePosition(row.clan_member) }}</view><view class="td w-count">{{ defenseCount(row.clan_member) }}</view>
              <view class="td w-name name-cell enemy-cell">{{ memberName(row.opponent_member) }}</view><view class="td w-th th-cell enemy-cell">{{ memberTh(row.opponent_member) }}</view>
              <view class="td w-attack enemy-cell" :class="attackClass(attackAt(row.opponent_member, 0), false)">{{ formatAttack(attackAt(row.opponent_member, 0), '未出刀') }}</view><view class="td w-pos enemy-cell">{{ attackTarget(attackAt(row.opponent_member, 0)) }}</view>
              <view class="td w-attack enemy-cell" :class="attackClass(attackAt(row.opponent_member, 1), false)">{{ formatAttack(attackAt(row.opponent_member, 1), '未出刀') }}</view><view class="td w-pos enemy-cell">{{ attackTarget(attackAt(row.opponent_member, 1)) }}</view>
              <view class="td w-attack enemy-cell" :class="attackClass(defenseBest(row.opponent_member), true)">{{ formatAttack(defenseBest(row.opponent_member)) }}</view><view class="td w-pos enemy-cell">{{ defensePosition(row.opponent_member) }}</view><view class="td w-count enemy-cell">{{ defenseCount(row.opponent_member) }}</view>
            </view>
          </view>
        </view>
      </scroll-view>
      <view class="bottom-space"></view>
    </view>
  </view>
</template>

<script>
import TopBar from '@/components/TopBar.vue'
import { getCurrentWar, getWarHistoryDetail } from '@/utils/api.js'

const CACHE_REFRESH_INTERVAL_MS = 60 * 1000

export default {
  components: { TopBar },
  data() {
    return { clanTag: '', warKey: '', war: null, loading: true, loadError: '', nowMs: Date.now(), clockTimer: null, refreshTimer: null }
  },
  computed: {
    isHistory() { return !!this.warKey },
    historyListFallback() { return this.isHistory ? `/pages/war/war?view=history&clan_tag=${encodeURIComponent(this.clanTag)}` : '/pages/war/war' }
  },
  onLoad(options) {
    try { this.clanTag = decodeURIComponent((options && options.clan_tag) || '') } catch (e) { this.clanTag = (options && options.clan_tag) || '' }
    try { this.warKey = decodeURIComponent((options && options.war_key) || '') } catch (e) { this.warKey = (options && options.war_key) || '' }
    this.fetchDetail()
  },
  onShow() { if (!this.isHistory) this.startTimers() },
  onHide() { this.stopTimers() },
  onUnload() { this.stopTimers() },
  async onPullDownRefresh() {
    await this.fetchDetail()
    uni.stopPullDownRefresh()
  },
  onShareAppMessage() {
    const history = this.isHistory ? `&war_key=${encodeURIComponent(this.warKey)}` : ''
    return { title: `苍穹联赛助手｜${this.war ? this.war.clan_name : (this.isHistory ? '历史部落战' : '当前部落战')}`, path: `/pages/war/current-detail?clan_tag=${encodeURIComponent(this.clanTag)}${history}` }
  },
  onShareTimeline() {
    const history = this.isHistory ? `&war_key=${encodeURIComponent(this.warKey)}` : ''
    return { title: `苍穹联赛助手｜${this.war ? this.war.clan_name : (this.isHistory ? '历史部落战' : '当前部落战')}`, query: `clan_tag=${encodeURIComponent(this.clanTag)}${history}` }
  },
  methods: {
    async fetchDetail() {
      if (!this.clanTag) { this.loadError = '缺少部落标签'; this.loading = false; return }
      if (!this.war) this.loading = true
      this.loadError = ''
      try { this.war = this.isHistory ? await getWarHistoryDetail(this.clanTag, this.warKey) : await getCurrentWar(this.clanTag) }
      catch (e) { this.loadError = e.message || '战争详情加载失败' }
      finally { this.loading = false }
    },
    startTimers() {
      this.stopTimers()
      this.nowMs = Date.now()
      this.clockTimer = setInterval(() => { this.nowMs = Date.now() }, 1000)
      this.refreshTimer = setInterval(() => { this.fetchDetail() }, CACHE_REFRESH_INTERVAL_MS)
    },
    stopTimers() {
      if (this.clockTimer) clearInterval(this.clockTimer)
      if (this.refreshTimer) clearInterval(this.refreshTimer)
      this.clockTimer = null; this.refreshTimer = null
    },
    statusLabel(status) { return ({ in_war: '战斗日', preparation: '准备日', war_ended: '已结束' })[status] || status },
    resultLabel(result) { return ({ leading: '当前领先', losing: '当前落后', tied: '当前平局', victory: '胜利', defeat: '失败', pending: '尚未开战' })[result] || '-' },
    resultClass(result) {
      if (['leading', 'victory'].indexOf(result) >= 0) return 'result-win'
      if (['losing', 'defeat'].indexOf(result) >= 0) return 'result-loss'
      return 'result-tied'
    },
    memberName(member) { return member ? member.name : '-' },
    memberTh(member) { return member && member.town_hall_level ? member.town_hall_level : '-' },
    attackAt(member, index) { return member && member.attacks ? member.attacks[index] : null },
    defenseBest(member) { return member && member.defense ? member.defense.best_attack : null },
    attackTarget(attack) { return attack && attack.target_position ? attack.target_position : '-' },
    defensePosition(member) {
      const best = this.defenseBest(member)
      return best && best.attacker_position ? best.attacker_position : '-'
    },
    defenseCount(member) {
      if (!member || !member.defense) return '0/0'
      return `${member.defense.three_star_count}/${member.defense.total_attacks}`
    },
    formatAttack(attack, emptyText = '-') {
      if (!attack) return emptyText
      return `${'★'.repeat(Number(attack.stars || 0))}${'☆'.repeat(Math.max(0, 3 - Number(attack.stars || 0)))} ${Number(attack.destruction_percentage || 0).toFixed(0)}%`
    },
    attackClass(attack, defense) {
      if (!attack) return 'attack-empty'
      const stars = Number(attack.stars || 0)
      if (defense) return stars === 3 ? 'attack-bad' : stars === 2 ? 'attack-mid' : 'attack-good'
      return stars === 3 ? 'attack-good' : stars === 2 ? 'attack-mid' : 'attack-bad'
    },
    formatPercent(value) { return `${Number(value || 0).toFixed(2)}%` },
    parseTime(value) {
      if (!value) return null
      const text = String(value); const match = text.match(/^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})/)
      if (match) return new Date(`${match[1]}-${match[2]}-${match[3]}T${match[4]}:${match[5]}:${match[6]}Z`)
      const date = new Date(text.replace('+00:00', 'Z')); return isNaN(date.getTime()) ? null : date
    },
    formatFullTime(value) {
      const date = this.parseTime(value)
      if (!date) return '-'
      const pad = number => String(number).padStart(2, '0')
      return `${date.getFullYear()}/${pad(date.getMonth() + 1)}/${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
    },
    countdownLabel() {
      if (!this.war) return '-'
      if (this.war.status === 'war_ended') return `结束于 ${this.formatFullTime(this.war.end_time)}`
      const preparation = this.war.status === 'preparation'
      const target = this.parseTime(preparation ? this.war.start_time : this.war.end_time)
      if (!target) return '-'
      const seconds = Math.max(0, Math.floor((target.getTime() - this.nowMs) / 1000))
      const days = Math.floor(seconds / 86400); const hours = Math.floor((seconds % 86400) / 3600); const minutes = Math.floor((seconds % 3600) / 60)
      return `${preparation ? '距离开战' : '距离结束'}：${days ? days + '天 ' : ''}${hours}小时${minutes}分钟`
    }
  }
}
</script>

<style>
.detail-page { min-height: 100vh; background: #0f0f23; color: #d8dce8; }.state-box { min-height: 70vh; padding: 40rpx; display: flex; flex-direction: column; align-items: center; justify-content: center; box-sizing: border-box; }.state-icon { margin-bottom: 20rpx; font-size: 70rpx; }.state-text { color: #aab4c8; font-size: 29rpx; }.state-hint { margin-top: 12rpx; color: #66708a; font-size: 24rpx; }.error-text { margin-bottom: 18rpx; color: #e17055; font-size: 26rpx; text-align: center; }.retry-btn { color: #5fa8ff; font-size: 25rpx; }
.detail-content { padding-bottom: 40rpx; }.sync-warning { margin: 20rpx 24rpx 0; padding: 14rpx 18rpx; border-radius: 9rpx; color: #fdcb6e; background: rgba(253,203,110,.1); font-size: 22rpx; line-height: 1.5; }.war-overview { margin: 20rpx 24rpx; padding: 22rpx; border: 1rpx solid #2a2a4a; border-radius: 14rpx; background: #18182d; }.overview-title-row { display: flex; align-items: center; }.overview-title { color: #fff; font-size: 29rpx; font-weight: 600; }.result-label { margin-left: 12rpx; font-size: 23rpx; font-weight: 600; }.result-win { color: #00b894; }.result-loss { color: #e17055; }.result-tied { color: #fdcb6e; }.share-btn { margin: 0 0 0 auto; padding: 7rpx 16rpx; border: 0; border-radius: 6rpx; color: #aab4c8; background: #252540; font-size: 22rpx; line-height: 1.5; }.share-btn::after { border: 0; }
.match-row { margin-top: 22rpx; display: flex; align-items: center; }.match-side { flex: 1; display: flex; flex-direction: column; }.enemy-side { align-items: flex-end; }.match-name { max-width: 270rpx; overflow: hidden; color: #f0f0f5; font-size: 27rpx; text-overflow: ellipsis; white-space: nowrap; }.match-tag { margin-top: 5rpx; color: #66708a; font-size: 20rpx; }.versus { margin: 0 18rpx; color: #4a90d9; font-size: 24rpx; font-weight: 600; }.time-info { margin-top: 20rpx; display: flex; flex-direction: column; color: #747c91; font-size: 22rpx; line-height: 1.7; }.countdown { color: #fdcb6e; }.score-summary { margin-top: 18rpx; padding-top: 16rpx; display: flex; align-items: center; border-top: 1rpx solid #252540; }.score-side { flex: 1; display: flex; justify-content: space-between; color: #d8dce8; font-size: 23rpx; }.enemy-score { text-align: right; }.score-divider { margin: 0 16rpx; color: #4a90d9; }.updated-at { display: block; margin-top: 14rpx; color: #596178; font-size: 20rpx; text-align: center; }
.table-note { margin: 20rpx 24rpx 10rpx; color: #66708a; font-size: 22rpx; }.war-table-scroll { width: 100%; }.table-inner, .group-row, .tr { width: 1648rpx; }.table-inner { margin: 0; border-top: 1rpx solid #343452; border-bottom: 1rpx solid #343452; background: #15152a; }.group-row, .tr { display: flex; flex-direction: row; box-sizing: border-box; }.group-row { height: 64rpx; color: #fff; font-size: 23rpx; font-weight: 600; }.group-seq { width: 56rpx; display: flex; align-items: center; justify-content: center; box-sizing: border-box; border-right: 1rpx solid #3a3a5a; background: #242440; }.side-group { width: 796rpx; display: flex; align-items: center; justify-content: center; box-sizing: border-box; border-right: 1rpx solid #3a3a5a; }.own-group { color: #9fc9ff; background: #202846; }.enemy-group { color: #f7ba83; background: #422d2b; }
.tr { min-height: 68rpx; align-items: stretch; border-bottom: 1rpx solid #2a2a44; }.tr-head { min-height: 78rpx; color: #dfe5f0; background: #242440; font-weight: 600; }.even { background: #19192f; }.td { flex-shrink: 0; min-height: 68rpx; padding: 5rpx; display: flex; align-items: center; justify-content: center; box-sizing: border-box; border-right: 1rpx solid #30304a; color: #c9cfda; font-size: 21rpx; text-align: center; white-space: nowrap; overflow: hidden; }.tr-head .td { min-height: 78rpx; font-size: 20rpx; }.enemy-head { background: #332b3b; }.enemy-cell { background: rgba(74,45,45,.12); }.w-seq { width: 56rpx; }.w-name { width: 170rpx; }.w-th { width: 54rpx; }.w-attack { width: 110rpx; }.w-pos { width: 54rpx; }.w-count { width: 80rpx; }.seq-cell { color: #74b9ff; font-weight: 600; }.name-cell { padding: 0 10rpx; justify-content: flex-start; text-overflow: ellipsis; }.th-cell { color: #74b9ff; font-weight: 600; }.attack-good { color: #00b894; }.attack-mid { color: #fdcb6e; }.attack-bad { color: #e17055; }.attack-empty { color: #596178; }.bottom-space { height: 80rpx; }
</style>
