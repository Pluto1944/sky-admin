<template>
  <view class="page">
    <TopBar title="管理部落" :show-back="true" :back-fallback="backFallback" />
    <scroll-view scroll-y class="content">
      <view v-if="loading" class="state">正在加载...</view>
      <template v-else-if="detail">
        <view class="summary-card">
          <view><text class="summary-title">{{ detail.alliance.name }}</text><text class="summary-sub">已添加 {{ activeClans.length }} 个部落 · 超级管理员不受套餐数量限制</text></view>
          <text class="summary-role">超级管理</text>
        </view>

        <view class="section-title">添加部落</view>
        <view class="card add-card">
          <input v-model="newClanTag" class="input" maxlength="15" placeholder="部落标签，例如 #2QQ" placeholder-style="color:#59637a" />
          <picker :range="categories" range-key="label" :value="newCategoryIndex" @change="newCategoryIndex = Number($event.detail.value) || 0">
            <view class="picker-field">部落类型：{{ categories[newCategoryIndex].label }}⌄</view>
          </picker>
          <button class="primary-btn full-btn" :loading="busy" :disabled="busy || !newClanTag.trim()" @tap="addClan">添加部落</button>
        </view>

        <view class="section-title">全部部落</view>
        <view class="search-box">
          <text class="search-icon">⌕</text>
          <input v-model="query" class="search-input" placeholder="搜索部落名称、标签、类型或认证状态" placeholder-style="color:#59637a" />
          <text v-if="query" class="search-clear" @tap="query = ''">清除</text>
        </view>
        <text class="result-count">显示 {{ filteredClans.length }} 条</text>

        <view v-if="filteredClans.length" class="clan-list">
          <view v-for="clan in filteredClans" :key="clan.clan_tag" class="clan-card">
            <view class="clan-head">
              <view class="order-column">
                <text :class="['order-btn', { disabled: activeIndex(clan) === 0 }]" @tap="moveClan(clan, -1)">↑</text>
                <text :class="['order-btn', { disabled: activeIndex(clan) === activeClans.length - 1 }]" @tap="moveClan(clan, 1)">↓</text>
              </view>
              <view class="grow">
                <text class="clan-name">{{ clan.clan_name || clan.clan_tag }}</text>
                <text class="clan-meta">{{ clan.clan_tag }} · {{ categoryLabel(clan.category) }} · {{ verificationLabel(clan.verification_status) }}</text>
              </view>
            </view>
            <view class="action-grid">
              <picker :range="categories" range-key="label" :value="categoryIndex(clan.category)" @change="changeCategory(clan, $event)">
                <view class="action-btn">类型：{{ categoryLabel(clan.category) }}⌄</view>
              </picker>
              <button class="action-btn" @tap="editClanName(clan)">修改别名</button>
              <button v-if="clan.verification_status !== 'verified'" class="action-btn verify" @tap="setVerification(clan, 'verified')">设为已认证</button>
              <button v-else class="action-btn warn" @tap="setVerification(clan, 'revoked')">撤销认证</button>
              <button class="action-btn warn" @tap="setVerification(clan, 'disputed')">标记争议</button>
              <button class="action-btn danger" @tap="confirmRemove(clan)">移除部落</button>
            </view>
          </view>
        </view>
        <view v-else class="state compact">{{ query ? '没有匹配的部落' : '该联盟尚未添加部落' }}</view>
      </template>
      <view class="bottom-space"></view>
    </scroll-view>
  </view>
</template>

<script>
import TopBar from '@/components/TopBar.vue'
import { addPlatformManagedClan, getPlatformAlliance, getPlatformManagedClans, removePlatformManagedClan, reorderPlatformManagedClans, savePlatformVerification, updatePlatformManagedClan } from '@/utils/api.js'

