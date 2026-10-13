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
        <view class="section-title">多联盟认证</view>
        <view class="card">
          <text class="sub">允许保留；如需调整，请进入对应联盟逐个撤销认证。</text>
          <view v-for="item in verificationConflicts" :key="item.clan_tag" class="queue-row">
            <text>{{ item.clan_tag }}</text><text>{{ item.alliance_names }}</text>
          </view>
        </view>
      </template>

      <view class="section-title">创建联盟</view>
      <view class="card">
        <text class="sub">平台入口不受个人“只能创建一个联盟”的限制；新联盟默认使用免费套餐。</text>
        <input v-model="platformAllianceName" class="search-input standalone-input" maxlength="30" placeholder="联盟名称" placeholder-style="color:#59637a" />
        <button class="primary-btn" :loading="createBusy" :disabled="createBusy || !platformAllianceName.trim()" @tap="createAlliance">创建联盟</button>
      </view>

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
        <view class="card action-card">
          <text class="name">联盟成员与权限</text>
          <text class="sub">可以通过 OpenID 添加成员；把其他成员设为首领时会自动完成首领移交。</text>
          <view v-for="member in detail.members" :key="member.id" class="member-row">
            <view class="grow">
              <text class="name small">{{ member.nickname || member.account_name || ('微信用户' + member.id) }}</text>
              <text class="openid">{{ member.openid }}</text>
              <text v-if="member.status !== 'active'" class="sub">{{ memberStatusLabel(member.status) }}</text>
            </view>
            <picker
              v-if="member.status === 'active'"
              :range="memberRoles"
              range-key="label"
              :value="memberRoleIndex(member.role)"
              @change="changePlatformMemberRole(member, $event)"
            >
              <text class="category">{{ memberRoleLabel(member.role) }}⌄</text>
            </picker>
            <text v-if="member.status === 'active' && member.role !== 'leader'" class="remove" @tap="confirmPlatformMemberRemove(member)">移除</text>
          </view>
          <view class="platform-add">
            <input v-model="newMemberOpenid" class="search-input" maxlength="200" placeholder="用户 OpenID" placeholder-style="color:#59637a" />
            <picker :range="memberRoles" range-key="label" :value="newMemberRoleIndex" @change="newMemberRoleIndex = Number($event.detail.value) || 0">
              <view class="platform-picker">角色：{{ memberRoles[newMemberRoleIndex].label }}⌄</view>
            </picker>
            <button class="primary-btn" :loading="memberBusy" :disabled="memberBusy || !newMemberOpenid.trim()" @tap="addPlatformMember">添加成员</button>
          </view>
        </view>

        <view class="card action-card">
          <view class="title-row">
            <view class="grow">
              <text class="name">管理部落</text>
              <text class="sub">已添加 {{ platformActiveClans.length }} 个 · 超级管理员不受套餐数量限制</text>
            </view>
          </view>
          <view v-for="(clan, index) in platformActiveClans" :key="clan.clan_tag" class="clan-row">
            <view class="platform-order">
              <text :class="['order-btn', { disabled: index === 0 }]" @tap="movePlatformClan(index, -1)">↑</text>
              <text :class="['order-btn', { disabled: index === platformActiveClans.length - 1 }]" @tap="movePlatformClan(index, 1)">↓</text>
            </view>
            <view class="grow">
              <text class="name small">{{ clan.clan_name || clan.clan_tag }}</text>
              <text class="sub">{{ clan.clan_tag }} · {{ verificationLabel(clan.verification_status) }}</text>
            </view>
            <picker :range="categories" range-key="label" :value="categoryIndex(clan.category)" @change="changePlatformCategory(clan, $event)">
              <text class="category">{{ categoryLabel(clan.category) }}⌄</text>
            </picker>
            <text class="edit-name" @tap="editPlatformClanName(clan)">别名</text>
            <text class="remove" @tap="confirmPlatformRemove(clan)">移除</text>
          </view>
          <view class="platform-add">
            <input v-model="newClanTag" class="search-input" maxlength="15" placeholder="部落标签，例如 #2QQ" placeholder-style="color:#59637a" />
            <picker :range="categories" range-key="label" :value="newCategoryIndex" @change="newCategoryIndex = Number($event.detail.value) || 0">
              <view class="platform-picker">部落标签：{{ categories[newCategoryIndex].label }}⌄</view>
            </picker>
            <button class="primary-btn" :loading="clanBusy" :disabled="clanBusy || !newClanTag.trim()" @tap="addPlatformClan">添加部落</button>
          </view>
        </view>

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
          <text class="sub">当前 {{ detail.alliance.plan_code }} · {{ grantStatusLabel(detail.alliance.grant_status) }}<text v-if="detail.alliance.expires_at"> · {{ shortDate(detail.alliance.expires_at) }}</text></text>
          <button class="primary-btn" @tap="grantPaid">开通付费版365天</button>
          <button class="secondary-btn" @tap="grantFree">设为免费版</button>
        </view>

        <view class="card action-card">
          <text class="name">联盟状态</text>
          <text class="sub">当前：{{ statusLabel(detail.alliance.status) }}</text>
          <button v-if="detail.alliance.status === 'active'" class="secondary-btn danger-text" @tap="changeStatus('suspended')">停用联盟</button>
          <template v-else-if="detail.alliance.status === 'suspended'">
            <button class="primary-btn" @tap="changeStatus('active')">恢复联盟</button>
            <button class="delete-btn" @tap="deleteAlliance">删除已停用联盟</button>
            <text class="sub danger-tip">删除后不再显示在联盟列表中；历史事实和审计仍会保留。</text>
          </template>
          <text v-else class="sub">该联盟已经删除，不能恢复。</text>
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
  addPlatformAllianceMember,
  addPlatformManagedClan,
  createPlatformAlliance,
  deletePlatformAlliance,
  getPlatformAlliance,
  getPlatformAlliances,
  getPlatformManagedClans,
  removePlatformManagedClan,
  removePlatformAllianceMember,
  reorderPlatformManagedClans,
  savePlatformAllianceStatus,
  savePlatformFreeRegistration,
  savePlatformPlan,
  savePlatformVerification,
  updatePlatformAllianceMemberRole,
  updatePlatformManagedClan
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
      detail: null,
      platformManagement: { clans: [], unlimited: true, can_manage: false, can_add: false },
      clanBusy: false,
      newClanTag: '',
      platformAllianceName: '',
      createBusy: false,
      memberBusy: false,
      newMemberOpenid: '',
      newMemberRoleIndex: 0,
      memberRoles: [
        { key: 'member', label: '成员' },
        { key: 'admin', label: '管理员' },
        { key: 'leader', label: '首领' }
      ],
      newCategoryIndex: 0,
      categories: [
        { key: 'normal', label: '实战' },
        { key: 'combat', label: '战营' },
        { key: 'farm', label: '互刷' },
        { key: 'flat', label: '偷矿' }
      ]
    }
  },
  computed: {
    platformActiveClans() {
      return (this.platformManagement.clans || []).filter(item => item.status === 'active')
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
        this.verificationConflicts = result.multi_alliance_verifications || result.verification_conflicts || []
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
    async createAlliance() {
      if (this.createBusy || !this.platformAllianceName.trim()) return
      this.createBusy = true
      try {
        const created = await createPlatformAlliance(this.platformAllianceName.trim())
        this.platformAllianceName = ''
        await this.loadDashboard()
        await this.reloadDetail(created.alliance_id)
        uni.showToast({ title: '联盟已创建', icon: 'success' })
      } catch (err) {
        uni.showModal({ title: '创建失败', content: err.message || '请稍后重试', showCancel: false })
      } finally {
        this.createBusy = false
      }
    },
    async openAlliance(item) {
      try {
        await this.reloadDetail(item.id)
      } catch (err) {
        uni.showToast({ title: err.message || '加载失败', icon: 'none' })
      }
    },
    async reloadDetail(allianceId) {
      const [detail, management] = await Promise.all([
        getPlatformAlliance(allianceId),
        getPlatformManagedClans(allianceId)
      ])
      this.detail = detail
      this.platformManagement = management
    },
    async addPlatformClan() {
      if (!this.detail || this.clanBusy || !this.newClanTag.trim()) return
      this.clanBusy = true
      try {
        await addPlatformManagedClan(this.detail.alliance.id, {
          clan_tag: this.newClanTag.trim(),
          category: this.categories[this.newCategoryIndex].key
        })
        this.newClanTag = ''
        await this.reloadDetail(this.detail.alliance.id)
        await this.loadDashboard()
        uni.showToast({ title: '部落已添加', icon: 'success' })
      } catch (err) {
        uni.showModal({ title: '添加失败', content: err.message || '请稍后重试', showCancel: false })
      } finally {
        this.clanBusy = false
      }
    },
    async addPlatformMember() {
      if (!this.detail || this.memberBusy || !this.newMemberOpenid.trim()) return
      this.memberBusy = true
      try {
        const selected = this.memberRoles[this.newMemberRoleIndex]
        await addPlatformAllianceMember(this.detail.alliance.id, this.newMemberOpenid.trim(), selected.key)
        this.newMemberOpenid = ''
        await this.reloadDetail(this.detail.alliance.id)
        await this.loadDashboard()
        uni.showToast({ title: '成员已添加', icon: 'success' })
      } catch (err) {
        uni.showModal({ title: '添加失败', content: err.message || '请稍后重试', showCancel: false })
      } finally {
        this.memberBusy = false
      }
    },
    changePlatformMemberRole(member, event) {
      const selected = this.memberRoles[Number(event.detail.value) || 0]
      if (!selected || selected.key === member.role) return
      const apply = async () => {
        try {
          await updatePlatformAllianceMemberRole(this.detail.alliance.id, member.id, selected.key)
          await this.reloadDetail(this.detail.alliance.id)
          await this.loadDashboard()
          uni.showToast({ title: '权限已更新', icon: 'success' })
        } catch (err) {
          uni.showModal({ title: '更新失败', content: err.message || '请稍后重试', showCancel: false })
        }
      }
      if (selected.key !== 'leader') {
        apply()
        return
      }
      uni.showModal({
        title: '移交联盟首领',
        content: `确认将${member.nickname || member.account_name || '该用户'}设为联盟首领？原首领将变为管理员。`,
        success: result => { if (result.confirm) apply() }
      })
    },
    confirmPlatformMemberRemove(member) {
      uni.showModal({
        title: '移除联盟成员',
        content: `确认移除${member.nickname || member.account_name || '该用户'}？`,
        confirmColor: '#c9797f',
        success: async result => {
          if (!result.confirm) return
          try {
            await removePlatformAllianceMember(this.detail.alliance.id, member.id)
            await this.reloadDetail(this.detail.alliance.id)
            await this.loadDashboard()
            uni.showToast({ title: '成员已移除', icon: 'success' })
          } catch (err) {
            uni.showToast({ title: err.message || '移除失败', icon: 'none' })
          }
        }
      })
    },
    async changePlatformCategory(clan, event) {
      const selected = this.categories[Number(event.detail.value) || 0]
      if (!selected || selected.key === clan.category) return
      try {
        await updatePlatformManagedClan(this.detail.alliance.id, clan.clan_tag, { category: selected.key })
        await this.reloadDetail(this.detail.alliance.id)
        uni.showToast({ title: '标签已更新', icon: 'success' })
      } catch (err) {
        uni.showToast({ title: err.message || '更新失败', icon: 'none' })
      }
    },
    editPlatformClanName(clan) {
      uni.showModal({
        title: '修改部落别名',
        editable: true,
        placeholderText: clan.clan_name || clan.clan_tag,
        content: clan.clan_name || '',
        success: async result => {
          if (!result.confirm) return
          try {
            await updatePlatformManagedClan(this.detail.alliance.id, clan.clan_tag, {
              category: clan.category,
              clan_name: result.content || clan.clan_tag
            })
            await this.reloadDetail(this.detail.alliance.id)
            uni.showToast({ title: '别名已更新', icon: 'success' })
          } catch (err) {
            uni.showToast({ title: err.message || '更新失败', icon: 'none' })
          }
        }
      })
    },
    async movePlatformClan(index, offset) {
      const target = index + offset
      if (target < 0 || target >= this.platformActiveClans.length) return
      const ordered = this.platformActiveClans.slice()
      const moved = ordered.splice(index, 1)[0]
      ordered.splice(target, 0, moved)
      try {
        await reorderPlatformManagedClans(this.detail.alliance.id, ordered.map(item => item.clan_tag))
        await this.reloadDetail(this.detail.alliance.id)
      } catch (err) {
        uni.showToast({ title: err.message || '排序失败', icon: 'none' })
      }
    },
    confirmPlatformRemove(clan) {
      uni.showModal({
        title: '移除部落',
        content: `确认从${this.detail.alliance.name}移除${clan.clan_name || clan.clan_tag}？公共历史数据不会删除。`,
        confirmColor: '#c9797f',
        success: async result => {
          if (!result.confirm) return
          try {
            await removePlatformManagedClan(this.detail.alliance.id, clan.clan_tag)
            await this.reloadDetail(this.detail.alliance.id)
            await this.loadDashboard()
            uni.showToast({ title: '已移除', icon: 'success' })
          } catch (err) {
            uni.showToast({ title: err.message || '移除失败', icon: 'none' })
          }
        }
      })
    },
    async setVerification(clan, status) {
      try {
        await savePlatformVerification(this.detail.alliance.id, clan.clan_tag, status, '平台人工操作')
        await this.reloadDetail(this.detail.alliance.id)
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
        await this.reloadDetail(this.detail.alliance.id)
        await this.loadDashboard()
        uni.showToast({ title: '付费权益已开通', icon: 'success' })
      } catch (err) {
        uni.showModal({ title: '开通失败', content: err.message || '请稍后重试', showCancel: false })
      }
    },
    async grantFree() {
      try {
        await savePlatformPlan(this.detail.alliance.id, 'free', null, '后台调整为免费版')
        await this.reloadDetail(this.detail.alliance.id)
        await this.loadDashboard()
        uni.showToast({ title: '已调整为免费版', icon: 'success' })
      } catch (err) {
        uni.showModal({ title: '调整失败', content: err.message || '请先移除多余部落', showCancel: false })
      }
    },
    changeStatus(status) {
      uni.showModal({
        title: status === 'active' ? '恢复联盟' : '停用联盟',
        content: status === 'active' ? '确认恢复该联盟？' : '停用后成员将暂时无法访问，公共历史不会删除。',
        success: async res => {
          if (!res.confirm) return
          try {
            await savePlatformAllianceStatus(this.detail.alliance.id, status, '平台人工操作')
            await this.reloadDetail(this.detail.alliance.id)
            await this.loadDashboard()
          } catch (err) {
            uni.showToast({ title: err.message || '操作失败', icon: 'none' })
          }
        }
      })
    },
    deleteAlliance() {
      const alliance = this.detail && this.detail.alliance
      if (!alliance || alliance.status !== 'suspended') return
      uni.showModal({
        title: '删除已停用联盟',
        content: `请输入联盟名称“${alliance.name}”确认删除`,
        editable: true,
        placeholderText: '联盟名称',
        confirmColor: '#c9797f',
        success: async result => {
          if (!result.confirm) return
          try {
            await deletePlatformAlliance(alliance.id, result.content)
            this.detail = null
            await this.loadDashboard()
            uni.showToast({ title: '联盟已删除', icon: 'success' })
          } catch (err) {
            uni.showToast({ title: err.message || '删除失败', icon: 'none' })
          }
        }
      })
    },
    statusLabel(value) { return ({ active: '正常', suspended: '已停用', archived: '已删除' }[value] || value) },
    grantStatusLabel(value) { return ({ active: '有效', grace: '7天只读宽限期', expired: '已到期', revoked: '已撤销' }[value] || value || '兼容权益') },
    categoryIndex(value) { const index = this.categories.findIndex(item => item.key === value); return index < 0 ? 0 : index },
    categoryLabel(value) { const item = this.categories.find(entry => entry.key === value); return item ? item.label : value },
    verificationLabel(value) { return ({ verified: '已认证', disputed: '争议中', revoked: '已撤销', unverified: '未认证' }[value] || value) },
    memberRoleIndex(value) { const index = this.memberRoles.findIndex(item => item.key === value); return index < 0 ? 0 : index },
    memberRoleLabel(value) { const item = this.memberRoles.find(entry => entry.key === value); return item ? item.label : value },
    memberStatusLabel(value) { return ({ active: '有效', left: '已退出', removed: '已移除', blocked: '已封禁', invited: '待加入' }[value] || value) },
    shortDate(value) { return value ? String(value).replace('T', ' ').slice(0, 16) : '' }
  }
}
</script>

