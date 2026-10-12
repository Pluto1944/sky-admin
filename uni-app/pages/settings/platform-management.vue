<template>
  <view class="page">
    <TopBar title="超级管理" :show-back="true" back-fallback="/pages/settings/settings" />
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
          <text class="name">免费部落总配额</text>
          <input v-model="freeLimit" class="limit-input" type="number" maxlength="5" />
        </view>
        <text class="sub">当前 {{ settings.active || 0 }} 个，剩余 {{ settings.remaining || 0 }} 个</text>
        <button class="primary-btn" :loading="busy" @tap="saveSettings">保存开放设置</button>
      </view>

      <view class="section-title">同步队列</view>
      <view class="card queue-card">
        <view v-for="(count, key) in queue" :key="key" class="queue-row">
          <text>{{ key }}</text><text>{{ count }}</text>
        </view>
        <text v-if="!Object.keys(queue).length" class="sub">当前无任务记录</text>
      </view>

      <template v-if="verificationConflicts.length">
        <view class="section-title">认证冲突</view>
        <view class="card">
          <view v-for="item in verificationConflicts" :key="item.clan_tag" class="queue-row">
            <text>{{ item.clan_tag }}</text><text>{{ item.alliance_names }}</text>
          </view>
        </view>
      </template>

      <view class="section-title">联盟查询</view>
      <view class="search-row">
        <input v-model="search" class="search-input" placeholder="联盟名称或标识" placeholder-style="color:#59637a" />
        <button class="search-btn" @tap="loadDashboard">查询</button>
      </view>
      <view v-for="item in alliances" :key="item.id" class="card alliance-card" @tap="openAlliance(item)">
        <view class="title-row">
          <text class="name grow">{{ item.name }}</text>
          <text :class="['status', 'status-' + item.status]">{{ statusLabel(item.status) }}</text>
        </view>
        <text class="sub">{{ item.plan_code }} · {{ item.clan_count }} 部落 · {{ item.member_count }} 成员 · 已认证 {{ item.verified_count || 0 }}</text>
        <text v-if="item.expires_at" class="sub">权益至 {{ shortDate(item.expires_at) }}</text>
      </view>

      <template v-if="detail">
        <view class="section-title">当前操作：{{ detail.alliance.name }}</view>
        <view class="card">
          <text class="name">人工部落认证</text>
          <view v-for="clan in detail.clans" :key="clan.id" class="clan-row">
            <view class="grow">
              <text class="name small">{{ clan.clan_name || clan.clan_tag }}</text>
              <text class="sub">{{ clan.clan_tag }} · {{ verificationLabel(clan.verification_status) }}</text>
            </view>
            <button v-if="clan.verification_status !== 'verified' && clan.status === 'active'" class="mini-btn" @tap="setVerification(clan, 'verified')">认证</button>
            <button v-if="clan.verification_status === 'verified'" class="mini-btn danger" @tap="setVerification(clan, 'revoked')">撤销</button>
            <button v-if="clan.status === 'active'" class="mini-btn warn" @tap="setVerification(clan, 'disputed')">争议</button>
          </view>
        </view>

        <view class="card action-card">
          <text class="name">套餐权益</text>
          <text class="sub">当前 {{ detail.alliance.plan_code }} · {{ detail.alliance.grant_status || '兼容权益' }}<text v-if="detail.alliance.expires_at"> · {{ shortDate(detail.alliance.expires_at) }}</text></text>
          <button class="primary-btn" @tap="grantPaid">开通付费版365天</button>
          <button class="secondary-btn" @tap="grantFree">设为免费版</button>
        </view>

        <view class="card action-card">
          <text class="name">联盟状态</text>
          <text class="sub">当前：{{ statusLabel(detail.alliance.status) }}</text>
          <button v-if="detail.alliance.status === 'active'" class="secondary-btn danger-text" @tap="changeStatus('suspended')">暂停联盟</button>
          <button v-else class="primary-btn" @tap="changeStatus('active')">恢复联盟</button>
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
import {
  getPlatformAlliance,
  getPlatformAlliances,
  savePlatformAllianceStatus,
  savePlatformFreeRegistration,
  savePlatformPlan,
  savePlatformVerification
} from '@/utils/api.js'

