<template>
  <view class="detail-page">
    <TopBar title="返回参赛部落" :showBack="true" :backFallback="listFallback" />

    <view v-if="loading" class="state-box"><text class="state-text">加载联赛数据...</text></view>
    <view v-else-if="loadError && !detail" class="state-box">
      <text class="error-text">{{ loadError }}</text>
      <text class="retry-btn" @tap="fetchDetail">点击重试</text>
    </view>

    <view v-else-if="detail" class="detail-content">
      <view class="team-card">
        <view class="team-title-row">
          <picker v-if="availableTeams.length > 1" :range="availableTeams" range-key="display_name" @change="switchTeam">
            <view class="team-picker">{{ detail.team.team_name || detail.team.team_alias }}⌄</view>
          </picker>
          <text v-else class="team-name">{{ detail.team.team_name || detail.team.team_alias }}</text>
          <text class="team-tag">{{ detail.team.clan_tag }}</text>
          <button class="share-btn" open-type="share">分享</button>
        </view>
        <view class="team-meta">
          <text>{{ detail.team.team_alias }}</text><text>{{ detail.team.league_level || '未定级' }}</text>
          <text v-if="detail.summary.rank">当前第{{ detail.summary.rank }}名</text>
          <text>{{ summaryResultText(detail.summary) }}</text>
        </view>
        <text v-if="detail.error" class="cache-warning">{{ detail.error }}（已保留最近成功数据）</text>
        <text v-if="detail.updated_at" class="updated-at">数据更新于 {{ formatTime(detail.updated_at) }}</text>
      </view>

      <view class="inner-tab-bar">
        <view class="inner-tab" :class="{ active: activeView === 'war-day' }" @tap="activeView = 'war-day'">战斗日</view>
        <view class="inner-tab" :class="{ active: activeView === 'overview' }" @tap="activeView = 'overview'">联赛总览</view>
      </view>

      <view v-if="activeView === 'war-day'" class="war-day-pane">
        <scroll-view v-if="rounds.length" scroll-x class="round-scroll">
          <view class="round-tabs">
            <view v-for="item in rounds" :key="item.round" class="round-tab" :class="[{ active: selectedRoundNumber === item.round }, 'round-' + item.status]" @tap="selectedRoundNumber = item.round">
              <text>第{{ item.round }}场</text><text class="round-status">{{ roundStatusLabel(item.status) }}</text>
            </view>
          </view>
        </scroll-view>

        <view v-if="!rounds.length" class="empty-box">{{ detail.status === 'waiting' ? '等待联赛开启' : '暂无战斗日数据' }}</view>
        <view v-else-if="selectedRound && !selectedRound.clan" class="empty-box">第{{ selectedRound.round }}场{{ selectedRound.status === 'bye' ? '轮空' : '数据暂不可用' }}</view>
        <view v-else-if="selectedRound" class="round-content">
          <view class="match-card">
            <view class="match-heading"><text>联赛第{{ selectedRound.round }}场 · {{ roundStatusLabel(selectedRound.status) }}</text><text class="result-label" :class="resultClass(selectedRound.result)">{{ roundResultLabel(selectedRound) }}</text></view>
            <view class="match-row">
              <view class="match-side"><text class="match-name">{{ selectedRound.clan.name }}</text><text class="match-tag">{{ selectedRound.clan.tag }}</text></view>
              <text class="versus">VS</text>
              <view class="match-side enemy-side"><text class="match-name">{{ selectedRound.opponent.name }}</text><text class="match-tag">{{ selectedRound.opponent.tag }}</text></view>
            </view>
            <view class="score-row">
              <text>{{ selectedRound.clan.attacks }}/{{ selectedRound.clan.total_attacks }}刀</text><text>{{ selectedRound.clan.stars }}⭐ {{ formatPercent(selectedRound.clan.destruction_percentage) }}</text><text class="score-divider">—</text><text>{{ selectedRound.opponent.stars }}⭐ {{ formatPercent(selectedRound.opponent.destruction_percentage) }}</text><text>{{ selectedRound.opponent.attacks }}/{{ selectedRound.opponent.total_attacks }}刀</text>
            </view>
            <view class="time-info"><text>开战：{{ formatFullTime(selectedRound.start_time) }}</text><text>结束：{{ formatFullTime(selectedRound.end_time) }}</text></view>
          </view>

          <text class="table-note">左右滑动查看完整战斗日表格</text>
          <scroll-view scroll-x class="wide-table-scroll">
            <view class="battle-table">
              <view class="tr tr-head">
                <view class="td battle-seq">序号</view>
                <view class="td battle-name">己方名称</view><view class="td battle-th">本</view><view class="td battle-attack">进攻</view><view class="td battle-pos">对位</view><view class="td battle-attack">防守</view><view class="td battle-pos">对位</view>
                <view class="td battle-name enemy-cell">对手名称</view><view class="td battle-th enemy-cell">本</view><view class="td battle-attack enemy-cell">进攻</view><view class="td battle-pos enemy-cell">对位</view><view class="td battle-attack enemy-cell">防守</view><view class="td battle-pos enemy-cell">对位</view>
              </view>
              <view v-for="row in selectedRound.rows" :key="row.position" class="tr" :class="{ even: row.position % 2 === 0 }">
                <view class="td battle-seq seq-cell">{{ row.position }}</view>
                <view class="td battle-name name-cell">{{ memberName(row.clan_member) }}</view><view class="td battle-th th-cell">{{ memberTh(row.clan_member) }}</view><view class="td battle-attack" :class="attackClass(memberAttack(row.clan_member), false)">{{ formatAttack(memberAttack(row.clan_member), '未出刀') }}</view><view class="td battle-pos">{{ attackTarget(memberAttack(row.clan_member)) }}</view><view class="td battle-attack" :class="attackClass(memberDefense(row.clan_member), true)">{{ formatAttack(memberDefense(row.clan_member), '未被打') }}</view><view class="td battle-pos">{{ defensePosition(row.clan_member) }}</view>
                <view class="td battle-name name-cell enemy-cell">{{ memberName(row.opponent_member) }}</view><view class="td battle-th th-cell enemy-cell">{{ memberTh(row.opponent_member) }}</view><view class="td battle-attack enemy-cell" :class="attackClass(memberAttack(row.opponent_member), false)">{{ formatAttack(memberAttack(row.opponent_member), '未出刀') }}</view><view class="td battle-pos enemy-cell">{{ attackTarget(memberAttack(row.opponent_member)) }}</view><view class="td battle-attack enemy-cell" :class="attackClass(memberDefense(row.opponent_member), true)">{{ formatAttack(memberDefense(row.opponent_member), '未被打') }}</view><view class="td battle-pos enemy-cell">{{ defensePosition(row.opponent_member) }}</view>
              </view>
            </view>
          </scroll-view>
        </view>
      </view>

      <view v-else class="overview-pane">
        <view class="overview-section">
          <view class="section-title" @tap="toggleSection('townHalls')"><text>大本概览</text><text>{{ openSections.townHalls ? '收起' : '展开' }}</text></view>
          <scroll-view v-if="openSections.townHalls" scroll-x class="wide-table-scroll">
            <view :style="{ width: townHallTableWidth + 'rpx' }" class="overview-table">
              <view class="tr tr-head" :style="{ width: townHallTableWidth + 'rpx' }"><view class="td ov-level">等级</view><view class="td ov-clan">部落名称</view><view class="td ov-tag">标签</view><view class="td ov-total">总</view><view v-for="level in townHallLevels" :key="level" class="td ov-th">{{ level }}</view></view>
              <view v-for="row in townHallRows" :key="row.clan_tag" class="tr" :style="{ width: townHallTableWidth + 'rpx' }"><view class="td ov-level">{{ row.clan_level }}</view><view class="td ov-clan name-cell">{{ row.clan_name }}</view><view class="td ov-tag">{{ row.clan_tag }}</view><view class="td ov-total">{{ row.total }}</view><view v-for="level in townHallLevels" :key="level" class="td ov-th">{{ row.counts[level] || '' }}</view></view>
            </view>
          </scroll-view>
        </view>

        <view class="overview-section">
          <view class="section-title" @tap="toggleSection('standings')"><text>联赛对局</text><text>{{ openSections.standings ? '收起' : '展开' }}</text></view>
          <scroll-view v-if="openSections.standings" scroll-x class="wide-table-scroll">
            <view :style="{ width: standingsTableWidth + 'rpx' }" class="overview-table">
              <view class="tr tr-head" :style="{ width: standingsTableWidth + 'rpx' }"><view class="td rank-col">排名</view><view class="td player-col">部落名称</view><view class="td total-col">总计</view><view v-for="round in overviewRoundNumbers" :key="round" class="td round-col">第{{ round }}场</view></view>
              <view v-for="row in standingsRows" :key="row.clan_tag" class="tr" :style="{ width: standingsTableWidth + 'rpx' }"><view class="td rank-col">{{ row.rank }}</view><view class="td player-col name-cell">{{ row.clan_name }}</view><view class="td total-col">{{ row.league_stars }}⭐</view><view v-for="item in row.rounds" :key="item.round" class="td round-col" :class="standingResultClass(item)">{{ standingRoundText(item) }}</view></view>
            </view>
          </scroll-view>
        </view>

        <view class="overview-section">
          <view class="section-title" @tap="toggleSection('offense')"><text>成员进攻统计</text><text>{{ openSections.offense ? '收起' : '展开' }}</text></view>
          <scroll-view v-if="openSections.offense" scroll-x class="wide-table-scroll">
            <view :style="{ width: offenseTableWidth + 'rpx' }" class="overview-table">
              <view class="tr tr-head" :style="{ width: offenseTableWidth + 'rpx' }"><view class="td rank-col">排名</view><view class="td player-col">名称</view><view class="td th-col">大本</view><view class="td member-total-col">总计</view><view class="td count-col">出刀</view><view class="td diff-col">对位差</view><view v-for="round in overviewRoundNumbers" :key="round" class="td member-round-col">第{{ round }}场</view></view>
              <view v-for="row in offenseRows" :key="row.player_tag" class="tr" :style="{ width: offenseTableWidth + 'rpx' }"><view class="td rank-col">{{ row.rank }}</view><view class="td player-col name-cell">{{ row.name }}</view><view class="td th-col">{{ row.town_hall_level }}</view><view class="td member-total-col">{{ row.total_stars }}★ {{ formatNumber(row.total_destruction) }}%</view><view class="td count-col">{{ row.attacks }}/{{ row.appearances }}</view><view class="td diff-col">{{ signedNumber(row.matchup_difference) }}</view><view v-for="item in row.rounds" :key="item.round" class="td member-round-col" :class="attackCellClass(item)">{{ offenseRoundText(item) }}</view></view>
            </view>
          </scroll-view>
        </view>

        <view class="overview-section">
          <view class="section-title" @tap="toggleSection('defense')"><text>成员防守统计</text><text>{{ openSections.defense ? '收起' : '展开' }}</text></view>
          <scroll-view v-if="openSections.defense" scroll-x class="wide-table-scroll">
            <view :style="{ width: defenseTableWidth + 'rpx' }" class="overview-table">
              <view class="tr tr-head" :style="{ width: defenseTableWidth + 'rpx' }"><view class="td rank-col">排名</view><view class="td pos-col">序号</view><view class="td player-col">名称</view><view class="td th-col">大本</view><view class="td member-total-col">防守成果</view><view class="td defense-count-col">防守成功</view><view v-for="round in overviewRoundNumbers" :key="round" class="td member-round-col">第{{ round }}场</view></view>
              <view v-for="row in defenseRows" :key="row.player_tag" class="tr" :style="{ width: defenseTableWidth + 'rpx' }"><view class="td rank-col">{{ row.rank }}</view><view class="td pos-col">{{ row.last_position }}</view><view class="td player-col name-cell">{{ row.name }}</view><view class="td th-col">{{ row.town_hall_level }}</view><view class="td member-total-col">{{ row.saved_stars }}★ {{ formatNumber(row.saved_destruction) }}%</view><view class="td defense-count-col">{{ row.successful_defenses }}/{{ row.appearances }}</view><view v-for="item in row.rounds" :key="item.round" class="td member-round-col" :class="defenseCellClass(item)">{{ defenseRoundText(item) }}</view></view>
            </view>
          </scroll-view>
        </view>
      </view>
      <view class="bottom-space"></view>
    </view>
  </view>