<style>
.page { height: 100vh; display: flex; flex-direction: column; color: #dce1ed; background: #0f0f23; }
.content { flex: 1; min-height: 0; padding: 24rpx; box-sizing: border-box; }
.section-title { margin: 30rpx 8rpx 14rpx; color: #7f8aa2; font-size: 23rpx; }
.card { margin-bottom: 16rpx; padding: 22rpx; border: 1rpx solid #292945; border-radius: 14rpx; background: #18182d; }
.setting-row, .title-row, .clan-row, .member-row, .queue-row, .audit-row, .search-row { display: flex; align-items: center; }
.setting-row { min-height: 84rpx; }.grow { flex: 1; min-width: 0; }
.name { display: block; color: #e8ebf3; font-size: 26rpx; font-weight: 600; }.name.small { font-size: 24rpx; }
.sub { display: block; color: #778198; font-size: 21rpx; line-height: 1.6; }
.limit-input { width: 150rpx; padding: 12rpx; border: 1rpx solid #30304d; border-radius: 8rpx; color: #fff; text-align: center; background: #111126; }
.primary-btn, .secondary-btn, .search-btn, .mini-btn { border: 0; border-radius: 9rpx; font-size: 23rpx; }
.primary-btn, .secondary-btn { margin-top: 18rpx; line-height: 2.4; }.primary-btn { color: #fff; background: #315f9a; }.secondary-btn { color: #7eb8f6; background: #202b42; }
.primary-btn::after, .secondary-btn::after, .search-btn::after, .mini-btn::after { border: 0; }
.queue-row { justify-content: space-between; min-height: 54rpx; color: #9099ac; font-size: 22rpx; }
.search-row { margin-bottom: 18rpx; }.search-input { flex: 1; padding: 18rpx; border: 1rpx solid #292945; border-radius: 10rpx; color: #fff; background: #18182d; }.search-btn { width: 120rpx; margin-left: 12rpx; color: #7eb8f6; background: #202b42; line-height: 2.45; }
.standalone-input {
  height: 72rpx;
  padding: 0 18rpx;
  margin-top: 16rpx;
  box-sizing: border-box;
  font-size: 24rpx;
  line-height: 72rpx;
  background: #111126;
}
.alliance-card:active { background: #202038; }.status { color: #8d96a8; font-size: 21rpx; }.status-active { color: #54b9a6; }.status-suspended { color: #d29a5f; }.status-archived { color: #737b8e; }
.clan-row { min-height: 100rpx; border-bottom: 1rpx solid #25253e; }.clan-row:last-child { border-bottom: 0; }
.member-row { min-height: 112rpx; border-bottom: 1rpx solid #25253e; }.member-row:last-of-type { border-bottom: 0; }
.openid { display: block; max-width: 390rpx; margin-top: 5rpx; overflow: hidden; color: #667087; font-size: 18rpx; text-overflow: ellipsis; white-space: nowrap; }
.platform-order { width: 48rpx; flex-shrink: 0; display: flex; flex-direction: column; align-items: center; }.order-btn { color: #6da9e8; font-size: 25rpx; line-height: 1.45; }.order-btn.disabled { color: #3d4558; }
.category { margin-left: 8rpx; padding: 8rpx 10rpx; border-radius: 8rpx; color: #78afe8; background: #202940; font-size: 20rpx; }.edit-name { margin-left: 10rpx; color: #7f9fca; font-size: 20rpx; }.remove { margin-left: 12rpx; color: #b8757d; font-size: 20rpx; }
.platform-add { padding-top: 24rpx; }
.platform-add .search-input {
  height: 88rpx;
  padding: 0 22rpx;
  box-sizing: border-box;
  font-size: 25rpx;
  line-height: 88rpx;
  background: #111126;
}
.platform-add picker { display: block; }
.platform-picker {
  height: 88rpx;
  margin-top: 16rpx;
  padding: 0 22rpx;
  box-sizing: border-box;
  display: flex;
  align-items: center;
  border: 1rpx solid #30304d;
  border-radius: 10rpx;
  color: #a4adbf;
  background: #111126;
  font-size: 25rpx;
}
.platform-add .primary-btn {
  height: 88rpx;
  margin-top: 16rpx;
  font-size: 25rpx;
  line-height: 88rpx;
}
.mini-btn { margin: 0 0 0 8rpx; padding: 5rpx 12rpx; color: #7eb8f6; background: #202b42; line-height: 2; }.mini-btn.warn { color: #d4a665; }.mini-btn.danger { color: #c9797f; }
.action-card { margin-top: 16rpx; }.danger-text { color: #c9797f; }
.delete-btn { margin-top: 16rpx; border: 1rpx solid rgba(201, 121, 127, .45); border-radius: 9rpx; color: #d98c91; background: rgba(120, 45, 54, .18); font-size: 23rpx; line-height: 2.4; }
.delete-btn::after { border: 0; }.danger-tip { margin-top: 12rpx; color: #91676f; }
.audit-row { min-height: 58rpx; border-bottom: 1rpx solid #24243c; }.time { margin-left: 12rpx; color: #5f687e; font-size: 19rpx; }
.bottom-space { height: 80rpx; }
</style>
