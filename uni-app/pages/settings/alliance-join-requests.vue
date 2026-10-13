<template>
  <view class="page">
    <TopBar title="加入申请" :show-back="true" back-fallback="/pages/settings/alliance-management" />
    <scroll-view scroll-y class="content">
      <view v-if="loading" class="state">正在加载...</view>
      <template v-else-if="alliance">
        <view class="summary-card">
          <view>
            <text class="summary-title">{{ alliance.name }}</text>
            <text class="summary-sub">待处理 {{ pendingCount }} 条 · 全部 {{ requests.length }} 条</text>
          </view>
          <text class="summary-role">{{ alliance.role_label || roleLabel(alliance.role) }}</text>
        </view>

        <view v-if="requests.length" class="request-list">
          <view v-for="request in requests" :key="request.id" class="request-card">
            <view class="request-head">
              <view class="grow">
                <text class="request-name">{{ request.display_name }}</text>
                <text class="request-meta">{{ request.player_tag || '未绑定游戏账号' }}</text>
              </view>
              <text :class="['status', 'status-' + request.status]">{{ requestStatusLabel(request.status) }}</text>
            </view>
            <text class="request-time">申请于 {{ shortDate(request.created_at) }}</text>
            <text v-if="request.status !== 'pending'" class="request-time">处理于 {{ shortDate(request.updated_at) }}</text>
            <view v-if="request.status === 'pending'" class="request-actions">
              <button class="action reject" :disabled="Boolean(reviewingId)" @tap="reviewRequest(request, 'reject')">拒绝</button>
              <button class="action approve" :loading="reviewingId === request.id" :disabled="Boolean(reviewingId)" @tap="reviewRequest(request, 'approve')">同意加入</button>
            </view>
          </view>
        </view>
        <view v-else class="state">暂无申请记录</view>
      </template>
      <view v-else class="state">请先创建或加入联盟</view>
      <view class="bottom-space"></view>
    </scroll-view>
  </view>
</template>

<script>
import TopBar from '@/components/TopBar.vue'
import { getAllianceJoinRequests, reviewAllianceJoinRequest } from '@/utils/api.js'
import { getCurrentAlliance, loadAllianceContext } from '@/utils/alliance.js'

export default {
  components: { TopBar },
  data() {
    return {
      loading: true,
      alliance: null,
      requests: [],
      reviewingId: 0
    }
  },
  computed: {
    pendingCount() {
      return this.requests.filter(item => item.status === 'pending').length
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
        const result = await getAllianceJoinRequests(this.alliance.id)
        this.requests = result.requests || []
      } catch (err) {
        uni.showToast({ title: err.message || '加载失败', icon: 'none' })
      } finally {
        this.loading = false
      }
    },
    reviewRequest(request, action) {
      if (!request || request.status !== 'pending' || this.reviewingId) return
      const approving = action === 'approve'
      uni.showModal({
        title: approving ? '同意加入' : '拒绝申请',
        content: `${approving ? '确认同意' : '确认拒绝'}${request.display_name}的加入申请？`,
        confirmColor: approving ? '#4d91d2' : '#c9797f',
        success: async result => {
          if (!result.confirm) return
          this.reviewingId = request.id
          try {
            await reviewAllianceJoinRequest(this.alliance.id, request.id, action)
            await this.loadData()
            uni.showToast({ title: approving ? '已同意' : '已拒绝', icon: 'success' })
          } catch (err) {
            uni.showToast({ title: err.message || '处理失败', icon: 'none' })
          } finally {
            this.reviewingId = 0
          }
        }
      })
    },
    requestStatusLabel(value) {
      return ({ pending: '待处理', approved: '已同意', rejected: '已拒绝' }[value] || value)
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
.content { flex: 1; min-height: 0; padding: 24rpx; box-sizing: border-box; }
.state { padding: 180rpx 24rpx; color: #717b91; font-size: 25rpx; text-align: center; }
.summary-card { display: flex; align-items: center; justify-content: space-between; padding: 24rpx; border: 1rpx solid #292945; border-radius: 14rpx; background: #18182d; }
.summary-title, .summary-sub, .request-name, .request-meta, .request-time { display: block; }
.summary-title { color: #f2f3f8; font-size: 30rpx; font-weight: 700; }.summary-sub { margin-top: 8rpx; color: #737d92; font-size: 21rpx; }.summary-role { color: #68a8e9; font-size: 22rpx; }
.request-list { margin-top: 20rpx; }.request-card { margin-bottom: 16rpx; padding: 24rpx; border: 1rpx solid #292945; border-radius: 14rpx; background: #18182d; }
.request-head { display: flex; align-items: center; }.grow { flex: 1; min-width: 0; }.request-name { overflow: hidden; color: #e7e9f0; font-size: 27rpx; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }.request-meta { margin-top: 7rpx; color: #68738a; font-size: 20rpx; }
.status { flex-shrink: 0; margin-left: 16rpx; padding: 8rpx 12rpx; border-radius: 8rpx; font-size: 20rpx; }.status-pending { color: #d2a666; background: #302b35; }.status-approved { color: #62b49e; background: #203432; }.status-rejected { color: #bc7a80; background: #35252e; }
.request-time { margin-top: 12rpx; color: #788197; font-size: 20rpx; }.request-actions { display: flex; gap: 18rpx; margin-top: 20rpx; padding-top: 18rpx; border-top: 1rpx solid #292945; }.action { flex: 1; margin: 0; border: 1rpx solid transparent; border-radius: 10rpx; font-size: 23rpx; line-height: 2.45; }.action::after { border: 0; }.action.reject { color: #c88a90; background: rgba(120, 45, 54, .15); border-color: rgba(184, 95, 105, .3); }.action.approve { color: #8dc1f3; background: #202b42; border-color: #324966; }.action[disabled] { opacity: .55; }
.bottom-space { height: 80rpx; }
</style>
