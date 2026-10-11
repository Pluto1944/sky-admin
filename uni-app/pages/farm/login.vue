<template>
  <view class="farm-login-page">
    <view class="login-hero">
      <view class="login-mark">互</view>
      <text class="login-title">互刷联盟系统</text>
      <text class="login-subtitle">使用管理员分配的独立账号登录</text>
    </view>

    <view class="login-card">
      <view class="field">
        <text class="field-label">账号</text>
        <input v-model="username" class="field-input" placeholder="请输入登录邮箱" maxlength="254" />
      </view>
      <view class="field">
        <text class="field-label">密码</text>
        <input v-model="password" class="field-input" password placeholder="请输入密码" maxlength="128" @confirm="submit" />
      </view>
      <button class="login-button" :loading="loading" :disabled="loading" @tap="submit">登录</button>
      <text class="login-help">没有公开注册入口 · 忘记密码请联系创建者</text>
    </view>
  </view>
</template>

<script>
import { farmLogin, getFarmMe } from '@/utils/api.js'

export default {
  data() {
    return { username: '', password: '', loading: false }
  },
  onShow() {
    if (!uni.getStorageSync('farm_token')) return
    getFarmMe().then(() => {
      uni.redirectTo({ url: '/pages/farm/home' })
    }).catch(() => {})
  },
  methods: {
    async submit() {
      if (this.loading) return
      const username = this.username.trim()
      if (!username || !this.password) {
        uni.showToast({ title: '请输入邮箱和密码', icon: 'none' })
        return
      }
      this.loading = true
      try {
        const result = await farmLogin(username, this.password)
        uni.setStorageSync('farm_token', result.token)
        uni.setStorageSync('farm_account', result.account)
        this.password = ''
        uni.redirectTo({ url: '/pages/farm/home' })
      } catch (e) {
        uni.showModal({ title: '登录失败', content: e.message || '请稍后重试', showCancel: false })
      } finally {
        this.loading = false
      }
    }
  }
}
</script>

<style>
.farm-login-page { min-height: 100vh; padding: 96rpx 36rpx; box-sizing: border-box; background: #0f0f23; color: #f2f4fb; }
.login-hero { display: flex; flex-direction: column; align-items: center; margin-bottom: 52rpx; }
.login-mark { display: flex; width: 112rpx; height: 112rpx; align-items: center; justify-content: center; margin-bottom: 28rpx; border: 1rpx solid #426895; border-radius: 28rpx; background: linear-gradient(145deg, #397fc0, #24527f); box-shadow: 0 18rpx 48rpx rgba(29,91,148,.28); font-size: 52rpx; font-weight: 700; }
.login-title { font-size: 42rpx; font-weight: 700; }
.login-subtitle { margin-top: 14rpx; color: #7f8aa4; font-size: 25rpx; }
.login-card { padding: 36rpx 30rpx 30rpx; border: 1rpx solid #2b3153; border-radius: 22rpx; background: #191a32; }
.field { margin-bottom: 28rpx; }
.field-label { display: block; margin-bottom: 12rpx; color: #aeb7cc; font-size: 25rpx; }
.field-input { height: 84rpx; padding: 0 24rpx; border: 1rpx solid #30375e; border-radius: 14rpx; background: #121327; color: #f2f4fb; font-size: 28rpx; }
.login-button { display: flex; height: 86rpx; align-items: center; justify-content: center; margin-top: 10rpx; border-radius: 14rpx; background: #397fc0; color: #fff; font-size: 29rpx; font-weight: 600; }
.login-button::after { border: 0; }
.login-button[disabled] { opacity: .65; }
.login-help { display: block; margin-top: 24rpx; color: #69728b; font-size: 22rpx; text-align: center; }
</style>
