<template>
  <view class="page-container">
    <TopBar title="战斗" :buttons="topButtons" @onTopTab="onTopTab" />

    <view v-if="activeTopTab === 'league'" class="content-area">
      <view class="inner-tab-bar">
        <view
          v-for="tab in leagueTabs"
          :key="tab.key"
          class="inner-tab-item"
          :class="{ active: activeLeagueTab === tab.key }"
          @tap="switchLeagueTab(tab.key)"
        >{{ tab.label }}</view>
      </view>
      <view class="placeholder-box">
        <text class="placeholder-icon">🏆</text>
        <text class="placeholder-text">{{ activeLeagueTab === 'war-day' ? '战斗日' : '联赛总览' }}</text>
      </view>
    </view>

    <view v-else class="placeholder-box">
      <text class="placeholder-icon">⚔️</text>
      <text class="placeholder-text">部落战</text>
    </view>
  </view>
</template>

<script>
import TopBar from '@/components/TopBar.vue'

export default {
  components: { TopBar },
  data() {
    return {
      topButtons: [
        { key: 'clan-war', icon: '⚔️', text: '部落战', action: 'onTopTab' },
        { key: 'league', icon: '🏆', text: '联赛', action: 'onTopTab' }
      ],
      activeTopTab: 'clan-war',
      leagueTabs: [
        { key: 'war-day', label: '战斗日' },
        { key: 'league-overview', label: '联赛总览' }
      ],
      activeLeagueTab: 'war-day'
    }
  },
  methods: {
    onTopTab(tab) {
      this.activeTopTab = tab
      if (tab === 'league') this.activeLeagueTab = 'war-day'
    },
    switchLeagueTab(tab) {
      this.activeLeagueTab = tab
    }
  }
}
</script>

<style>
.page-container { height: 100vh; display: flex; flex-direction: column; background: #0f0f23; }
.content-area { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.inner-tab-bar { display: flex; flex-shrink: 0; height: 72rpx; background: #141428; border-bottom: 1rpx solid #1a1a2e; }
.inner-tab-item { flex: 1; display: flex; align-items: center; justify-content: center; color: #7d8498; font-size: 27rpx; }
.inner-tab-item.active { color: #5fa8ff; font-weight: 600; border-bottom: 4rpx solid #4a90d9; }
.placeholder-box { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; }
.placeholder-icon { margin-bottom: 22rpx; font-size: 72rpx; }
.placeholder-text { color: #d8dce8; font-size: 34rpx; }
</style>
