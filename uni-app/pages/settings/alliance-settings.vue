<template>
  <view class="page">
    <TopBar title="联盟设置" :show-back="true" back-fallback="/pages/settings/alliance-management" />
    <scroll-view scroll-y class="content">
      <view v-if="loading" class="state">正在加载...</view>
      <template v-else-if="alliance">
        <view class="summary-card">
          <view class="grow"><text class="summary-name">{{ alliance.name }}</text><text class="summary-sub">联盟基础资料与成员关系设置</text></view>
          <text class="summary-role">{{ alliance.role_label || roleLabel(alliance.role) }}</text>
        </view>

        <view class="section-title">联盟信息</view>
        <view class="card info-card">
          <view class="info-row"><text class="info-label">当前套餐</text><text class="info-value">{{ alliance.plan.name }}</text></view>
          <view class="info-row"><text class="info-label">权益状态</text><text class="info-value">{{ planStateLabel(alliance.plan.status) }}</text></view>
          <view v-if="alliance.plan.expires_at" class="info-row"><text class="info-label">权益到期</text><text class="info-value">{{ shortDate(alliance.plan.expires_at) }}</text></view>
          <view class="info-row"><text class="info-label">部落数量</text><text class="info-value">{{ alliance.clan_count || 0 }} 个</text></view>
        </view>

        <template v-if="alliance.role === 'leader'">
          <view class="section-title">联盟名称</view>
          <view class="card form-card">
            <input v-model="allianceName" class="input" maxlength="30" placeholder="联盟名称" placeholder-style="color:#59637a" />
            <button class="primary-btn" :loading="saving" :disabled="saving || !allianceName.trim()" @tap="saveName">保存联盟名称</button>
          </view>
        </template>

        <view class="section-title">成员关系</view>
        <view class="card action-card">
          <template v-if="alliance.role !== 'leader'">
            <text class="body">退出后将失去当前联盟访问权限，以后仍可通过新的有效邀请重新加入。</text>
            <button class="danger-btn" @tap="confirmLeave">退出当前联盟</button>
          </template>
          <template v-else-if="alliance.plan.code !== 'internal'">
            <text class="body">删除联盟前需要输入完整联盟名称确认。公共部落及战争历史数据不会删除。</text>
            <button class="danger-btn" @tap="confirmArchive">删除当前联盟</button>
          </template>
          <text v-else class="body">内部联盟不能从普通管理入口退出或删除。</text>
        </view>
      </template>
      <view v-else class="state">请先创建或加入联盟</view>
      <view class="bottom-space"></view>
    </scroll-view>
  </view>
</template>

<script>
import TopBar from '@/components/TopBar.vue'
import { archiveAlliance, leaveAlliance, renameAlliance } from '@/utils/api.js'
import { getCurrentAlliance, loadAllianceContext } from '@/utils/alliance.js'

