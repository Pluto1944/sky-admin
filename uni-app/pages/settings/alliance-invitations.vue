<template>
  <view class="page">
    <TopBar title="邀请管理" :show-back="true" back-fallback="/pages/settings/alliance-management" />
    <scroll-view scroll-y class="content">
      <view v-if="loading" class="state">正在加载...</view>
      <template v-else-if="alliance">
        <view class="summary-card">
          <view class="grow"><text class="summary-name">{{ alliance.name }}</text><text class="summary-sub">有效邀请 {{ activeInviteCount }} 条 · 全部记录 {{ links.length }} 条</text></view>
          <text class="summary-role">{{ alliance.role_label || roleLabel(alliance.role) }}</text>
        </view>

        <view class="section-title">生成邀请</view>
        <view class="card invite-card">
          <text class="body">其他用户登录后打开分享，将以普通成员身份加入联盟，不会继承分享人的管理权限。</text>
          <button class="primary-btn" :loading="shareBusy" :disabled="shareBusy" @tap="generateShare">生成30天邀请</button>
          <template v-if="shareToken">
            <view class="generated-box">
              <text class="generated-title">邀请已生成</text>
              <text class="generated-tip">有效期至 {{ shortDate(shareExpiresAt) }}</text>
            </view>
            <button class="share-btn" open-type="share">分享联盟</button>
            <button class="text-btn" @tap="copySharePath">复制邀请参数</button>
          </template>
        </view>

        <view class="entry-card" @tap="openShareHistory">
          <view class="entry-icon">录</view>
          <view class="grow"><text class="entry-name">邀请记录</text><text class="entry-sub">查看状态、使用人数、有效期并撤销邀请</text></view>
          <text class="entry-count">{{ links.length }} 条</text><text class="arrow">›</text>
        </view>
      </template>
      <view v-else class="state">请先创建或加入联盟</view>
      <view class="bottom-space"></view>
    </scroll-view>
  </view>
</template>

<script>
import TopBar from '@/components/TopBar.vue'
import { createAllianceShare, getAllianceShares } from '@/utils/api.js'
import { getCurrentAlliance, loadAllianceContext, rememberAllianceShareToken } from '@/utils/alliance.js'

export default {
  components: { TopBar },
  data() { return { loading: true, shareBusy: false, alliance: null, links: [], shareToken: '', shareExpiresAt: '' } },
  computed: { activeInviteCount() { return this.links.filter(item => item.status === 'active').length } },
  async onShow() { await this.loadData() },
  onShareAppMessage() {
    if (!this.shareToken || !this.alliance) return { title: '联盟邀请', path: '/pages/settings/settings' }
    return { title: `${this.alliance.name}邀请你加入`, path: `/pages/clan/clan?share_token=${encodeURIComponent(this.shareToken)}` }
  },
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
        const result = await getAllianceShares(this.alliance.id)
        this.links = result.links || []
      } catch (err) { uni.showToast({ title: err.message || '加载失败', icon: 'none' }) }
      finally { this.loading = false }
    },
    async generateShare() {
      if (!this.alliance || this.shareBusy) return
      this.shareBusy = true
      try {
        const result = await createAllianceShare(this.alliance.id, 30)
        this.shareToken = result.token
        this.shareExpiresAt = result.expires_at
        rememberAllianceShareToken(this.alliance.id, result.token, result.expires_at, 'invite')
        await this.loadData()
        uni.showToast({ title: '邀请已生成', icon: 'success' })
      } catch (err) { uni.showToast({ title: err.message || '生成失败', icon: 'none' }) }
      finally { this.shareBusy = false }
    },
    copySharePath() {
      if (!this.shareToken) return
      uni.setClipboardData({ data: `share_token=${this.shareToken}`, success: () => uni.showToast({ title: '邀请参数已复制', icon: 'success' }) })
    },
    openShareHistory() { uni.navigateTo({ url: '/pages/settings/alliance-invite-history' }) },
    roleLabel(value) { return ({ leader: '首领', admin: '管理', member: '成员' }[value] || value) },
    shortDate(value) { return value ? String(value).replace('T', ' ').slice(0, 16) : '—' }
  }
}
</script>

<style>
.page { height: 100vh; display: flex; flex-direction: column; color: #dce1ed; background: #0f0f23; }.content { flex: 1; min-height: 0; padding: 24rpx; box-sizing: border-box; }.state { padding: 180rpx 24rpx; color: #717b91; text-align: center; }.grow { flex: 1; min-width: 0; }
.summary-card, .card, .entry-card { border: 1rpx solid #292945; border-radius: 14rpx; background: #18182d; }.summary-card { padding: 24rpx; display: flex; align-items: center; }.summary-name, .summary-sub, .body, .generated-title, .generated-tip, .entry-name, .entry-sub { display: block; }.summary-name { color: #f2f3f8; font-size: 31rpx; font-weight: 700; }.summary-sub { margin-top: 8rpx; color: #737d92; font-size: 21rpx; }.summary-role { margin-left: 16rpx; color: #68a8e9; font-size: 22rpx; }
.section-title { margin: 30rpx 8rpx 14rpx; color: #7f8aa2; font-size: 23rpx; }.invite-card { padding: 24rpx; }.body { color: #a0a9bc; font-size: 22rpx; line-height: 1.65; }.primary-btn, .share-btn, .text-btn { width: 100%; margin-top: 18rpx; border: 0; border-radius: 10rpx; font-size: 24rpx; line-height: 2.45; }.primary-btn { color: #fff; background: #315f9a; }.share-btn { color: #91c1ef; background: #202b42; }.text-btn { color: #8995ad; background: transparent; }.primary-btn::after, .share-btn::after, .text-btn::after { border: 0; }
.generated-box { margin-top: 20rpx; padding: 18rpx; border: 1rpx solid #2d3b54; border-radius: 10rpx; background: #151c30; }.generated-title { color: #72b8a5; font-size: 24rpx; font-weight: 600; }.generated-tip { margin-top: 7rpx; color: #748097; font-size: 20rpx; }
.entry-card { min-height: 116rpx; margin-top: 18rpx; padding: 16rpx 20rpx; box-sizing: border-box; display: flex; align-items: center; }.entry-icon { width: 58rpx; height: 58rpx; margin-right: 18rpx; display: flex; align-items: center; justify-content: center; border-radius: 13rpx; color: #ad9edb; background: #302d45; font-size: 23rpx; font-weight: 700; }.entry-name { color: #e8ebf3; font-size: 26rpx; font-weight: 600; }.entry-sub { margin-top: 7rpx; color: #778198; font-size: 21rpx; }.entry-count { margin-left: 12rpx; color: #7e89a1; font-size: 20rpx; white-space: nowrap; }.arrow { margin-left: 12rpx; color: #606b83; font-size: 36rpx; }.bottom-space { height: 80rpx; }
</style>
