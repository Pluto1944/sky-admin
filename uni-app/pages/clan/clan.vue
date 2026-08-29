<template>
  <view class="page-container">
    <TopBar title="部落" :buttons="topButtons" @onRecord="onRecord" @onFarm="onFarm" @onFilter="onFilter" @onSearch="onSearch" />
    <view v-if="loading" class="state-box"><text class="state-text">加载中...</text></view>
    <view v-else-if="!members.length" class="state-box"><text class="state-text">暂无成员数据</text></view>
    <scroll-view v-else scroll-x scroll-y class="table-scroll-x">
    <view class="table-wrap">
      <view v-if="updatedAt" class="update-time"><text class="update-text">数据更新于 {{ updatedAt }}</text></view>
      <view class="tr tr-head">
        <view class="td w-name" @tap="onSort('account_name')">昵称{{ sortMark('account_name') }}</view><view class="td w-owner">归属人</view><view class="td w-clan" @tap="onSort('clan_tag')">部落{{ sortMark('clan_tag') }}</view><view class="td w-role">职位</view><view class="td w-th" @tap="onSort('town_hall_level')">本{{ sortMark('town_hall_level') }}</view><view class="td w-exp" @tap="onSort('exp_level')">经验{{ sortMark('exp_level') }}</view><view class="td w-trophy" @tap="onSort('trophies')">奖杯{{ sortMark('trophies') }}</view><view class="td w-league">联赛</view><view class="td w-score" @tap="onSort('history_score')">历史分{{ sortMark('history_score') }}</view><view class="td w-status">报名状态</view><view class="td w-member">成员状态</view><view class="td w-reg">最近报名</view><view class="td w-sync">最近同步</view>
      </view>
      <view class="tbody">
        <view v-for="(item, idx) in sortedMembers" :key="idx" class="tr" :class="{ even: idx % 2 === 1 }">
          <view class="td w-name name-text">{{ item.account_name || '-' }}</view><view class="td w-owner">{{ item.player_name || '-' }}</view><view class="td w-clan">{{ item.clan_tag || '-' }}</view><view class="td w-role">{{ formatRole(item.clan_role) }}</view><view class="td w-th">{{ item.town_hall_level || '-' }}</view><view class="td w-exp">{{ item.exp_level || '-' }}</view><view class="td w-trophy">{{ item.trophies || 0 }}</view><view class="td w-league">{{ item.league_name || '-' }}</view><view class="td w-score">{{ item.history_score || 0 }}</view><view class="td w-status">{{ formatStatus(item.status) }}</view><view class="td w-member">{{ formatStatus(item.membership_status) }}</view><view class="td w-reg">{{ item.last_reg_period || '-' }}</view><view class="td w-sync">{{ formatTime(item.last_synced_at) }}</view>
        </view>
      </view>
    </view>
    </scroll-view>
  </view>
