<template>
  <view class="page">
    <TopBar title="管理联盟列表" :show-back="true" back-fallback="/pages/clan/clan" />
    <scroll-view scroll-y class="content">
      <view v-if="loading" class="empty">正在加载...</view>
      <template v-else>
        <view class="section-title">我的联盟</view>
        <view v-if="!alliances.length" class="empty-card">暂无已加入联盟</view>
        <view v-for="item in alliances" :key="item.id" class="card">
          <view class="grow">
            <text class="name">{{ item.name }}</text>
            <text class="sub">{{ roleLabel(item.role) }} · {{ item.clan_count || 0 }} 个部落</text>
          </view>
          <button class="action danger" @tap="removeMembership(item)">{{ item.role === 'leader' ? '删除联盟' : '退出联盟' }}</button>
        </view>

        <view class="section-title">浏览过的联盟</view>
        <view v-if="!browsed.length" class="empty-card">暂无浏览历史</view>
        <view v-for="item in browsed" :key="item.id" class="card">
          <view class="grow">
            <text class="name">{{ item.name }}</text>
            <text class="sub">最近访问 {{ shortTime(item.last_visited_at) }}</text>
          </view>
          <button class="action" @tap="removeHistory(item)">删除记录</button>
        </view>
      </template>
      <view class="bottom-space"></view>
    </scroll-view>
  </view>
</template>

<script>
import TopBar from '@/components/TopBar.vue'
import { archiveFreeAlliance, deleteAllianceHistory, getMyAlliances, leaveAlliance } from '@/utils/api.js'
import { loadAllianceContext } from '@/utils/alliance.js'

export default {
  components: { TopBar },
  data() {
    return { loading: false, alliances: [], browsed: [] }
  },
  onShow() { this.load() },
  methods: {
    async load() {
      this.loading = true
      try {
        const result = await getMyAlliances()
        this.alliances = result.alliances || []
        this.browsed = result.browsed_alliances || []
      } catch (e) {
        uni.showToast({ title: e.message || '加载失败', icon: 'none' })
      } finally {
        this.loading = false
      }
    },
    removeMembership(item) {
      if (item.role === 'leader') {
        uni.showModal({
          title: '删除联盟',
          content: `请输入联盟名称“${item.name}”确认删除`,
          editable: true,
          placeholderText: '联盟名称',
          confirmColor: '#c9797f',
          success: async result => {
            if (!result.confirm) return
            try {
              await archiveFreeAlliance(item.id, result.content)
              await loadAllianceContext(null, true)
              await this.load()
              uni.showToast({ title: '联盟已删除', icon: 'success' })
            } catch (e) {
              uni.showToast({ title: e.message || '删除失败', icon: 'none' })
            }
          }
        })
        return
      }
      uni.showModal({
        title: '退出联盟',
        content: `确定退出“${item.name}”？退出后不会自动保留为浏览记录。`,
        confirmColor: '#c9797f',
        success: async result => {
          if (!result.confirm) return
          try {
            await leaveAlliance(item.id)
            await loadAllianceContext(null, true)
            await this.load()
            uni.showToast({ title: '已退出联盟', icon: 'success' })
          } catch (e) {
            uni.showToast({ title: e.message || '退出失败', icon: 'none' })
          }
        }
      })
    },
    removeHistory(item) {
      uni.showModal({
        title: '删除浏览记录',
        content: `确定从列表中删除“${item.name}”？`,
        success: async result => {
          if (!result.confirm) return
          try {
            await deleteAllianceHistory(item.id)
            await loadAllianceContext(null, true)
            await this.load()
          } catch (e) {
            uni.showToast({ title: e.message || '删除失败', icon: 'none' })
          }
        }
      })
    },
    roleLabel(role) { return ({ leader: '首领', admin: '管理', member: '成员' }[role] || '成员') },
    shortTime(value) { return value ? String(value).replace('T', ' ').slice(0, 16) : '—' }
  }
}
</script>

<style>
.page { height: 100vh; display: flex; flex-direction: column; color: #dce1ed; background: #0f0f23; }
.content { flex: 1; min-height: 0; padding: 24rpx; box-sizing: border-box; }
.section-title { margin: 26rpx 8rpx 14rpx; color: #7f8aa2; font-size: 23rpx; }
.card { display: flex; align-items: center; margin-bottom: 14rpx; padding: 22rpx; border: 1rpx solid #292945; border-radius: 14rpx; background: #18182d; }
.grow { flex: 1; min-width: 0; }.name { display: block; overflow: hidden; color: #e8ebf3; font-size: 27rpx; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.sub { display: block; margin-top: 8rpx; color: #778198; font-size: 21rpx; }.action { flex-shrink: 0; margin-left: 18rpx; padding: 0 18rpx; border: 0; border-radius: 9rpx; color: #7eb8f6; font-size: 22rpx; line-height: 2.35; background: #202b42; }
.action::after { border: 0; }.action.danger { color: #c9797f; }.empty, .empty-card { color: #70798f; font-size: 24rpx; text-align: center; }.empty { padding: 100rpx 0; }.empty-card { padding: 42rpx 20rpx; border: 1rpx solid #25253f; border-radius: 14rpx; background: #17172b; }.bottom-space { height: 80rpx; }
</style>
