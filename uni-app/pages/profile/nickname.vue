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
          @focus="handleNicknameFocus"
          @input="handleNicknameInput"
          @blur="handleNicknameBlur"
          @nicknamereview="handleNicknameReview"
          @confirm="save"
        />
        <text class="field-tip">
          {{ nicknameFieldTip }}
        </text>
      </view>

      <view v-if="autoSaving" class="save-status">
        <text>正在自动保存…</text>
      </view>
      <button
        v-else
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
      pendingNickname: '',
      nicknameReviewPassed: false,
      nicknameInputStartedEmpty: true,
      nicknameInputEvents: 0,
      privacyAuthorizationPending: false,
      privacyAuthorizationDenied: false,
      autoSaving: false,
      autoBlurTimer: null,
      autoSaveTimer: null,
      nicknameFocusTimer: null
    }
  },
  computed: {
    nicknameFieldTip() {
      if (this.privacyAuthorizationPending) {
        return '正在确认微信隐私授权…'
      }
      if (this.privacyAuthorizationDenied) {
        return '未授权微信昵称，可继续手动输入或暂不设置。'
      }
      return this.editing
        ? '可以选择微信昵称，也可以自行填写。'
        : '未出现微信昵称时，可点击输入框手动填写。'
    }
  },
  watch: {
    nickname(value, previousValue) {
      const nickname = typeof value === 'string' ? value.trim() : ''
      const previousNickname = typeof previousValue === 'string' ? previousValue.trim() : ''
      if (this.editing || this.saving || previousNickname || nickname.length <= 1) return

      this.pendingNickname = nickname
      this.nicknameDirty = true
      this.queueAutoSave(250)
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
    this.requireNicknamePrivacyAuthorization()
  },
  onUnload() {
    if (this.autoBlurTimer) {
      clearTimeout(this.autoBlurTimer)
    }
    if (this.autoSaveTimer) {
      clearTimeout(this.autoSaveTimer)
    }
    if (this.nicknameFocusTimer) {
      clearTimeout(this.nicknameFocusTimer)
    }
  },
  methods: {
    focusNicknameAfterPrivacyAuthorization() {
      if (this.editing || this.nickname) return
      if (this.nicknameFocusTimer) {
        clearTimeout(this.nicknameFocusTimer)
      }
      this.nicknameFocusTimer = setTimeout(() => {
        this.nicknameFocusTimer = null
        this.nicknameFocused = true
      }, 180)
    },
    requireNicknamePrivacyAuthorization() {
      // input type="nickname" 在用户尚未完成微信侧隐私授权时会直接降级为普通文本框，
      // 且不会触发 onNeedPrivacyAuthorization。先模拟一次隐私接口调用，让微信官方
      // 弹窗完成授权同步；拒绝或旧基础库不支持时仍允许手动填写昵称。
      const wechat = typeof wx !== 'undefined' ? wx : null
      if (!wechat || typeof wechat.requirePrivacyAuthorize !== 'function') {
        this.focusNicknameAfterPrivacyAuthorization()
        return
      }

      this.privacyAuthorizationPending = true
      wechat.requirePrivacyAuthorize({
        success: () => {
          this.privacyAuthorizationPending = false
          this.privacyAuthorizationDenied = false
          this.focusNicknameAfterPrivacyAuthorization()
        },
        fail: () => {
          this.privacyAuthorizationPending = false
          this.privacyAuthorizationDenied = true
          this.nicknameFocused = false
          uni.showToast({ title: '可手动输入昵称或暂不设置', icon: 'none' })
        }
      })
    },
    handleNicknameFocus() {
      if (this.editing) return
      this.pendingNickname = ''
      this.nicknameReviewPassed = false
      this.nicknameInputStartedEmpty = !this.nickname.trim()
      this.nicknameInputEvents = 0
    },
    handleNicknameInput(event) {
      const rawNickname = event && event.detail ? event.detail.value : this.nickname
      this.nicknameInputEvents += 1
      const isFirstInputFromEmpty = this.nicknameInputStartedEmpty && this.nicknameInputEvents === 1
      this.nickname = rawNickname
      this.nicknameDirty = true

      // 微信推荐昵称会从空值一次性填入完整昵称，但仍保持输入框焦点。
      // 主动收起键盘以触发 blur，后续由 nicknamereview 审核通过后保存。
      if (
        !this.editing &&
        isFirstInputFromEmpty &&
        rawNickname.trim().length > 1
      ) {
        this.nicknameInputStartedEmpty = false
        this.pendingNickname = rawNickname.trim()
        // 开发者工具的昵称建议不会稳定触发 blur / nicknamereview。
        // 保留微信审核事件为主路径，同时为一次性填入的完整昵称提供自动保存兜底。
        this.queueAutoSave(450)
        if (this.autoBlurTimer) {
          clearTimeout(this.autoBlurTimer)
        }
        this.autoBlurTimer = setTimeout(() => {
          this.autoBlurTimer = null
          this.nicknameFocused = false
          if (uni.hideKeyboard) {
            uni.hideKeyboard()
          }
        }, 80)
      }
    },
    handleNicknameBlur(event) {
      if (this.editing) return

      if (this.autoBlurTimer) {
        clearTimeout(this.autoBlurTimer)
        this.autoBlurTimer = null
      }

      const detail = event && event.detail ? event.detail : {}
      const rawNickname = typeof detail.value === 'string' ? detail.value : this.nickname
      const nickname = rawNickname.trim()
      this.nickname = rawNickname
      this.pendingNickname = nickname
      this.nicknameDirty = Boolean(nickname)

      if (nickname && (!this.nicknameReviewSupported || this.nicknameReviewPassed)) {
        this.queueAutoSave()
      }
    },
    handleNicknameReview(event) {
      if (this.editing) return
      const detail = event && event.detail ? event.detail : {}
      if (detail.pass) {
        this.nicknameReviewPassed = true
        const nickname = (this.pendingNickname || this.nickname).trim()
        if (nickname) {
          this.nickname = nickname
          this.nicknameDirty = true
          this.queueAutoSave()
        }
      } else if (!detail.timeout) {
        if (this.autoSaveTimer) {
          clearTimeout(this.autoSaveTimer)
          this.autoSaveTimer = null
        }
        this.autoSaving = false
        this.nickname = ''
        this.pendingNickname = ''
        this.nicknameDirty = false
        this.nicknameReviewPassed = false
        uni.showToast({ title: '该昵称未通过微信校验', icon: 'none' })
      }
    },
    queueAutoSave(delay = 120) {
      if (this.saving || !this.nicknameDirty || !this.nickname.trim()) return
      this.autoSaving = true
      if (this.autoSaveTimer) {
        clearTimeout(this.autoSaveTimer)
      }
      this.autoSaveTimer = setTimeout(() => {
        this.autoSaveTimer = null
        this.save()
      }, delay)
    },
    save() {
      if (this.saving) return
      if (this.autoSaveTimer) {
        clearTimeout(this.autoSaveTimer)
        this.autoSaveTimer = null
      }
      const nickname = this.nickname.trim()
      if (!nickname) {
        this.autoSaving = false
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
          this.autoSaving = false
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

.save-status {
  height: 84rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #77baff;
  background: #182947;
  border: 1rpx solid #315887;
  border-radius: 14rpx;
  font-size: 26rpx;
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