</template>
<script>
import TopBar from '@/components/TopBar.vue'
import { getMembers } from '@/utils/api.js'
export default {
  components: { TopBar },
  data() { return { topButtons: [{ key: 'record', icon: '⚔️', text: '战绩', action: 'onRecord' }, { key: 'farm', icon: '🔄', text: '互刷', action: 'onFarm' }, { key: 'filter', icon: '⏬', text: '筛选', action: 'onFilter' }, { key: 'search', icon: '🔍', text: '搜索', action: 'onSearch' }], members: [], loading: true, updatedAt: '', sortKey: 'town_hall_level', sortOrder: 'desc' } },
  computed: { sortedMembers() { const a = [...this.members]; const k = this.sortKey; a.sort((x, y) => { const xv = x[k]; const yv = y[k]; if (xv == null) return 1; if (yv == null) return -1; const n = typeof xv === 'number' && typeof yv === 'number' ? xv - yv : String(xv).localeCompare(String(yv), 'zh-CN'); return this.sortOrder === 'desc' ? -n : n }); return a } },
  onLoad() { this.fetchMembers() },
  methods: {
    async fetchMembers() { try { const res = await getMembers(); this.members = res.members || []; const times = this.members.map(x => x.last_synced_at).filter(Boolean).sort(); this.updatedAt = times.length ? this.formatTime(times[times.length - 1]) : '' } catch (e) { uni.showToast({ title: '加载成员失败', icon: 'none' }) } finally { this.loading = false } },
    formatRole(v) { return ({ leader: '首领', coLeader: '副首领', admin: '长老', member: '成员' }[v] || v || '-') },
    formatStatus(v) { return v === 'member' ? '在部落' : v === 'left' ? '已离开' : '-' },
    formatTime(v) {
      if (!v) return '-'
      const d = new Date(String(v).replace('+00:00', 'Z'))
      if (isNaN(d.getTime())) return String(v)
      const month = String(d.getMonth() + 1).padStart(2, '0')
      const day = String(d.getDate()).padStart(2, '0')
      const hour = String(d.getHours()).padStart(2, '0')
      const minute = String(d.getMinutes()).padStart(2, '0')
      return `${month}-${day} ${hour}:${minute}`
    },
    onSort(k) { if (this.sortKey === k) this.sortOrder = this.sortOrder === 'desc' ? 'asc' : 'desc'; else { this.sortKey = k; this.sortOrder = 'desc' } },
    sortMark(k) { return this.sortKey === k ? (this.sortOrder === 'desc' ? '↓' : '↑') : '' },
    onRecord() { uni.navigateTo({ url: '/pages/clan/stats' }) }, onFarm() { uni.navigateTo({ url: '/pages/clan/farm' }) }, onFilter() { uni.showToast({ title: '筛选功能开发中', icon: 'none' }) }, onSearch() { uni.showToast({ title: '搜索功能开发中', icon: 'none' }) }
  }
}
</script>
<style>
.page-container { height: 100vh; display: flex; flex-direction: column; background: #0f0f23; }
.state-box { flex: 1; display: flex; align-items: center; justify-content: center; }
.state-text { color: #888; font-size: 28rpx; }
.update-time { text-align: center; padding: 12rpx 0 8rpx; }.update-text { color: #667; font-size: 22rpx; }
.table-wrap { flex: 1; min-height: 0; display: flex; flex-direction: column; padding-bottom: 100rpx; overflow: hidden; }
.table-scroll-x { flex: 1; min-height: 0; width: 100%; }
.table-wrap { width: 1570rpx; }
.tbody { flex: 1; height: 0; }
.tr { display: flex; flex-direction: row; width: 1570rpx; height: 72rpx; align-items: center; border-bottom: 2rpx solid #33334d; }
.tr-head { height: 88rpx; flex-shrink: 0; background: #262644; border-top: 2rpx solid #4a4a70; }
.even { background: #19192f; }
.td { display: flex; flex-direction: row; align-items: center; justify-content: center; flex-shrink: 0; box-sizing: border-box; height: 100%; color: #d0d0dc; font-size: 24rpx; text-align: center; border-right: 2rpx solid #33334d; white-space: nowrap; overflow: hidden; }
.tr-head .td { color: #fff; font-weight: 600; background: #262644; border-color: #5a5a80; }
.w-name { width: 190rpx; padding: 0 12rpx; justify-content: flex-start; text-align: left; border-left: 2rpx solid #33334d; }
.w-owner { width: 140rpx; }.w-clan { width: 150rpx; }.w-role { width: 120rpx; }.w-th { width: 60rpx; }.w-exp { width: 70rpx; }.w-trophy { width: 100rpx; }.w-league { width: 150rpx; }.w-score { width: 110rpx; }.w-status { width: 120rpx; }.w-member { width: 120rpx; }.w-reg { width: 110rpx; }.w-sync { width: 130rpx; }
.name-text { color: #f0f0f5; }
</style>