</template>

<script>
import TopBar from '@/components/TopBar.vue'
import { getCwlLiveDetail } from '@/utils/api.js'

const CACHE_REFRESH_INTERVAL_MS = 60 * 1000
const BUSINESS_TIMEZONE_OFFSET_MS = 8 * 60 * 60 * 1000

function currentBusinessPeriod() {
  const date = new Date(Date.now() + BUSINESS_TIMEZONE_OFFSET_MS)
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, '0')}`
}

export default {
  components: { TopBar },
  data() {
    return {
      clanTag: '', period: '', detail: null, loading: true, loadError: '',
      activeView: 'war-day', selectedRoundNumber: null, requestedRound: null,
      refreshTimer: null,
      openSections: { townHalls: false, standings: true, offense: true, defense: false }
    }
  },
  computed: {
    listFallback() { return `/pages/war/war?tab=league&period=${encodeURIComponent(this.period || '')}` },
    isCurrentPeriod() { return !this.period || this.period === currentBusinessPeriod() },
    rounds() { return this.detail && this.detail.rounds ? this.detail.rounds : [] },
    selectedRound() { return this.rounds.find(item => item.round === this.selectedRoundNumber) || this.rounds[0] || null },
    availableTeams() { return this.detail && this.detail.available_teams ? this.detail.available_teams : [] },
    townHallLevels() { return this.detail ? this.detail.overview.town_halls.levels || [] : [] },
    townHallRows() { return this.detail ? this.detail.overview.town_halls.rows || [] : [] },
    standingsRows() { return this.detail ? this.detail.overview.standings.rows || [] : [] },
    offenseRows() { return this.detail ? this.detail.overview.offense.rows || [] : [] },
    defenseRows() { return this.detail ? this.detail.overview.defense.rows || [] : [] },
    overviewRoundCount() { return this.detail ? this.detail.overview.standings.round_count || 0 : 0 },
    overviewRoundNumbers() { return Array.from({ length: this.overviewRoundCount }, (value, index) => index + 1) },
    townHallTableWidth() { return 540 + this.townHallLevels.length * 72 },
    standingsTableWidth() { return 410 + this.overviewRoundCount * 170 },
    offenseTableWidth() { return 650 + this.overviewRoundCount * 130 },
    defenseTableWidth() { return 700 + this.overviewRoundCount * 130 }
  },
  onLoad(options) {
    try { this.clanTag = decodeURIComponent((options && options.clan_tag) || '') } catch (e) { this.clanTag = (options && options.clan_tag) || '' }
    this.period = (options && options.period) || ''
    this.activeView = options && options.view === 'overview' ? 'overview' : 'war-day'
    this.requestedRound = Number((options && options.round) || 0) || null
    uni.setStorageSync('war_active_top_tab', 'league')
    this.fetchDetail()
  },
  onShow() {
    uni.setStorageSync('war_active_top_tab', 'league')
    this.stopTimer()
    if (this.isCurrentPeriod) {
      if (this.detail) this.fetchDetail()
      this.refreshTimer = setInterval(() => { this.fetchDetail() }, CACHE_REFRESH_INTERVAL_MS)
    }
  },
  onHide() { this.stopTimer() },
  onUnload() { this.stopTimer() },
  async onPullDownRefresh() { await this.fetchDetail(); uni.stopPullDownRefresh() },
  onShareAppMessage() {
    const round = this.selectedRoundNumber ? `&round=${this.selectedRoundNumber}` : ''
    return { title: `苍穹联赛助手｜${this.detail ? (this.detail.team.team_name || this.detail.team.team_alias) : '联赛'}`, path: `/pages/war/cwl-detail?clan_tag=${encodeURIComponent(this.clanTag)}&period=${encodeURIComponent(this.period)}&view=${this.activeView}${round}` }
  },
  onShareTimeline() {
    return { title: `苍穹联赛助手｜${this.detail ? (this.detail.team.team_name || this.detail.team.team_alias) : '联赛'}`, query: `clan_tag=${encodeURIComponent(this.clanTag)}&period=${encodeURIComponent(this.period)}&view=${this.activeView}&round=${this.selectedRoundNumber || ''}` }
  },
  methods: {
    async fetchDetail() {
      if (!this.clanTag) { this.loadError = '缺少部落标签'; this.loading = false; return }
      if (!this.detail) this.loading = true
      this.loadError = ''
      try {
        const res = await getCwlLiveDetail(this.clanTag, this.period, this.selectedRoundNumber || this.requestedRound)
        this.detail = Object.assign({}, res)
        this.period = res.period || this.period
        const firstRound = (res.rounds || [])[0]
        if (!this.selectedRoundNumber) this.selectedRoundNumber = this.requestedRound || res.requested_round || res.current_round || (firstRound && firstRound.round)
        this.$nextTick(() => { this.$forceUpdate() })
      } catch (e) { this.loadError = e.message || '联赛详情加载失败' }
      finally { this.loading = false }
    },
    stopTimer() { if (this.refreshTimer) clearInterval(this.refreshTimer); this.refreshTimer = null },
    switchTeam(event) {
      const selected = this.availableTeams[Number(event.detail.value)]
      if (!selected || selected.clan_tag === this.clanTag) return
      this.clanTag = selected.clan_tag
      this.selectedRoundNumber = null
      this.detail = null
      this.fetchDetail()
    },
    toggleSection(key) { this.$set(this.openSections, key, !this.openSections[key]) },
    roundStatusLabel(status) { return ({ in_war: '战斗日', preparation: '准备日', war_ended: '已结束', not_started: '未开始', unavailable: '待同步', bye: '轮空' })[status] || status },
    roundResultLabel(item) {
      if (!item) return '-'
      if (item.status === 'in_war') return ({ leading: '领先', losing: '落后', tied: '平' })[item.result] || '进行中'
      return ({ victory: '胜利', defeat: '失败', tied: '平局', pending: '尚未开战' })[item.result] || '-'
    },
    summaryResultText(summary) {
      if (!summary) return '-'
      return `${summary.wins || 0}胜 ${summary.losses || 0}负${summary.ties ? ' ' + summary.ties + '平' : ''}`
    },
    resultClass(result) { if (['leading', 'victory'].indexOf(result) >= 0) return 'result-win'; if (['losing', 'defeat'].indexOf(result) >= 0) return 'result-loss'; return 'result-tied' },
    memberName(member) { return member ? member.name : '-' },
    memberTh(member) { return member && member.town_hall_level ? member.town_hall_level : '-' },
    memberAttack(member) { return member ? member.attack : null },
    memberDefense(member) { return member ? member.defense : null },
    attackTarget(attack) { return attack && attack.target_position ? attack.target_position : '-' },
    defensePosition(member) { const attack = this.memberDefense(member); return attack && attack.attacker_position ? attack.attacker_position : '-' },
    formatAttack(attack, emptyText) { if (!attack) return emptyText || '-'; return `${'★'.repeat(Number(attack.stars || 0))}${'☆'.repeat(Math.max(0, 3 - Number(attack.stars || 0)))} ${Number(attack.destruction_percentage || 0).toFixed(0)}%` },
    attackClass(attack, defense) { if (!attack) return 'attack-empty'; const stars = Number(attack.stars || 0); if (defense) return stars === 3 ? 'attack-bad' : stars === 2 ? 'attack-mid' : 'attack-good'; return stars === 3 ? 'attack-good' : stars === 2 ? 'attack-mid' : 'attack-bad' },
    standingRoundText(item) {
      if (!item || item.status === 'not_started') return '-'
      if (item.status === 'preparation') return '准备中'
      return `${item.attacks || 0}× ${item.stars || 0}★ ${this.formatNumber(item.destruction_percentage)}%`
    },
    standingResultClass(item) {
      if (!item || ['not_started', 'preparation'].indexOf(item.status) >= 0) return 'result-pending'
      if (item.status === 'in_war') {
        if (item.result === 'leading') return 'result-live-win'
        if (item.result === 'losing') return 'result-live-loss'
        return 'result-live-tied'
      }
      return this.resultClass(item.result)
    },
    offenseRoundText(item) { if (item.status === 'not_participated') return '未参战'; if (item.status === 'not_attacked') return '未出刀'; return `${item.stars}★ ${this.formatNumber(item.destruction_percentage)}%` },
    defenseRoundText(item) { if (item.status === 'not_participated') return '未参战'; if (item.status === 'unattacked') return '未被打'; return `${item.stars}★ ${this.formatNumber(item.destruction_percentage)}%` },
    attackCellClass(item) { if (item.status !== 'attacked') return 'attack-empty'; return item.stars === 3 ? 'attack-good' : item.stars === 2 ? 'attack-mid' : 'attack-bad' },
    defenseCellClass(item) { if (item.status !== 'defended') return 'attack-empty'; return item.stars === 3 ? 'attack-bad' : item.stars === 2 ? 'attack-mid' : 'attack-good' },
    signedNumber(value) { const number = Number(value || 0); return number > 0 ? `+${number}` : String(number) },
    formatNumber(value) { return Number(value || 0).toFixed(0) },
    formatPercent(value) { return `${Number(value || 0).toFixed(2)}%` },
    parseTime(value) { if (!value) return null; const text = String(value); const match = text.match(/^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})/); if (match) return new Date(`${match[1]}-${match[2]}-${match[3]}T${match[4]}:${match[5]}:${match[6]}Z`); const date = new Date(text.replace('+00:00', 'Z')); return isNaN(date.getTime()) ? null : date },
    formatFullTime(value) { const date = this.parseTime(value); if (!date) return '-'; const pad = number => String(number).padStart(2, '0'); return `${date.getFullYear()}/${pad(date.getMonth() + 1)}/${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}` },
    formatTime(value) { const date = this.parseTime(value); if (!date) return value || '-'; const pad = number => String(number).padStart(2, '0'); return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}` }
  }
}
</script>

