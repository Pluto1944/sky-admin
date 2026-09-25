<template>
  <view class="page">
    <TopBar title="成员详情" :showBack="true" />
    <view class="card">
      <text class="icon">👤</text>
      <text class="name">{{ member.account_name || '成员' }}</text>
      <text class="line">玩家标签：{{ member.player_tag || '暂无' }}</text>
      <text class="line">所属部落：{{ member.clan_tag || '暂无' }}</text>
      <text class="line">大本等级：{{ member.town_hall_level || '暂无' }}</text>
      <text class="line">部落职位：{{ member.clan_role || '暂无' }}</text>
    </view>
  </view>
</template>

<script>
import TopBar from '@/components/TopBar.vue'
export default {
  components: { TopBar },
  data() { return { member: {} } },
  onLoad(options) {
    this.member = { account_name: options && options.name, player_tag: options && options.tag, clan_tag: options && options.clan, town_hall_level: options && options.th, clan_role: options && options.role }
  }
}
</script>

<style scoped>
.page { min-height: 100vh; background: #0f0f23; }
.card { margin: 40rpx 30rpx; padding: 44rpx 34rpx; border-radius: 20rpx; background: #1a1a3e; display: flex; flex-direction: column; }
.icon { font-size: 80rpx; text-align: center; margin-bottom: 24rpx; }
.name { color: #fff; font-size: 38rpx; font-weight: 600; text-align: center; margin-bottom: 34rpx; }
.line { color: #b9c0cf; font-size: 28rpx; padding: 18rpx 0; border-bottom: 1rpx solid #2a2a4a; }
</style>