export default {
  components: { TopBar },
  data() {
    return {
      allianceId: null, loading: true, busy: false, detail: null, management: { clans: [] }, query: '', newClanTag: '', newCategoryIndex: 0,
      categories: [{ key: 'normal', label: '实战' }, { key: 'combat', label: '战营' }, { key: 'farm', label: '互刷' }, { key: 'flat', label: '偷矿' }]
    }
  },
  computed: {
    backFallback() { return `/pages/settings/platform-alliance-detail?id=${this.allianceId}` },
    activeClans() { return (this.management.clans || []).filter(item => item.status === 'active') },
    filteredClans() {
      const query = this.query.trim().toLowerCase()
      if (!query) return this.activeClans
      return this.activeClans.filter(clan => [clan.clan_name, clan.clan_tag, this.categoryLabel(clan.category), this.verificationLabel(clan.verification_status)]
        .some(value => String(value || '').toLowerCase().indexOf(query) >= 0))
    }
  },
  onLoad(options) { this.allianceId = Number(options && options.id) || null },
  async onShow() { if (this.allianceId) await this.loadData() },
  methods: {
    async loadData() {
      this.loading = true
      try {
        const [detail, management] = await Promise.all([getPlatformAlliance(this.allianceId), getPlatformManagedClans(this.allianceId)])
        this.detail = detail; this.management = management
      } catch (err) { uni.showModal({ title: '部落加载失败', content: err.message || '请稍后重试', showCancel: false }) }
      finally { this.loading = false }
    },
    async addClan() {
      if (!this.newClanTag.trim() || this.busy) return
      this.busy = true
      try {
        await addPlatformManagedClan(this.allianceId, { clan_tag: this.newClanTag.trim(), category: this.categories[this.newCategoryIndex].key })
        this.newClanTag = ''; this.newCategoryIndex = 0; await this.loadData(); uni.showToast({ title: '部落已添加', icon: 'success' })
      } catch (err) { uni.showModal({ title: '添加失败', content: err.message || '请稍后重试', showCancel: false }) }
      finally { this.busy = false }
    },
    activeIndex(clan) { return this.activeClans.findIndex(item => item.clan_tag === clan.clan_tag) },
    async moveClan(clan, offset) {
      const index = this.activeIndex(clan); const target = index + offset
      if (index < 0 || target < 0 || target >= this.activeClans.length || this.busy) return
      const ordered = this.activeClans.slice(); const moved = ordered.splice(index, 1)[0]; ordered.splice(target, 0, moved)
      this.busy = true
      try { await reorderPlatformManagedClans(this.allianceId, ordered.map(item => item.clan_tag)); await this.loadData() }
      catch (err) { uni.showToast({ title: err.message || '排序失败', icon: 'none' }) }
      finally { this.busy = false }
    },
    async changeCategory(clan, event) {
      const selected = this.categories[Number(event.detail.value) || 0]
      if (!selected || selected.key === clan.category) return
      try { await updatePlatformManagedClan(this.allianceId, clan.clan_tag, { category: selected.key }); await this.loadData() }
      catch (err) { uni.showToast({ title: err.message || '更新失败', icon: 'none' }) }
    },
    editClanName(clan) {
      uni.showModal({
        title: '修改部落别名', editable: true, content: clan.clan_name || '', placeholderText: clan.clan_tag,
        success: async result => {
          if (!result.confirm) return
          try { await updatePlatformManagedClan(this.allianceId, clan.clan_tag, { category: clan.category, clan_name: result.content || clan.clan_tag }); await this.loadData() }
          catch (err) { uni.showToast({ title: err.message || '更新失败', icon: 'none' }) }
        }
      })
    },
    async setVerification(clan, status) {
      try { await savePlatformVerification(this.allianceId, clan.clan_tag, status, '平台人工操作'); await this.loadData(); uni.showToast({ title: '认证状态已更新', icon: 'success' }) }
      catch (err) { uni.showModal({ title: '操作失败', content: err.message || '请稍后重试', showCancel: false }) }
    },
    confirmRemove(clan) {
      uni.showModal({
        title: '移除部落', content: `确认移除${clan.clan_name || clan.clan_tag}？公共历史数据不会删除。`, confirmColor: '#c9797f',
        success: async result => {
          if (!result.confirm) return
          try { await removePlatformManagedClan(this.allianceId, clan.clan_tag); await this.loadData(); uni.showToast({ title: '部落已移除', icon: 'success' }) }
          catch (err) { uni.showToast({ title: err.message || '移除失败', icon: 'none' }) }
        }
      })
    },
    categoryIndex(value) { const index = this.categories.findIndex(item => item.key === value); return index < 0 ? 0 : index },
    categoryLabel(value) { const item = this.categories.find(item => item.key === value); return item ? item.label : value },
    verificationLabel(value) { return ({ verified: '已认证', disputed: '争议中', revoked: '已撤销', unverified: '未认证' }[value] || value) }
  }
}
</script>

