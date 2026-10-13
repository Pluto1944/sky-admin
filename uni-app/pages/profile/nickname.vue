<template>
  <view class="page">
    <view class="identity-card">
      <view class="identity-mark">名</view>
      <text class="title">{{ editing ? '修改昵称' : '选择微信昵称' }}</text>
      <text class="description">
        {{ editing ? '昵称会展示给联盟首领和管理员，用于识别联盟成员。' : '点击微信提供的昵称即可完成，选择后会自动保存。' }}
      </text>

      <view class="field">
        <text class="label">昵称</text>
        <input
          v-model="nickname"
          class="nickname-input"
          type="nickname"
          maxlength="20"
          confirm-type="done"
          :focus="nicknameFocused"
          placeholder="点击选择微信昵称或输入新昵称"
          placeholder-style="color:#59637a"
          @input="handleNicknameInput"
          @blur="handleNicknameBlur"
          @nicknamereview="handleNicknameReview"
          @confirm="save"
        />
        <text class="field-tip">
          {{ editing ? '可以选择微信昵称，也可以自行填写。' : '未出现微信昵称时，可点击输入框手动填写。' }}
        </text>
      </view>

      <button
        class="primary"
        :loading="saving"
        :disabled="saving || !nickname.trim()"
        @tap="save"
      >{{ editing ? '保存昵称' : '手动保存' }}</button>
      <button v-if="!editing" class="secondary" :disabled="saving" @tap="skip">暂不设置</button>
    </view>

    <view class="privacy-tip">
      <text>昵称由你主动选择，仅用于本小程序内展示。登录和权限判断仍使用不可见的账号标识。</text>
    </view>
  </view>
</template>

<script>
import { updateWechatProfile } from '@/utils/api.js'

export default {
  data() {
    return {
      nickname: '',
      saving: false,
      editing: false,
      next: 'settings',
      nicknameFocused: false,
      nicknameDirty: false,
      nicknameReviewSupported: false,
      autoSaveTimer: null
    }
  },
  onLoad(options) {
    if (!uni.getStorageSync('token')) {
      uni.switchTab({ url: '/pages/settings/settings' })
      return
    }
    this.editing = options && options.mode === 'edit'
    this.next = options && options.next === 'bind' ? 'bind' : 'settings'
    const current = getApp().globalData.userInfo
    this.nickname = current && current.nickname ? current.nickname : ''
    try {
      this.nicknameReviewSupported = Boolean(
        uni.canIUse && uni.canIUse('input.bindnicknamereview')
      )
    } catch (err) {
      this.nicknameReviewSupported = false
    }
  },
  onReady() {
    if (!this.editing && !this.nickname) {
      setTimeout(() => {
        this.nicknameFocused = true
      }, 180)
    }
  },
  onUnload() {
    if (this.autoSaveTimer) {
      clearTimeout(this.autoSaveTimer)
    }
  },
  methods: {
    handleNicknameInput(event) {
      this.nickname = event && event.detail ? event.detail.value : this.nickname
      this.nicknameDirty = true
    },
    handleNicknameBlur() {
      if (!this.editing && !this.nicknameReviewSupported) {
        this.queueAutoSave()
      }
    },
    handleNicknameReview(event) {
      if (this.editing || !this.nicknameDirty) return
      const detail = event && event.detail ? event.detail : {}
      if (detail.pass) {
        this.queueAutoSave()
      } else if (!detail.timeout) {
        this.nickname = ''
        this.nicknameDirty = false
        uni.showToast({ title: '该昵称未通过微信校验', icon: 'none' })
      }
    },
    queueAutoSave() {
      if (this.saving || !this.nicknameDirty || !this.nickname.trim()) return
      if (this.autoSaveTimer) {
        clearTimeout(this.autoSaveTimer)
      }
      this.autoSaveTimer = setTimeout(() => {
        this.autoSaveTimer = null
        this.save()
      }, 120)
    },
    save() {
      const nickname = this.nickname.trim()
      if (!nickname) {
        uni.showToast({ title: '请输入昵称', icon: 'none' })
        return
      }
      this.saving = true
      updateWechatProfile(nickname)
        .then((res) => {
          getApp().globalData.userInfo = res.user
          uni.showToast({ title: '昵称已保存', icon: 'success' })
          setTimeout(() => this.finish(), 350)
        })
        .catch((err) => {
          this.saving = false
          uni.showModal({
            title: '保存失败',
            content: err.message || '请稍后重试',
            showCancel: false
          })
        })
    },
    skip() {
      this.finish()
    },
    finish() {
      if (this.editing) {
        uni.navigateBack()
      } else if (this.next === 'bind') {
        uni.redirectTo({ url: '/pages/bind/bind' })
      } else {
        uni.switchTab({ url: '/pages/settings/settings' })
      }
    }
  }
}
</script>

<style>
.page {
  min-height: 100vh;
  padding: 72rpx 34rpx 80rpx;
  box-sizing: border-box;
  background: linear-gradient(180deg, #15162c 0%, #0f0f23 55%);
}

.identity-card {
  padding: 48rpx 34rpx 34rpx;
  background: linear-gradient(145deg, #1c1e3a, #17182f);
  border: 1rpx solid #303557;
  border-radius: 24rpx;
  box-shadow: 0 18rpx 50rpx rgba(0, 0, 0, 0.2);
}

.identity-mark {
  width: 88rpx;
  height: 88rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 28rpx;
  color: #dcebff;
  background: linear-gradient(135deg, #438bd0, #2f69aa);
  border-radius: 50%;
  font-size: 38rpx;
  font-weight: 700;
}

.title,
.description,
.label,
.field-tip {
  display: block;
}

.title {
  color: #f5f7fc;
  font-size: 38rpx;
  font-weight: 700;
  text-align: center;
}

.description {
  margin: 16rpx 12rpx 42rpx;
  color: #8e98ad;
  font-size: 24rpx;
  line-height: 1.7;
  text-align: center;
}

.field {
  margin-bottom: 34rpx;
}

.label {
  margin-bottom: 14rpx;
  color: #cbd3e1;
  font-size: 25rpx;
  font-weight: 600;
}

.nickname-input {
  width: 100%;
  height: 92rpx;
  padding: 0 24rpx;
  box-sizing: border-box;
  color: #f3f6fb;
  background: #101126;
  border: 1rpx solid #353a5d;
  border-radius: 14rpx;
  font-size: 29rpx;
}

.field-tip {
  margin-top: 13rpx;
  color: #68748a;
  font-size: 21rpx;
  line-height: 1.5;
}

.primary,
.secondary {
  width: 100%;
  height: 84rpx;
  margin: 0;
  border: 0;
  border-radius: 14rpx;
  font-size: 27rpx;
  line-height: 84rpx;
}

.primary {
  color: #fff;
  background: linear-gradient(135deg, #438bd0, #3474b7);
  font-weight: 600;
}

.primary[disabled] {
  color: #77839a;
  background: #252942;
}

.secondary {
  margin-top: 18rpx;
  color: #8e99ae;
  background: transparent;
  border: 1rpx solid #333852;
}

.primary::after,
.secondary::after {
  border: 0;
}

.privacy-tip {
  padding: 24rpx 18rpx;
  color: #626d82;
  font-size: 21rpx;
  line-height: 1.7;
  text-align: center;
}
</style>
