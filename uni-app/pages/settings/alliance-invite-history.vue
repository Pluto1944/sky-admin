<template>
  <view class="page">
    <TopBar title="邀请记录" :show-back="true" back-fallback="/pages/settings/alliance-management" />
    <scroll-view scroll-y class="content">
      <view v-if="loading" class="state">正在加载...</view>
      <template v-else-if="alliance">
        <view class="summary-card">
          <view>
            <text class="summary-title">{{ alliance.name }}</text>
            <text class="summary-sub">有效 {{ activeCount }} 条 · 全部 {{ links.length }} 条</text>
          </view>
          <text class="summary-role">{{ alliance.role_label || roleLabel(alliance.role) }}</text>
        </view>

        <text class="notice">后台只保存令牌摘要，历史邀请不能再次分享；需要新链接时请返回管理联盟页重新生成。</text>

        <view v-if="links.length" class="invite-list">
          <view v-for="link in links" :key="link.id" class="invite-card">
            <view class="invite-head">
              <text class="invite-title">邀请 #{{ link.id }}</text>
              <text :class="['status', 'status-' + link.status]">{{ shareStatusLabel(link.status) }}</text>
            </view>
            <view class="metric-row">
              <view class="metric">
                <text class="metric-value">{{ link.use_count }}</text>
                <text class="metric-label">已加入</text>
              </view>
              <view class="metric grow">
                <text class="metric-value small">{{ shortDate(link.expires_at) }}</text>
                <text class="metric-label">有效期至</text>
              </view>
            </view>
            <text class="invite-time">创建于 {{ shortDate(link.created_at) }}</text>
            <text v-if="link.last_used_at" class="invite-time">最后使用 {{ shortDate(link.last_used_at) }}</text>
            <button v-if="link.can_revoke && link.status === 'active'" class="revoke-btn" :loading="revokingId === link.id" :disabled="Boolean(revokingId)" @tap="confirmRevoke(link)">撤销邀请</button>
          </view>
        </view>
        <view v-else class="state">暂无邀请记录</view>
      </template>
      <view v-else class="state">请先创建或加入联盟</view>
      <view class="bottom-space"></view>
    </scroll-view>
  </view>
</template>

<script>
import TopBar from '@/components/TopBar.vue'
import { getAllianceShares, revokeAllianceShare } from '@/utils/api.js'
import { getCurrentAlliance, loadAllianceContext } from '@/utils/alliance.js'

export default {
  components: { TopBar },
  data() {
    return {
      loading: true,
      alliance: null,
      links: [],
      revokingId: 0
    }
  },
  computed: {
    activeCount() {
      return this.links.filter(item => item.status === 'active').length
    }
  },
  async onShow() {
    await this.loadData()
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
      } catch (err) {
        uni.showToast({ title: err.message || '加载失败', icon: 'none' })
      } finally {
        this.loading = false
      }
    },
    confirmRevoke(link) {
      if (!link || this.revokingId) return
      uni.showModal({
        title: '撤销联盟邀请',
        content: '撤销后，尚未使用该链接的人将不能再加入联盟。',
        confirmColor: '#c9797f',
        success: async result => {
          if (!result.confirm) return
          this.revokingId = link.id
          try {
            await revokeAllianceShare(this.alliance.id, link.id)
            await this.loadData()
            uni.showToast({ title: '邀请已撤销', icon: 'success' })
          } catch (err) {
            uni.showToast({ title: err.message || '撤销失败', icon: 'none' })
          } finally {
            this.revokingId = 0
          }
        }
      })
    },
    shareStatusLabel(value) {
      return ({ active: '有效', revoked: '已撤销', expired: '已过期' }[value] || value)
    },
    roleLabel(value) {
      return ({ leader: '首领', admin: '管理', member: '成员' }[value] || value)
    },
    shortDate(value) {
      return value ? String(value).replace('T', ' ').slice(0, 16) : '—'
    }
  }
}
</script>

<style>
.page { height: 100vh; display: flex; flex-direction: column; color: #dce1ed; background: #0f0f23; }
.content { flex: 1; min-height: 0; padding: 24rpx; box-sizing: border-box; }.state { padding: 180rpx 24rpx; color: #717b91; font-size: 25rpx; text-align: center; }
.summary-card { display: flex; align-items: center; justify-content: space-between; padding: 24rpx; border: 1rpx solid #292945; border-radius: 14rpx; background: #18182d; }.summary-title, .summary-sub, .notice, .metric-value, .metric-label, .invite-time { display: block; }.summary-title { color: #f2f3f8; font-size: 30rpx; font-weight: 700; }.summary-sub { margin-top: 8rpx; color: #737d92; font-size: 21rpx; }.summary-role { color: #68a8e9; font-size: 22rpx; }
.notice { margin: 18rpx 6rpx 0; color: #626d82; font-size: 20rpx; line-height: 1.6; }.invite-list { margin-top: 18rpx; }.invite-card { margin-bottom: 16rpx; padding: 24rpx; border: 1rpx solid #292945; border-radius: 14rpx; background: #18182d; }.invite-head { display: flex; align-items: center; justify-content: space-between; }.invite-title { color: #e7e9f0; font-size: 27rpx; font-weight: 600; }
.status { padding: 8rpx 12rpx; border-radius: 8rpx; font-size: 20rpx; }.status-active { color: #62b49e; background: #203432; }.status-revoked { color: #bc7a80; background: #35252e; }.status-expired { color: #8a91a0; background: #282a38; }
.metric-row { display: flex; margin-top: 20rpx; padding: 18rpx 0; border-top: 1rpx solid #292945; border-bottom: 1rpx solid #292945; }.metric { min-width: 150rpx; }.grow { flex: 1; min-width: 0; }.metric-value { color: #dfe3ec; font-size: 27rpx; font-weight: 600; }.metric-value.small { font-size: 23rpx; }.metric-label { margin-top: 5rpx; color: #6d778d; font-size: 19rpx; }.invite-time { margin-top: 12rpx; color: #788197; font-size: 20rpx; }
.revoke-btn { width: 100%; margin: 20rpx 0 0; border: 1rpx solid rgba(184, 95, 105, .34); border-radius: 10rpx; color: #c9858b; background: rgba(120, 45, 54, .14); font-size: 22rpx; line-height: 2.35; }.revoke-btn::after { border: 0; }.revoke-btn[disabled] { opacity: .55; }.bottom-space { height: 80rpx; }
</style>