export default {
  components: { TopBar },
  data() {
    return {
      busy: false,
      search: '',
      settings: {},
      freeEnabled: false,
      freeLimit: '20',
      alliances: [],
      queue: {},
      audits: [],
      verificationConflicts: [],
      detail: null
    }
  },
  async onLoad() { await this.loadDashboard() },
  methods: {
    async loadDashboard() {
      this.busy = true
      try {
        const result = await getPlatformAlliances(this.search.trim())
        this.settings = result.settings || {}
        this.freeEnabled = Boolean(this.settings.public_open)
        this.freeLimit = String(this.settings.limit === undefined ? 20 : this.settings.limit)
        this.alliances = result.alliances || []
        this.queue = result.queue || {}
        this.audits = result.audit || []
        this.verificationConflicts = result.verification_conflicts || []
      } catch (err) {
        uni.showModal({ title: '超级管理不可用', content: err.message || '请稍后重试', showCancel: false })
      } finally {
        this.busy = false
      }
    },
    async saveSettings() {
      if (this.busy) return
      this.busy = true
      try {
        this.settings = await savePlatformFreeRegistration(this.freeEnabled, Number(this.freeLimit || 0))
        uni.showToast({ title: '设置已保存', icon: 'success' })
      } catch (err) {
        uni.showToast({ title: err.message || '保存失败', icon: 'none' })
      } finally {
        this.busy = false
      }
    },
    async openAlliance(item) {
      try {
        this.detail = await getPlatformAlliance(item.id)
      } catch (err) {
        uni.showToast({ title: err.message || '加载失败', icon: 'none' })
      }
    },
    async setVerification(clan, status) {
      try {
        await savePlatformVerification(this.detail.alliance.id, clan.clan_tag, status, '平台人工操作')
        this.detail = await getPlatformAlliance(this.detail.alliance.id)
        await this.loadDashboard()
        uni.showToast({ title: '认证状态已更新', icon: 'success' })
      } catch (err) {
        uni.showModal({ title: '操作失败', content: err.message || '请稍后重试', showCancel: false })
      }
    },
    async grantPaid() {
      const expiry = new Date(Date.now() + 365 * 24 * 60 * 60 * 1000).toISOString()
      try {
        await savePlatformPlan(this.detail.alliance.id, 'paid', expiry, '后台人工开通')
        this.detail = await getPlatformAlliance(this.detail.alliance.id)
        await this.loadDashboard()
        uni.showToast({ title: '付费权益已开通', icon: 'success' })
      } catch (err) {
        uni.showModal({ title: '开通失败', content: err.message || '请稍后重试', showCancel: false })
      }
    },
    async grantFree() {
      try {
        await savePlatformPlan(this.detail.alliance.id, 'free', null, '后台调整为免费版')
        this.detail = await getPlatformAlliance(this.detail.alliance.id)
        await this.loadDashboard()
        uni.showToast({ title: '已调整为免费版', icon: 'success' })
      } catch (err) {
        uni.showModal({ title: '调整失败', content: err.message || '请先移除多余部落', showCancel: false })
      }
    },
    changeStatus(status) {
      uni.showModal({
        title: status === 'active' ? '恢复联盟' : '暂停联盟',
        content: status === 'active' ? '确认恢复该联盟？' : '暂停后成员将暂时无法访问，公共历史不会删除。',
        success: async res => {
          if (!res.confirm) return
          try {
            await savePlatformAllianceStatus(this.detail.alliance.id, status, '平台人工操作')
            this.detail = await getPlatformAlliance(this.detail.alliance.id)
            await this.loadDashboard()
          } catch (err) {
            uni.showToast({ title: err.message || '操作失败', icon: 'none' })
          }
        }
      })
    },
    statusLabel(value) { return ({ active: '正常', suspended: '已暂停', archived: '已归档' }[value] || value) },
    verificationLabel(value) { return ({ verified: '已认证', disputed: '争议中', revoked: '已撤销', unverified: '未认证' }[value] || value) },
    shortDate(value) { return value ? String(value).replace('T', ' ').slice(0, 16) : '' }
  }
}
</script>

<style>
.page { height: 100vh; display: flex; flex-direction: column; color: #dce1ed; background: #0f0f23; }
.content { flex: 1; min-height: 0; padding: 24rpx; box-sizing: border-box; }
.section-title { margin: 30rpx 8rpx 14rpx; color: #7f8aa2; font-size: 23rpx; }
.card { margin-bottom: 16rpx; padding: 22rpx; border: 1rpx solid #292945; border-radius: 14rpx; background: #18182d; }
.setting-row, .title-row, .clan-row, .queue-row, .audit-row, .search-row { display: flex; align-items: center; }
.setting-row { min-height: 84rpx; }.grow { flex: 1; min-width: 0; }
.name { display: block; color: #e8ebf3; font-size: 26rpx; font-weight: 600; }.name.small { font-size: 24rpx; }
.sub { display: block; color: #778198; font-size: 21rpx; line-height: 1.6; }
.limit-input { width: 150rpx; padding: 12rpx; border: 1rpx solid #30304d; border-radius: 8rpx; color: #fff; text-align: center; background: #111126; }
.primary-btn, .secondary-btn, .search-btn, .mini-btn { border: 0; border-radius: 9rpx; font-size: 23rpx; }
.primary-btn, .secondary-btn { margin-top: 18rpx; line-height: 2.4; }.primary-btn { color: #fff; background: #315f9a; }.secondary-btn { color: #7eb8f6; background: #202b42; }
.primary-btn::after, .secondary-btn::after, .search-btn::after, .mini-btn::after { border: 0; }
.queue-row { justify-content: space-between; min-height: 54rpx; color: #9099ac; font-size: 22rpx; }
.search-row { margin-bottom: 18rpx; }.search-input { flex: 1; padding: 18rpx; border: 1rpx solid #292945; border-radius: 10rpx; color: #fff; background: #18182d; }.search-btn { width: 120rpx; margin-left: 12rpx; color: #7eb8f6; background: #202b42; line-height: 2.45; }
.alliance-card:active { background: #202038; }.status { color: #8d96a8; font-size: 21rpx; }.status-active { color: #54b9a6; }.status-suspended { color: #d29a5f; }.status-archived { color: #737b8e; }
.clan-row { min-height: 100rpx; border-bottom: 1rpx solid #25253e; }.clan-row:last-child { border-bottom: 0; }
.mini-btn { margin: 0 0 0 8rpx; padding: 5rpx 12rpx; color: #7eb8f6; background: #202b42; line-height: 2; }.mini-btn.warn { color: #d4a665; }.mini-btn.danger { color: #c9797f; }
.action-card { margin-top: 16rpx; }.danger-text { color: #c9797f; }
.audit-row { min-height: 58rpx; border-bottom: 1rpx solid #24243c; }.time { margin-left: 12rpx; color: #5f687e; font-size: 19rpx; }
.bottom-space { height: 80rpx; }
</style>
