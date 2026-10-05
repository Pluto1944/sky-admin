<template>
  <view class="clan-page">
    <TopBar title="部落" :buttons="topButtons" @onSection="switchSection" />
    <ClanOverview v-if="activeSection === 'overview'" ref="overview" class="clan-section" @open-detail="openDetail" />
    <ClanMembers v-else-if="activeSection === 'members'" class="clan-section" :initial-clan-tag="memberClanTag" />
    <ClanStats v-else-if="activeSection === 'stats'" class="clan-section" />
    <ClanFarm v-else-if="activeSection === 'farm'" class="clan-section" />
    <ClanDetail
      v-else-if="activeSection === 'clan-detail'"
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

const VALID_SECTIONS = ['overview', 'members', 'stats', 'farm', 'clan-detail']

export default {
  components: { TopBar, ClanOverview, ClanMembers, ClanStats, ClanFarm, ClanDetail },
  data() {
    return { activeSection: 'overview', selectedClanTag: '', selectedClanName: '', memberClanTag: '' }
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
  onLoad(options) {
    const section = options && options.section
    if (!VALID_SECTIONS.includes(section)) return
    if (section === 'clan-detail') {
      const clanTag = options.clan_tag ? decodeURIComponent(options.clan_tag) : ''
      if (!clanTag) return
      this.selectedClanTag = clanTag
    }
    this.activeSection = section
  },
  onShow() {
    this.$nextTick(() => {
      if (this.activeSection === 'overview' && this.$refs.overview) this.$refs.overview.refresh()
    })
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
      return query
    },
    sharePath() { return `/pages/clan/clan?${this.shareQuery()}` }
  }
}
</script>

<style>
.clan-page { height: 100vh; display: flex; flex-direction: column; background: #0f0f23; }
.clan-section { flex: 1; min-height: 0; display: flex; flex-direction: column; }
</style>