export default {
  components: { TopBar },
  data() { return { loading: true, saving: false, alliance: null, allianceName: '' } },
  async onShow() { await this.loadData() },
  methods: {
    async loadData() {
      this.loading = true
      try {
        const loaded = await loadAllianceContext()
        this.alliance = loaded.current || getCurrentAlliance()
        if (!this.alliance) return
        if (['admin', 'leader'].indexOf(this.alliance.role) < 0) {
          uni.showToast({ title: '没有联盟管理权限', icon: 'none' })
          setTimeout(() => uni.navigateBack(), 500)
          return
        }
        this.allianceName = this.alliance.name
      } catch (err) { uni.showToast({ title: err.message || '加载失败', icon: 'none' }) }
      finally { this.loading = false }
    },
    async saveName() {
      const name = this.allianceName.trim()
      if (!name || !this.alliance || this.saving) return
      this.saving = true
      try {
        await renameAlliance(this.alliance.id, name)
        await loadAllianceContext(this.alliance.id, true)
        await this.loadData()
        uni.showToast({ title: '名称已保存', icon: 'success' })
      } catch (err) { uni.showToast({ title: err.message || '保存失败', icon: 'none' }) }
      finally { this.saving = false }
    },
    confirmLeave() {
      uni.showModal({
        title: '退出当前联盟', content: `确认退出${this.alliance.name}？`, confirmColor: '#d56b72',
        success: async result => {
          if (!result.confirm) return
          try {
            await leaveAlliance(this.alliance.id)
            const loaded = await loadAllianceContext(null, true)
            uni.switchTab({ url: loaded.current ? '/pages/clan/clan' : '/pages/settings/settings' })
          } catch (err) { uni.showToast({ title: err.message || '退出失败', icon: 'none' }) }
        }
      })
    },
    confirmArchive() {
      if (!this.alliance || this.alliance.role !== 'leader') return
      uni.showModal({
        title: '删除当前联盟', content: `请输入联盟名称“${this.alliance.name}”确认删除`, editable: true,
        placeholderText: '联盟名称', confirmColor: '#d56b72',
        success: async result => {
          if (!result.confirm) return
          try {
            await archiveAlliance(this.alliance.id, result.content)
            const loaded = await loadAllianceContext(null, true)
            uni.switchTab({ url: loaded.current ? '/pages/clan/clan' : '/pages/settings/settings' })
            uni.showToast({ title: '联盟已删除', icon: 'success' })
          } catch (err) { uni.showToast({ title: err.message || '删除失败', icon: 'none' }) }
        }
      })
    },
    roleLabel(value) { return ({ leader: '首领', admin: '管理', member: '成员' }[value] || value) },
    planStateLabel(value) { return ({ active: '有效', grace: '7天只读宽限期', legacy: '兼容权益', expired: '已到期', revoked: '已撤销' }[value] || value || '有效') },
    shortDate(value) { return value ? String(value).replace('T', ' ').slice(0, 16) : '—' }
  }
}
</script>

<style>
.page { height: 100vh; display: flex; flex-direction: column; color: #dce1ed; background: #0f0f23; }.content { flex: 1; min-height: 0; padding: 24rpx; box-sizing: border-box; }.state { padding: 180rpx 24rpx; color: #717b91; text-align: center; }
.summary-card, .card { border: 1rpx solid #292945; border-radius: 14rpx; background: #18182d; }.summary-card { padding: 24rpx; display: flex; align-items: center; }.grow { flex: 1; min-width: 0; }.summary-name, .summary-sub { display: block; }.summary-name { color: #f2f3f8; font-size: 31rpx; font-weight: 700; }.summary-sub { margin-top: 8rpx; color: #737d92; font-size: 21rpx; }.summary-role { margin-left: 16rpx; color: #68a8e9; font-size: 22rpx; }
.section-title { margin: 30rpx 8rpx 14rpx; color: #7f8aa2; font-size: 23rpx; }.info-card { padding: 10rpx 24rpx; }.info-row { min-height: 76rpx; display: flex; align-items: center; justify-content: space-between; border-bottom: 1rpx solid #25253e; }.info-row:last-child { border-bottom: 0; }.info-label { color: #7b859b; font-size: 22rpx; }.info-value { color: #dce1ed; font-size: 23rpx; }
.form-card, .action-card { padding: 24rpx; }.input { height: 84rpx; padding: 0 18rpx; box-sizing: border-box; border: 1rpx solid #30304d; border-radius: 10rpx; color: #dce1ed; background: #111126; font-size: 24rpx; }.primary-btn, .danger-btn { width: 100%; margin-top: 18rpx; border-radius: 10rpx; font-size: 24rpx; line-height: 2.45; }.primary-btn { border: 0; color: #fff; background: #315f9a; }.danger-btn { border: 1rpx solid #57363f; color: #c9797f; background: transparent; }.primary-btn::after, .danger-btn::after { border: 0; }.primary-btn[disabled] { color: #6f7890; background: #222b40; }.body { display: block; color: #8a94a9; font-size: 22rpx; line-height: 1.65; }.bottom-space { height: 80rpx; }
</style>
