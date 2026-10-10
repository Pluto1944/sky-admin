<template>
  <view class="clan-page">
    <TopBar title="部落" :buttons="topButtons" @onSection="switchSection" />
    <view v-if="!contextReady" class="context-loading"><text>正在加载联盟...</text></view>
    <ClanOverview v-else-if="activeSection === 'overview'" :key="'overview-' + allianceVersion" ref="overview" class="clan-section" @open-detail="openDetail" />
    <ClanMembers v-else-if="activeSection === 'members'" :key="'members-' + allianceVersion" class="clan-section" :initial-clan-tag="memberClanTag" />
    <ClanStats v-else-if="activeSection === 'stats'" :key="'stats-' + allianceVersion" class="clan-section" />
    <ClanFarm v-else-if="activeSection === 'farm'" :key="'farm-' + allianceVersion" class="clan-section" />
    <ClanDetail
      v-else-if="activeSection === 'clan-detail'"
      :key="'detail-' + allianceVersion"
      class="clan-section"
      :clan-tag="selectedClanTag"
      @loaded="onDetailLoaded"
      @back-overview="switchSection('overview')"
      @open-members="openMembers"
      @open-stats="switchSection('stats')"
      @open-farm="switchSection('farm')"
    />
  </view>
</template>

<script>
import TopBar from '@/components/TopBar.vue'
import ClanOverview from './components/ClanOverview.vue'
import ClanMembers from './components/ClanMembers.vue'
import ClanStats from './components/ClanStats.vue'
import ClanFarm from './components/ClanFarm.vue'
import ClanDetail from './components/ClanDetail.vue'
import { ALLIANCE_CHANGED_EVENT, activateSharedAlliance, allianceQuery } from '@/utils/alliance.js'

const VALID_SECTIONS = ['overview', 'members', 'stats', 'farm', 'clan-detail']

export default {
  components: { TopBar, ClanOverview, ClanMembers, ClanStats, ClanFarm, ClanDetail },
  data() {
    return { activeSection: 'overview', selectedClanTag: '', selectedClanName: '', memberClanTag: '', allianceVersion: 0, allianceChangeHandler: null, contextReady: false }
  },
  computed: {
    topButtons() {
      const active = this.activeSection === 'clan-detail' ? 'overview' : this.activeSection
      return [
        { key: 'overview', icon: '🏠', text: '概览', action: 'onSection', active: active === 'overview' },
        { key: 'members', icon: '👥', text: '成员', action: 'onSection', active: active === 'members' },
        { key: 'stats', icon: '⚔️', text: '战营', action: 'onSection', active: active === 'stats' },
        { key: 'farm', icon: '🔄', text: '互刷', action: 'onSection', active: active === 'farm' }
      ]
    }
  },
  async onLoad(options) {
    try {
      await activateSharedAlliance(options)
    } catch (e) {
      uni.showToast({ title: e.message || '联盟切换失败', icon: 'none' })
    }
    this.allianceChangeHandler = () => {
      this.allianceVersion += 1
      this.selectedClanTag = ''
      this.selectedClanName = ''
      this.memberClanTag = ''
      this.activeSection = 'overview'
    }
    uni.$on(ALLIANCE_CHANGED_EVENT, this.allianceChangeHandler)
    const requestedSection = options && options.section
    const section = VALID_SECTIONS.includes(requestedSection) ? requestedSection : 'overview'
    if (section === 'clan-detail') {
      const clanTag = options.clan_tag ? decodeURIComponent(options.clan_tag) : ''
      if (clanTag) this.selectedClanTag = clanTag
      else this.activeSection = 'overview'
    }
    if (section !== 'clan-detail' || this.selectedClanTag) this.activeSection = section
    this.contextReady = true
  },
  onShow() {
    if (!this.contextReady) return
    this.$nextTick(() => {
      if (this.activeSection === 'overview' && this.$refs.overview) this.$refs.overview.refresh()
    })
  },
  onUnload() {
    if (this.allianceChangeHandler) uni.$off(ALLIANCE_CHANGED_EVENT, this.allianceChangeHandler)
  },
  onShareAppMessage() { return { title: this.shareTitle(), path: this.sharePath() } },
  onShareTimeline() { return { title: this.shareTitle(), query: this.shareQuery() } },
  methods: {
    switchSection(section) {
      if (!VALID_SECTIONS.includes(section) || section === 'clan-detail') return
      if (section !== 'members') this.memberClanTag = ''
      this.activeSection = section
    },
    openDetail(clanTag) { this.selectedClanTag = clanTag; this.selectedClanName = ''; this.activeSection = 'clan-detail' },
    openMembers(clanTag) { this.memberClanTag = clanTag; this.activeSection = 'members' },
    onDetailLoaded(detail) { this.selectedClanName = detail.clan_name || '' },
    shareTitle() {
      const titles = { overview: '部落概览', members: '部落成员', stats: '战营', farm: '互刷部落' }
      if (this.activeSection === 'clan-detail') return `苍穹联赛助手｜${this.selectedClanName || '部落详情'}`
      return `苍穹联赛助手｜${titles[this.activeSection] || '部落概览'}`
    },
    shareQuery() {
      let query = `section=${this.activeSection}`
      if (this.activeSection === 'clan-detail' && this.selectedClanTag) query += `&clan_tag=${encodeURIComponent(this.selectedClanTag)}`
      const alliance = allianceQuery()
      if (alliance) query += `&${alliance}`
      return query
    },
    sharePath() { return `/pages/clan/clan?${this.shareQuery()}` }
  }
}
</script>

<style>
.clan-page { height: 100vh; display: flex; flex-direction: column; background: #0f0f23; }
.clan-section { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.context-loading { flex: 1; display: flex; align-items: center; justify-content: center; color: #69728a; font-size: 25rpx; }
</style>
