<template>
  <view class="page">
    <TopBar title="联盟状态" :show-back="true" :back-fallback="backFallback" />
    <scroll-view scroll-y class="content">
      <view v-if="loading" class="state">正在加载...</view>
      <template v-else-if="detail">
        <view class="summary-card">
          <view class="grow"><text class="summary-title">{{ detail.alliance.name }}</text><text class="summary-sub">{{ detail.alliance.alliance_key }}</text></view>
          <text :class="['status', 'status-' + detail.alliance.status]">{{ statusLabel(detail.alliance.status) }}</text>
        </view>
        <view class="section-title">状态管理</view>
        <view class="card danger-card">
          <text class="body">停用后联盟成员将暂时无法访问，公共历史数据和审计记录不会删除。</text>
          <button v-if="detail.alliance.status === 'active'" class="secondary-btn full-btn danger-text" :loading="busy" @tap="changeStatus('suspended')">停用联盟</button>
          <template v-else-if="detail.alliance.status === 'suspended'">
            <button class="primary-btn full-btn" :loading="busy" @tap="changeStatus('active')">恢复联盟</button>
            <button class="delete-btn" :loading="busy" @tap="deleteAlliance">删除已停用联盟</button>
            <text class="danger-tip">删除后不再显示；公共历史事实和审计记录仍会保留。</text>
          </template>
          <text v-else class="body">该联盟已经删除，不能恢复。</text>
        </view>
      </template>
      <view class="bottom-space"></view>
    </scroll-view>
  </view>
</template>

<script>
import TopBar from '@/components/TopBar.vue'
import { deletePlatformAlliance, getPlatformAlliance, savePlatformAllianceStatus } from '@/utils/api.js'

export default {
  components: { TopBar },
  data() { return { allianceId: null, loading: true, busy: false, detail: null } },
  computed: { backFallback() { return `/pages/settings/platform-alliance-detail?id=${this.allianceId}` } },
  onLoad(options) { this.allianceId = Number(options && options.id) || null },
  async onShow() { if (this.allianceId) await this.loadData() },
  methods: {
    async loadData() {
      this.loading = true
      try { this.detail = await getPlatformAlliance(this.allianceId) }
      catch (err) { uni.showModal({ title: '状态加载失败', content: err.message || '请稍后重试', showCancel: false }) }
      finally { this.loading = false }
    },
    changeStatus(status) {
      uni.showModal({
        title: status === 'active' ? '恢复联盟' : '停用联盟',
        content: status === 'active' ? '确认恢复该联盟？' : '停用后成员将暂时无法访问，公共历史不会删除。',
        success: async result => {
          if (!result.confirm) return
          this.busy = true
          try { await savePlatformAllianceStatus(this.allianceId, status, '平台人工操作'); await this.loadData(); uni.showToast({ title: status === 'active' ? '联盟已恢复' : '联盟已停用', icon: 'success' }) }
          catch (err) { uni.showToast({ title: err.message || '操作失败', icon: 'none' }) }
          finally { this.busy = false }
        }
      })
    },
    deleteAlliance() {
      const alliance = this.detail.alliance
      if (alliance.status !== 'suspended') return
      uni.showModal({
        title: '删除已停用联盟', content: `请输入联盟名称“${alliance.name}”确认删除`, editable: true, placeholderText: '联盟名称', confirmColor: '#c9797f',
        success: async result => {
          if (!result.confirm) return
          this.busy = true
          try {
            await deletePlatformAlliance(alliance.id, result.content)
            uni.showToast({ title: '联盟已删除', icon: 'success' })
            setTimeout(() => uni.redirectTo({ url: '/pages/settings/platform-alliance-list' }), 400)
          } catch (err) { uni.showToast({ title: err.message || '删除失败', icon: 'none' }) }
          finally { this.busy = false }
        }
      })
    },
    statusLabel(value) { return ({ active: '正常', suspended: '已停用', archived: '已删除' }[value] || value) }
  }
}
</script>

<style>
.page { height: 100vh; display: flex; flex-direction: column; color: #dce1ed; background: #0f0f23; }.content { flex: 1; min-height: 0; padding: 24rpx; box-sizing: border-box; }.state { padding: 180rpx 24rpx; color: #717b91; text-align: center; }.summary-card, .card { padding: 24rpx; border: 1rpx solid #292945; border-radius: 14rpx; background: #18182d; }.summary-card { display: flex; align-items: center; }.grow { flex: 1; min-width: 0; }.summary-title, .summary-sub, .body, .danger-tip { display: block; }.summary-title { color: #f2f3f8; font-size: 30rpx; font-weight: 700; }.summary-sub { margin-top: 8rpx; color: #737d92; font-size: 21rpx; }.status { font-size: 22rpx; }.status-active { color: #54b9a6; }.status-suspended { color: #d29a5f; }.status-archived { color: #737b8e; }.section-title { margin: 30rpx 8rpx 14rpx; color: #7f8aa2; font-size: 23rpx; }.danger-card { border-color: #3e2934; }.body { color: #9ea7ba; font-size: 21rpx; line-height: 1.65; }.primary-btn, .secondary-btn, .delete-btn { border-radius: 10rpx; font-size: 24rpx; }.primary-btn, .secondary-btn { border: 0; }.primary-btn { color: #fff; background: #315f9a; }.secondary-btn { color: #91b9e2; background: #202b42; }.primary-btn::after, .secondary-btn::after, .delete-btn::after { border: 0; }.full-btn { width: 100%; height: 84rpx; margin-top: 18rpx; line-height: 84rpx; }.danger-text { color: #c9797f; }.delete-btn { width: 100%; margin-top: 18rpx; border: 1rpx solid rgba(201,121,127,.45); color: #d98c91; background: rgba(120,45,54,.18); line-height: 2.5; }.danger-tip { margin-top: 14rpx; color: #91676f; font-size: 21rpx; line-height: 1.6; }.bottom-space { height: 80rpx; }
</style>
