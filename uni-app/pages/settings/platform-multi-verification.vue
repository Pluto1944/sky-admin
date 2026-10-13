<template>
  <view class="page">
    <TopBar title="联盟多认证管理" :show-back="true" back-fallback="/pages/settings/platform-management" />
    <scroll-view scroll-y class="content">
      <view class="summary-card">
        <view>
          <text class="summary-title">多联盟认证</text>
          <text class="summary-sub">{{ conflicts.length }} 个部落同时在多个联盟中保持认证</text>
        </view>
        <text class="summary-badge">允许保留</text>
      </view>

      <text class="notice">多认证不会自动覆盖。如需调整，请点选联盟进入管理列表，再进入联盟详情逐个撤销对应认证。</text>

      <view class="search-box">
        <input v-model="search" class="search-input" placeholder="搜索部落标签或联盟名称" placeholder-style="color:#59637a" />
        <text v-if="search" class="search-clear" @tap="search = ''">清除</text>
      </view>

      <view v-if="busy" class="state">正在加载...</view>
      <view v-else-if="!filteredConflicts.length" class="state">{{ search ? '没有匹配的多认证记录' : '当前没有多联盟认证' }}</view>
      <view v-for="item in filteredConflicts" :key="item.clan_tag" class="conflict-card">
        <view class="conflict-head">
          <text class="clan-tag">{{ item.clan_tag }}</text>
          <text class="count-badge">{{ item.alliance_count }} 个联盟</text>
        </view>
        <text class="card-label">已认证联盟</text>
        <view class="alliance-links">
          <view v-for="name in allianceNames(item)" :key="name" class="alliance-link" @tap="openAllianceSearch(name)">
            <text>{{ name }}</text><text class="arrow">›</text>
          </view>
        </view>
      </view>
      <view class="bottom-space"></view>
    </scroll-view>
  </view>
</template>

<script>
import TopBar from '@/components/TopBar.vue'
import { getPlatformAlliances } from '@/utils/api.js'

export default {
  components: { TopBar },
  data() {
    return {
      busy: false,
      search: '',
      conflicts: []
    }
  },
  computed: {
    filteredConflicts() {
      const keyword = this.search.trim().toLowerCase()
      if (!keyword) return this.conflicts
      return this.conflicts.filter(item => {
        return `${item.clan_tag || ''} ${item.alliance_names || ''}`.toLowerCase().indexOf(keyword) >= 0
      })
    }
  },
  async onShow() {
    await this.loadData()
  },
  methods: {
    async loadData() {
      if (this.busy) return
      this.busy = true
      try {
        const result = await getPlatformAlliances()
        this.conflicts = result.multi_alliance_verifications || result.verification_conflicts || []
      } catch (err) {
        uni.showModal({ title: '多认证数据不可用', content: err.message || '请稍后重试', showCancel: false })
      } finally {
        this.busy = false
      }
    },
    allianceNames(item) {
      return String(item.alliance_names || '').split(',').map(name => name.trim()).filter(Boolean)
    },
    openAllianceSearch(name) {
      uni.navigateTo({ url: `/pages/settings/platform-alliance-list?search=${encodeURIComponent(name)}` })
    }
  }
}
</script>

<style>
.page { height: 100vh; display: flex; flex-direction: column; color: #dce1ed; background: #0f0f23; }.content { flex: 1; min-height: 0; padding: 24rpx; box-sizing: border-box; }
.summary-card { display: flex; align-items: center; justify-content: space-between; padding: 24rpx; border: 1rpx solid #292945; border-radius: 14rpx; background: #18182d; }.summary-title, .summary-sub, .notice, .card-label { display: block; }.summary-title { color: #f1f3f8; font-size: 30rpx; font-weight: 700; }.summary-sub { margin-top: 7rpx; color: #727d93; font-size: 21rpx; }.summary-badge { flex-shrink: 0; margin-left: 18rpx; padding: 8rpx 12rpx; border-radius: 8rpx; color: #8cc7b5; background: #203432; font-size: 20rpx; }.notice { margin: 18rpx 6rpx 0; color: #68738a; font-size: 20rpx; line-height: 1.65; }
.search-box { height: 84rpx; margin-top: 20rpx; display: flex; align-items: center; padding: 0 20rpx; box-sizing: border-box; border: 1rpx solid #30304d; border-radius: 10rpx; background: #111126; }.search-input { flex: 1; min-width: 0; color: #fff; font-size: 23rpx; }.search-clear { flex-shrink: 0; margin-left: 14rpx; color: #74a9df; font-size: 21rpx; }
.conflict-card { margin-top: 16rpx; padding: 24rpx; border: 1rpx solid #292945; border-radius: 14rpx; background: #18182d; }.conflict-head { display: flex; align-items: center; justify-content: space-between; }.clan-tag { color: #e9edf5; font-size: 27rpx; font-weight: 650; }.count-badge { padding: 7rpx 11rpx; border-radius: 8rpx; color: #c9a766; background: #302c35; font-size: 19rpx; }.card-label { margin-top: 18rpx; color: #69748a; font-size: 19rpx; }.alliance-links { margin-top: 6rpx; }.alliance-link { min-height: 70rpx; display: flex; align-items: center; justify-content: space-between; border-bottom: 1rpx solid #25253e; color: #88b7e5; font-size: 22rpx; }.alliance-link:last-child { border-bottom: 0; }.arrow { color: #657087; font-size: 32rpx; }.state { padding: 150rpx 24rpx; color: #68738a; font-size: 24rpx; text-align: center; }.bottom-space { height: 80rpx; }
</style>
