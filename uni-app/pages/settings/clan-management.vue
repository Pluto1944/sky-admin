<template>
  <view class="page">
    <TopBar title="部落管理" :show-back="true" back-fallback="/pages/clan/clan" />
    <scroll-view scroll-y class="content">
      <view v-if="loading" class="state">正在加载...</view>
      <template v-else-if="alliance && management.can_manage">
        <view class="summary">
          <view>
            <text class="summary-title">{{ alliance.name }}</text>
            <text class="summary-sub">已添加 {{ activeClans.length }}/{{ management.max_clans }} 个部落</text>
          </view>
          <text class="summary-role">{{ alliance.role_label || roleLabel(alliance.role) }}</text>
        </view>

        <view v-if="activeClans.length" class="card clan-list">
          <view v-for="(clan, index) in activeClans" :key="clan.clan_tag" class="clan-row">
            <view class="order-actions">
              <text :class="['order-btn', { disabled: index === 0 }]" @tap="moveClan(index, -1)">↑</text>
              <text :class="['order-btn', { disabled: index === activeClans.length - 1 }]" @tap="moveClan(index, 1)">↓</text>
            </view>
            <view class="clan-main">
              <text class="clan-name">{{ clan.clan_name || clan.clan_tag }}</text>
              <text class="clan-meta">{{ clan.clan_tag }} · {{ verificationLabel(clan.verification_status) }}</text>
            </view>
            <picker :range="categories" range-key="label" :value="categoryIndex(clan.category)" @change="changeCategory(clan, $event)">
              <text class="category">{{ categoryLabel(clan.category) }}⌄</text>
            </picker>
            <text class="remove" @tap="confirmRemove(clan)">移除</text>
          </view>
        </view>

        <view v-else class="empty-card">
          <text class="empty-title">还没有部落</text>
          <text class="empty-tip">添加后会进入后台同步队列，公共资料首次出现需要一点时间。</text>
        </view>

        <view class="section-title">添加新部落</view>
        <view class="card add-card">
          <template v-if="management.can_add">
            <input v-model="newClanTag" class="input" maxlength="15" placeholder="部落标签，例如 #2QQ" placeholder-style="color:#59637a" />
            <picker :range="categories" range-key="label" :value="newCategoryIndex" @change="newCategoryIndex = Number($event.detail.value) || 0">
              <view class="picker">部落标签：{{ categories[newCategoryIndex].label }}⌄</view>
            </picker>
            <button class="primary-btn" :loading="saving" :disabled="saving || !newClanTag.trim()" @tap="addClan">添加部落</button>
          </template>
          <text v-else class="limit-tip">已达到当前套餐上限（{{ management.max_clans }} 个）。移除现有部落后可再添加。</text>
          <text class="notice">新部落默认未认证；移除只会停止当前联盟订阅，不会删除已有公共历史数据。</text>
        </view>
        <view class="bottom-space"></view>
      </template>
      <view v-else-if="alliance" class="state">只有联盟管理员或首领可以管理部落</view>
      <view v-else class="state">请先创建或加入联盟</view>
    </scroll-view>
  </view>
</template>

<script>
import TopBar from '@/components/TopBar.vue'
import {
  addAllianceManagedClan,
  getAllianceManagedClans,
  removeAllianceManagedClan,
  reorderAllianceManagedClans,
  updateAllianceManagedClan
} from '@/utils/api.js'
import { getCurrentAlliance, loadAllianceContext } from '@/utils/alliance.js'