<style>
.page { height: 100vh; display: flex; flex-direction: column; color: #dce1ed; background: #0f0f23; }.content { flex: 1; min-height: 0; padding: 24rpx; box-sizing: border-box; }.state { padding: 180rpx 24rpx; color: #717b91; font-size: 25rpx; text-align: center; }.state.compact { padding: 80rpx 24rpx; }
.summary-card, .card, .clan-card { padding: 24rpx; border: 1rpx solid #292945; border-radius: 14rpx; background: #18182d; }.summary-card { display: flex; align-items: center; justify-content: space-between; }.summary-title, .summary-sub, .clan-name, .clan-meta, .result-count { display: block; }.summary-title { color: #f2f3f8; font-size: 30rpx; font-weight: 700; }.summary-sub { margin-top: 8rpx; color: #737d92; font-size: 21rpx; }.summary-role { color: #68a8e9; font-size: 22rpx; }
.section-title { margin: 30rpx 8rpx 14rpx; color: #7f8aa2; font-size: 23rpx; }.input, .picker-field, .search-box { border: 1rpx solid #30304d; border-radius: 10rpx; color: #dce1ed; background: #111126; }.input, .picker-field { height: 84rpx; padding: 0 20rpx; box-sizing: border-box; font-size: 23rpx; line-height: 84rpx; }.picker-field { margin-top: 14rpx; color: #a4adbf; }.primary-btn { border: 0; border-radius: 10rpx; color: #fff; background: #315f9a; font-size: 24rpx; }.primary-btn::after { border: 0; }.full-btn { width: 100%; height: 84rpx; margin-top: 16rpx; line-height: 84rpx; }.primary-btn[disabled] { color: #6f7890; background: #222b40; }
.search-box { height: 82rpx; display: flex; align-items: center; padding: 0 18rpx; box-sizing: border-box; }.search-icon { margin-right: 12rpx; color: #71809a; font-size: 30rpx; }.search-input { flex: 1; min-width: 0; color: #dce1ed; font-size: 23rpx; }.search-clear { margin-left: 14rpx; color: #74a9df; font-size: 21rpx; }.result-count { margin: 12rpx 8rpx 0; color: #657087; font-size: 20rpx; }
.clan-list { margin-top: 16rpx; }.clan-card { margin-bottom: 16rpx; }.clan-head { display: flex; align-items: center; }.order-column { width: 48rpx; flex-shrink: 0; display: flex; flex-direction: column; align-items: center; }.order-btn { color: #6da9e8; font-size: 27rpx; line-height: 1.5; }.order-btn.disabled { color: #3d4558; }.grow { flex: 1; min-width: 0; }.clan-name { color: #e7e9f0; font-size: 27rpx; font-weight: 600; }.clan-meta { margin-top: 7rpx; color: #69738a; font-size: 20rpx; }
.action-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14rpx; margin-top: 20rpx; padding-top: 18rpx; border-top: 1rpx solid #292945; }.action-btn { width: 100%; height: 66rpx; margin: 0; padding: 0 12rpx; box-sizing: border-box; display: flex; align-items: center; justify-content: center; border: 1rpx solid #32445d; border-radius: 10rpx; color: #82b7eb; background: #202b42; font-size: 20rpx; line-height: 66rpx; }.action-btn::after { border: 0; }.action-btn.verify { color: #67b8a4; }.action-btn.warn { color: #d4a665; }.action-btn.danger { color: #c9858b; background: rgba(120,45,54,.14); border-color: rgba(184,95,105,.34); }.bottom-space { height: 80rpx; }
</style>