<style>
.detail-page { min-height: 100vh; background: #0f0f23; color: #d8dce8; }.detail-content { padding-bottom: 40rpx; }.state-box { min-height: 70vh; padding: 40rpx; display: flex; flex-direction: column; align-items: center; justify-content: center; box-sizing: border-box; }.state-text { color: #8890a0; font-size: 28rpx; }.error-text { margin-bottom: 18rpx; color: #e17055; font-size: 26rpx; text-align: center; }.retry-btn { color: #5fa8ff; font-size: 25rpx; }
.team-card { margin: 20rpx 24rpx 0; padding: 20rpx; border: 1rpx solid #2a2a4a; border-radius: 14rpx; background: #18182d; }.team-title-row { display: flex; align-items: center; }.team-picker, .team-name { max-width: 300rpx; overflow: hidden; color: #fff; font-size: 29rpx; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }.team-tag { margin-left: 10rpx; color: #66708a; font-size: 20rpx; }.share-btn { margin: 0 0 0 auto; padding: 7rpx 16rpx; border: 0; border-radius: 6rpx; color: #aab4c8; background: #252540; font-size: 22rpx; line-height: 1.5; }.share-btn::after { border: 0; }.team-meta { margin-top: 16rpx; display: flex; flex-wrap: wrap; color: #9aa0b0; font-size: 22rpx; }.team-meta text { margin: 0 18rpx 8rpx 0; }.cache-warning { display: block; margin-top: 8rpx; color: #fdcb6e; font-size: 21rpx; }.updated-at { display: block; margin-top: 8rpx; color: #596178; font-size: 20rpx; }
.inner-tab-bar { height: 76rpx; margin-top: 18rpx; display: flex; border-top: 1rpx solid #252540; border-bottom: 1rpx solid #252540; background: #141428; }.inner-tab { flex: 1; display: flex; align-items: center; justify-content: center; color: #7d8498; font-size: 27rpx; }.inner-tab.active { color: #5fa8ff; border-bottom: 4rpx solid #4a90d9; font-weight: 600; }
.round-scroll { width: 100%; background: #15152a; }.round-tabs { width: 950rpx; padding: 14rpx 20rpx; display: flex; flex-direction: row; }.round-tab { width: 118rpx; min-height: 64rpx; margin-right: 12rpx; padding: 8rpx; display: flex; flex-direction: column; align-items: center; justify-content: center; box-sizing: border-box; border: 1rpx solid #30304d; border-radius: 8rpx; color: #aab4c8; font-size: 23rpx; background: #202038; }.round-tab.active { color: #fff; border-color: #4a90d9; background: #263b61; }.round-status { margin-top: 4rpx; color: #66708a; font-size: 18rpx; }.round-tab.active .round-status { color: #9fc9ff; }.round-in_war .round-status { color: #ff7675; }.round-war_ended .round-status { color: #74b9ff; }
.empty-box { padding: 140rpx 30rpx; color: #66708a; font-size: 27rpx; text-align: center; }.match-card { margin: 20rpx 24rpx; padding: 20rpx; border: 1rpx solid #2a2a4a; border-radius: 14rpx; background: #18182d; }.match-heading { display: flex; align-items: center; color: #fff; font-size: 27rpx; font-weight: 600; }.result-label { margin-left: auto; font-size: 22rpx; }.result-win { color: #00b894; }.result-loss { color: #e17055; }.result-tied { color: #fdcb6e; }.match-row { margin-top: 20rpx; display: flex; align-items: center; }.match-side { flex: 1; display: flex; flex-direction: column; }.enemy-side { align-items: flex-end; }.match-name { max-width: 260rpx; overflow: hidden; color: #f0f0f5; font-size: 26rpx; text-overflow: ellipsis; white-space: nowrap; }.match-tag { margin-top: 4rpx; color: #66708a; font-size: 19rpx; }.versus { margin: 0 14rpx; color: #4a90d9; font-size: 22rpx; }.score-row { margin-top: 18rpx; display: flex; align-items: center; justify-content: space-between; color: #c9cfda; font-size: 21rpx; }.score-divider { color: #4a90d9; }.time-info { margin-top: 16rpx; padding-top: 12rpx; display: flex; justify-content: space-between; border-top: 1rpx solid #252540; color: #66708a; font-size: 20rpx; }
.table-note { display: block; margin: 16rpx 24rpx 10rpx; color: #66708a; font-size: 21rpx; }.wide-table-scroll { width: 100%; }.battle-table { width: 1276rpx; border-top: 1rpx solid #343452; border-bottom: 1rpx solid #343452; background: #15152a; }.tr { min-height: 68rpx; display: flex; flex-direction: row; align-items: stretch; box-sizing: border-box; border-bottom: 1rpx solid #2a2a44; }.tr-head { min-height: 76rpx; color: #dfe5f0; background: #242440; font-weight: 600; }.even { background: #19192f; }.td { flex-shrink: 0; min-height: 68rpx; padding: 5rpx; display: flex; align-items: center; justify-content: center; box-sizing: border-box; border-right: 1rpx solid #30304a; color: #c9cfda; font-size: 20rpx; text-align: center; white-space: nowrap; overflow: hidden; }.tr-head .td { min-height: 76rpx; }.battle-seq { width: 56rpx; }.battle-name { width: 170rpx; }.battle-th { width: 54rpx; }.battle-attack { width: 120rpx; }.battle-pos { width: 58rpx; }.enemy-cell { background: rgba(74,45,45,.13); }.seq-cell { color: #74b9ff; font-weight: 600; }.name-cell { padding: 0 10rpx; justify-content: flex-start; text-overflow: ellipsis; }.th-cell { color: #74b9ff; font-weight: 600; }.attack-good { color: #00b894; }.attack-mid { color: #fdcb6e; }.attack-bad { color: #e17055; }.attack-empty { color: #596178; }
.overview-pane { padding-top: 16rpx; }.overview-section { margin: 0 20rpx 16rpx; overflow: hidden; border: 1rpx solid #2a2a4a; border-radius: 10rpx; background: #15152a; }.section-title { min-height: 72rpx; padding: 0 18rpx; display: flex; align-items: center; justify-content: space-between; color: #d8dce8; font-size: 26rpx; background: #1b1b32; }.section-title text:last-child { color: #5fa8ff; font-size: 21rpx; }.overview-table { background: #15152a; }.ov-level { width: 70rpx; }.ov-clan { width: 210rpx; }.ov-tag { width: 170rpx; }.ov-total { width: 90rpx; }.ov-th { width: 72rpx; }.rank-col { width: 80rpx; }.player-col { width: 220rpx; }.total-col { width: 110rpx; }.round-col { width: 170rpx; }.th-col { width: 70rpx; }.member-total-col { width: 140rpx; }.count-col { width: 70rpx; }.diff-col { width: 70rpx; }.member-round-col { width: 130rpx; }.pos-col { width: 60rpx; }.defense-count-col { width: 110rpx; }.bottom-space { height: 80rpx; }
.overview-table .round-col.result-win { color: #00b894; font-weight: 600; }.overview-table .round-col.result-loss { color: #ff7675; font-weight: 600; }.overview-table .round-col.result-tied { color: #fdcb6e; font-weight: 600; }.overview-table .round-col.result-pending { color: #66708a; font-weight: 400; }
.overview-table .round-col.result-live-win { color: rgba(0,184,148,.62); font-weight: 500; }.overview-table .round-col.result-live-loss { color: rgba(255,118,117,.62); font-weight: 500; }.overview-table .round-col.result-live-tied { color: rgba(253,203,110,.62); font-weight: 500; }
</style>