export default {
  components: { TopBar },
  data() {
    return {
      loading: true,
      saving: false,
      alliance: null,
      management: { clans: [], max_clans: 1, can_manage: false, can_add: false },
      newClanTag: '',
      newCategoryIndex: 0,
      categories: [
        { key: 'normal', label: '实战' },
        { key: 'combat', label: '战营' },
        { key: 'farm', label: '互刷' },
        { key: 'flat', label: '偷矿' }
      ]
    }
  },
  computed: {
    activeClans() {
      return (this.management.clans || []).filter(item => item.status === 'active')
    }
  },
  async onLoad() { await this.loadData() },
  methods: {
    async loadData() {
      this.loading = true
      try {
        const loaded = await loadAllianceContext()
        this.alliance = loaded.current || getCurrentAlliance()
        if (this.alliance) this.management = await getAllianceManagedClans(this.alliance.id)
      } catch (err) {
        uni.showToast({ title: err.message || '加载失败', icon: 'none' })
      } finally {
        this.loading = false
      }
    },
    async refreshContextAndData() {
      await loadAllianceContext(this.alliance.id, true)
      this.alliance = getCurrentAlliance()
      this.management = await getAllianceManagedClans(this.alliance.id)
    },
    async addClan() {
      if (!this.alliance || this.saving || !this.newClanTag.trim()) return
      this.saving = true
      try {
        await addAllianceManagedClan(this.alliance.id, {
          clan_tag: this.newClanTag.trim(),
          category: this.categories[this.newCategoryIndex].key
        })
        this.newClanTag = ''
        await this.refreshContextAndData()
        uni.showToast({ title: '部落已添加', icon: 'success' })
      } catch (err) {
        uni.showModal({ title: '添加失败', content: err.message || '请稍后重试', showCancel: false })
      } finally {
        this.saving = false
      }
    },
    async changeCategory(clan, event) {
      const selected = this.categories[Number(event.detail.value) || 0]
      if (!selected || selected.key === clan.category) return
      try {
        await updateAllianceManagedClan(this.alliance.id, clan.clan_tag, { category: selected.key })
        clan.category = selected.key
        uni.showToast({ title: '标签已更新', icon: 'success' })
      } catch (err) {
        uni.showToast({ title: err.message || '更新失败', icon: 'none' })
      }
    },
    async moveClan(index, offset) {
      const target = index + offset
      if (target < 0 || target >= this.activeClans.length) return
      const ordered = this.activeClans.slice()
      const moved = ordered.splice(index, 1)[0]
      ordered.splice(target, 0, moved)
      try {
        await reorderAllianceManagedClans(this.alliance.id, ordered.map(item => item.clan_tag))
        const inactive = (this.management.clans || []).filter(item => item.status !== 'active')
        this.management.clans = ordered.concat(inactive)
      } catch (err) {
        uni.showToast({ title: err.message || '排序失败', icon: 'none' })
      }
    },
    confirmRemove(clan) {
      uni.showModal({
        title: '移除部落',
        content: `确认从当前联盟移除${clan.clan_name || clan.clan_tag}？已有公共历史数据不会删除。`,
        confirmColor: '#c9797f',
        success: async result => {
          if (!result.confirm) return
          try {
            await removeAllianceManagedClan(this.alliance.id, clan.clan_tag)
            await this.refreshContextAndData()
            uni.showToast({ title: '已移除', icon: 'success' })
          } catch (err) {
            uni.showToast({ title: err.message || '移除失败', icon: 'none' })
          }
        }
      })
    },
    categoryIndex(value) { const index = this.categories.findIndex(item => item.key === value); return index < 0 ? 0 : index },
    categoryLabel(value) { const item = this.categories.find(entry => entry.key === value); return item ? item.label : value },
    verificationLabel(value) { return ({ verified: '已认证', disputed: '有争议', revoked: '已撤销', unverified: '未认证' }[value] || '未认证') },
    roleLabel(value) { return ({ leader: '首领', admin: '管理', member: '成员' }[value] || value) }
  }
}
</script>

<style>
.page { height: 100vh; display: flex; flex-direction: column; color: #dce1ed; background: #0f0f23; }
.content { flex: 1; min-height: 0; padding: 24rpx; box-sizing: border-box; }
.state { padding: 180rpx 24rpx; color: #717b91; font-size: 26rpx; text-align: center; }
.summary { display: flex; align-items: center; justify-content: space-between; padding: 24rpx; border: 1rpx solid #292945; border-radius: 14rpx; background: #18182d; }
.summary-title, .summary-sub { display: block; }.summary-title { color: #f2f3f8; font-size: 31rpx; font-weight: 700; }.summary-sub { margin-top: 8rpx; color: #737d92; font-size: 22rpx; }.summary-role { color: #68a8e9; font-size: 22rpx; }
.section-title { margin: 30rpx 8rpx 14rpx; color: #7f8aa2; font-size: 23rpx; }
.card, .empty-card { border: 1rpx solid #292945; border-radius: 14rpx; background: #18182d; }
.clan-list { margin-top: 20rpx; overflow: hidden; }
.clan-row { min-height: 112rpx; padding: 14rpx 18rpx; box-sizing: border-box; display: flex; align-items: center; border-bottom: 1rpx solid #25253e; }.clan-row:last-child { border-bottom: 0; }
.order-actions { width: 54rpx; flex-shrink: 0; display: flex; flex-direction: column; align-items: center; }.order-btn { color: #6da9e8; font-size: 27rpx; line-height: 1.45; }.order-btn.disabled { color: #3d4558; }
.clan-main { flex: 1; min-width: 0; }.clan-name, .clan-meta { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.clan-name { color: #e7e9f0; font-size: 26rpx; font-weight: 600; }.clan-meta { margin-top: 7rpx; color: #69738a; font-size: 20rpx; }
.category { margin-left: 10rpx; padding: 9rpx 11rpx; border-radius: 8rpx; color: #78afe8; background: #202940; font-size: 21rpx; }.remove { margin-left: 14rpx; color: #b8757d; font-size: 21rpx; }
.empty-card { margin-top: 20rpx; padding: 70rpx 30rpx; text-align: center; }.empty-title, .empty-tip { display: block; }.empty-title { color: #ced3df; font-size: 27rpx; }.empty-tip { margin-top: 14rpx; color: #6c758a; font-size: 22rpx; line-height: 1.6; }
.add-card { padding: 24rpx; }.input, .picker { padding: 18rpx; border: 1rpx solid #30304d; border-radius: 10rpx; color: #dce1ed; background: #111126; font-size: 24rpx; }.picker { margin-top: 14rpx; color: #a4adbf; }
.primary-btn { margin-top: 18rpx; border: 0; border-radius: 10rpx; color: #fff; background: #315f9a; font-size: 25rpx; line-height: 2.55; }.primary-btn::after { border: 0; }.primary-btn[disabled] { color: #6f7890; background: #222b40; }
.limit-tip, .notice { display: block; color: #8790a2; font-size: 22rpx; line-height: 1.6; }.notice { margin-top: 18rpx; color: #646e84; }.bottom-space { height: 80rpx; }
</style>
