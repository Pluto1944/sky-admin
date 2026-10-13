<template>
  <view class="page">
    <TopBar title="平台设置" :show-back="true" back-fallback="/pages/settings/platform-management" />
    <scroll-view scroll-y class="content">
      <view class="section-title">免费联盟开放</view>
      <view class="card">
        <view class="setting-row">
          <view class="grow">
            <text class="name">允许外部用户创建</text>
            <text class="sub">关闭后内部白名单和已有联盟不受影响</text>
          </view>
          <switch :checked="freeEnabled" color="#4a90d9" @change="freeEnabled = $event.detail.value" />
        </view>
        <view class="setting-row">
          <text class="name grow">免费部落总配额</text>
          <input v-model="freeLimit" class="limit-input" type="number" maxlength="5" />
        </view>
        <text class="sub">当前 {{ settings.active || 0 }} 个，剩余 {{ settings.remaining || 0 }} 个</text>
        <button class="primary-btn" :loading="busy" @tap="saveSettings">保存开放设置</button>
      </view>

      <view class="section-title">同步队列</view>
      <view class="card">
        <view v-for="(count, key) in queue" :key="key" class="data-row"><text>{{ key }}</text><text>{{ count }}</text></view>
        <text v-if="!Object.keys(queue).length" class="sub">当前无任务记录</text>
      </view>

      <template v-if="verificationConflicts.length">
        <view class="section-title">多联盟认证</view>
        <view class="card">
          <text class="sub notice">允许保留；如需调整，请进入对应联盟逐个撤销认证。</text>
          <view v-for="item in verificationConflicts" :key="item.clan_tag" class="conflict-row">
            <text class="name small">{{ item.clan_tag }}</text>
            <text class="sub">{{ item.alliance_names }}</text>
          </view>
        </view>
      </template>

      <view class="section-title">最近平台审计</view>
      <view class="card">
        <view v-for="(item, index) in audits" :key="index" class="audit-row">
          <text class="sub grow">{{ item.action }} · {{ item.entity_type }} {{ item.entity_id || '' }}</text>
          <text class="time">{{ shortDate(item.created_at) }}</text>
        </view>
        <text v-if="!audits.length" class="sub">暂无平台操作</text>
      </view>
      <view class="bottom-space"></view>
    </scroll-view>
  </view>
</template>

<script>
import TopBar from '@/components/TopBar.vue'
import { getPlatformAlliances, savePlatformFreeRegistration } from '@/utils/api.js'

export default {
  components: { TopBar },
  data() {
    return {
      busy: false,
      settings: {},
      freeEnabled: false,
      freeLimit: '20',
      queue: {},
      audits: [],
      verificationConflicts: []
    }
  },
  async onShow() { await this.loadSettings() },
  methods: {
    async loadSettings() {
      if (this.busy) return
      this.busy = true
      try {
        const result = await getPlatformAlliances()
        this.settings = result.settings || {}
        this.freeEnabled = Boolean(this.settings.public_open)
        this.freeLimit = String(this.settings.limit === undefined ? 20 : this.settings.limit)
        this.queue = result.queue || {}
        this.audits = result.audit || []
        this.verificationConflicts = result.multi_alliance_verifications || result.verification_conflicts || []
      } catch (err) {
        uni.showModal({ title: '平台设置不可用', content: err.message || '请稍后重试', showCancel: false })
      } finally { this.busy = false }
    },
    async saveSettings() {
      if (this.busy) return
      this.busy = true
      try {
        this.settings = await savePlatformFreeRegistration(this.freeEnabled, Number(this.freeLimit || 0))
        uni.showToast({ title: '设置已保存', icon: 'success' })
      } catch (err) {
        uni.showToast({ title: err.message || '保存失败', icon: 'none' })
      } finally { this.busy = false }
    },
    shortDate(value) { return value ? String(value).replace('T', ' ').slice(0, 16) : '' }
  }
}
</script>

<style>
.page { height: 100vh; display: flex; flex-direction: column; color: #dce1ed; background: #0f0f23; }
.content { flex: 1; min-height: 0; padding: 24rpx; box-sizing: border-box; }.section-title { margin: 30rpx 8rpx 14rpx; color: #7f8aa2; font-size: 23rpx; }.section-title:first-child { margin-top: 4rpx; }
.card { margin-bottom: 16rpx; padding: 22rpx; border: 1rpx solid #292945; border-radius: 14rpx; background: #18182d; }.setting-row, .data-row, .audit-row { display: flex; align-items: center; }.setting-row { min-height: 84rpx; }.grow { flex: 1; min-width: 0; }
.name { display: block; color: #e8ebf3; font-size: 26rpx; font-weight: 600; }.name.small { font-size: 23rpx; }.sub { display: block; color: #778198; font-size: 21rpx; line-height: 1.6; }.notice { margin-bottom: 10rpx; }
.limit-input { width: 160rpx; height: 70rpx; padding: 0 12rpx; box-sizing: border-box; border: 1rpx solid #30304d; border-radius: 9rpx; color: #fff; text-align: center; background: #111126; }
.primary-btn { height: 82rpx; margin-top: 18rpx; border: 0; border-radius: 10rpx; color: #fff; background: #315f9a; font-size: 24rpx; line-height: 82rpx; }.primary-btn::after { border: 0; }
.data-row { justify-content: space-between; min-height: 58rpx; color: #9099ac; font-size: 22rpx; }.conflict-row { padding: 14rpx 0; border-bottom: 1rpx solid #25253e; }.conflict-row:last-child { border-bottom: 0; }
.audit-row { min-height: 62rpx; border-bottom: 1rpx solid #24243c; }.audit-row:last-child { border-bottom: 0; }.time { margin-left: 12rpx; color: #5f687e; font-size: 19rpx; }.bottom-space { height: 80rpx; }
</style>
