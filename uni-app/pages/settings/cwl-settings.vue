<template>
  <view class="page">
    <TopBar title="联赛设置" :showBack="true" :backFallback="backFallback" />

    <scroll-view scroll-y class="content">
      <view class="summary">
        <view>
          <text class="summary-title">{{ alliance ? alliance.name : '月度联赛队伍' }}</text>
          <text class="summary-sub">{{ periodLabel }} · 已配置 {{ teams.length }}/{{ maxTeamsLabel }} 支队伍</text>
        </view>
        <text class="summary-role">{{ alliance ? (alliance.role_label || roleLabel(alliance.role)) : '' }}</text>
      </view>

      <view class="period-tabs">
        <view
          v-for="option in periodOptions"
          :key="option.period"
          class="period-tab"
          :class="{ active: period === option.period }"
          @tap="selectPeriod(option.period)"
        >
          <text class="period-tab-main">{{ option.shortLabel }}</text>
          <text class="period-tab-sub">{{ option.label }}</text>
        </view>
      </view>

      <view v-if="loading" class="state">加载联赛配置...</view>
      <template v-else>
        <view v-if="season" class="status-card">
          <view class="status-row">
            <text class="status-label">配置状态</text>
            <text class="status-value" :class="'status-' + status">{{ statusLabel }}</text>
          </view>
          <view class="status-row">
            <text class="status-label">队伍数量</text>
            <text class="status-value">{{ teams.length }}/{{ maxTeamsLabel }}</text>
          </view>
          <text v-if="!canEdit" class="status-tip">官方联赛组已发现或月份已结束，当前配置只读</text>
          <button
            v-if="canManage && !canEdit && period === currentPeriodValue"
            class="next-season-btn"
            :loading="busy"
            @tap="openNextSeason"
          >创建或管理{{ nextPeriodLabel }}联赛</button>
        </view>

        <view v-if="!season" class="empty-card season-empty">
          <text class="empty-title">{{ periodLabel }}联赛尚未创建</text>
          <text class="empty-tip">联赛部落按月独立配置，不要求加入日常部落列表或完成认证。</text>
          <button v-if="canManage" class="primary-btn create-season-btn" :loading="busy" @tap="createSelectedSeason">创建{{ periodLabel }}联赛</button>
        </view>

        <view v-if="season && canManage && canEdit" class="toolbar-card">
          <button class="secondary-btn" @tap="copyPrevious" :disabled="busy || teams.length > 0">复制上月</button>
          <text class="toolbar-tip">复制后仍可调整顺序、Tag、别名和队伍类别</text>
        </view>

        <template v-if="season">
          <view class="section-title">联赛队伍（{{ teams.length }}）</view>
          <view v-if="teams.length" class="card team-list">
            <view v-for="(team, index) in teams" :key="team.id" class="team-item">
              <view class="team-row">
                <view class="order-actions">
                  <template v-if="canManage && canEdit">
                    <text class="order-btn" :class="{ disabled: index === 0 }" @tap="moveTeam(index, -1)">↑</text>
                    <text class="order-btn" :class="{ disabled: index === teams.length - 1 }" @tap="moveTeam(index, 1)">↓</text>
                  </template>
                </view>
                <view class="team-main">
                  <text class="team-name">{{ team.team_alias || team.clan_name_snapshot || team.clan_tag }}</text>
                  <text class="team-meta">{{ team.clan_tag }}<text v-if="team.clan_name_snapshot && team.clan_name_snapshot !== team.team_alias"> · {{ team.clan_name_snapshot }}</text></text>
                  <text class="team-staff">首领：{{ team.leader_name || '-' }} · 管理：{{ team.manager_names || '-' }}</text>
                </view>
                <text class="category" :class="'category-' + team.category">{{ team.category === 'combat' ? '实战队' : '壳子队' }}</text>
                <text v-if="canManage && canEdit" class="edit" @tap="startEdit(team)">编辑</text>
                <text v-if="canManage && canEdit" class="remove" @tap="removeTeam(team)">删除</text>
                <text
                  v-else-if="canManage && (status === 'frozen' || status === 'complete')"
                  class="edit"
                  @tap="startCorrection(team)"
                >编辑</text>
              </view>

              <view v-if="editingTeamId === team.id" class="edit-form">
                <input v-model="editForm.clan_tag" class="input" placeholder="部落标签，例如 #2QQ" maxlength="15" />
                <input v-model="editForm.clan_name" class="input" placeholder="部落名称（可选）" maxlength="30" />
                <input v-model="editForm.team_alias" class="input" placeholder="队伍别名（可选）" maxlength="30" />
                <input v-model="editForm.manager_names" class="input" placeholder="联赛管理（可选，多人用顿号分隔）" maxlength="80" />
                <picker :range="categoryOptions" range-key="label" :value="editCategoryIndex" @change="changeEditCategory">
                  <view class="picker">队伍类别：{{ categoryOptions[editCategoryIndex].label }}⌄</view>
                </picker>
                <view class="form-actions">
                  <button class="secondary-btn" @tap="cancelEdit">取消</button>
                  <button class="primary-btn" :loading="busy" @tap="submitEdit(team)">保存修改</button>
                </view>
              </view>

              <view v-if="correctingTeamId === team.id" class="edit-form">
                <input v-model="correction.clan_tag" class="input" placeholder="部落标签，例如 #2QQ" maxlength="15" />
                <input v-model="correction.clan_name" class="input" placeholder="部落名称（可选）" maxlength="30" />
                <input v-model="correction.team_alias" class="input" placeholder="队伍别名（可选）" maxlength="30" />
                <input v-model="correction.manager_names" class="input" placeholder="联赛管理（可选，多人用顿号分隔）" maxlength="80" />
                <picker :range="categoryOptions" range-key="label" :value="correctionCategoryIndex" @change="changeCorrectionCategory">
                  <view class="picker">队伍类别：{{ categoryOptions[correctionCategoryIndex].label }}⌄</view>
                </picker>
                <view class="form-actions">
                  <button class="secondary-btn" @tap="cancelCorrection">取消</button>
                  <button class="primary-btn" :loading="busy" @tap="submitCorrection(team)">保存修改</button>
                </view>
              </view>
            </view>
          </view>
          <view v-else class="empty-card">
            <text class="empty-title">{{ periodLabel }}暂无联赛队伍</text>
            <text class="empty-tip">可以复制上月配置，也可以在下方逐个添加。</text>
          </view>

          <template v-if="canManage && canEdit">
            <view class="section-title">添加新联赛队伍</view>
            <view class="card add-card">
              <template v-if="teams.length < maxTeams">
                <input v-model="form.clan_tag" class="input" placeholder="部落标签，例如 #2QQ" maxlength="15" />
                <input v-model="form.clan_name" class="input" placeholder="部落名称（可选）" maxlength="30" />
                <input v-model="form.team_alias" class="input" placeholder="队伍别名（可选）" maxlength="30" />
                <input v-model="form.manager_names" class="input" placeholder="联赛管理（可选，多人用顿号分隔）" maxlength="80" />
                <picker :range="categoryOptions" range-key="label" :value="categoryIndex" @change="changeCategory">
                  <view class="picker">队伍类别：{{ categoryOptions[categoryIndex].label }}⌄</view>
                </picker>
                <button class="primary-btn add-btn" :loading="busy" :disabled="busy || !form.clan_tag.trim()" @tap="addTeam">添加联赛队伍</button>
              </template>
              <text v-else class="limit-tip">已达到当前套餐上限（{{ maxTeams }} 支）。删除现有队伍后可再添加。</text>
              <text class="notice">联赛部落按月配置，不要求加入日常部落列表或完成认证。</text>
            </view>
          </template>

          <button
            v-if="canManage && canEdit && teams.length"
            class="confirm-btn"
            :loading="busy"
            @tap="confirmSeason"
          >确认{{ periodLabel }}联赛队伍</button>
        </template>
        <view class="bottom-space"></view>
      </template>
    </scroll-view>
  </view>
</template>

<script>
import TopBar from '@/components/TopBar.vue'
import {
  getAllianceCwlSeason,
  createAllianceCwlSeason,
  copyPreviousAllianceCwlSeason,
  addAllianceCwlTeam,
  updateAllianceCwlTeam,
  deleteAllianceCwlTeam,
  amendAllianceCwlTeam,
  confirmAllianceCwlSeason,
  getPlatformAlliance
} from '@/utils/api.js'
import { getCurrentAlliance, loadAllianceContext } from '@/utils/alliance.js'

const BUSINESS_TIMEZONE_OFFSET_MS = 8 * 60 * 60 * 1000

function currentPeriod() {
  const date = new Date(Date.now() + BUSINESS_TIMEZONE_OFFSET_MS)
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, '0')}`
}

function nextPeriod(value) {
  const parts = value.split('-').map(Number)
  return parts[1] === 12 ? `${parts[0] + 1}-01` : `${parts[0]}-${String(parts[1] + 1).padStart(2, '0')}`
}

export default {
  components: { TopBar },
  data() {
    const current = currentPeriod()
    return {
      period: current,
      periodOptions: [
        { period: current, shortLabel: '本月', label: `${current.slice(0, 4)}年${Number(current.slice(5))}月` },
        { period: nextPeriod(current), shortLabel: '下月', label: `${nextPeriod(current).slice(0, 4)}年${Number(nextPeriod(current).slice(5))}月` }
      ],
      categoryOptions: [{ key: 'combat', label: '实战队' }, { key: 'shell', label: '壳子队' }],
      categoryIndex: 0,
      platformAllianceId: null,
      alliance: null,
      season: null,
      loading: true,
      busy: false,
      form: { clan_tag: '', clan_name: '', team_alias: '', manager_names: '', category: 'combat' },
      editingTeamId: null,
      editCategoryIndex: 0,
      editForm: { clan_tag: '', clan_name: '', team_alias: '', manager_names: '', category: 'combat' },
      correctingTeamId: null,
      correctionCategoryIndex: 0,
      correction: { clan_tag: '', clan_name: '', team_alias: '', manager_names: '', category: 'combat' }
    }
  },
  computed: {
    periodIndex() { const index = this.periodOptions.findIndex(item => item.period === this.period); return index < 0 ? 0 : index },
    periodLabel() { return this.periodOptions[this.periodIndex].label },
    currentPeriodValue() { return this.periodOptions[0].period },
    nextPeriodLabel() { return this.periodOptions[1].label },
    canManage() { return this.alliance && ['admin', 'leader', 'platform_admin'].indexOf(this.alliance.role) >= 0 },
    teams() { return this.season && this.season.teams ? this.season.teams.slice().sort((a, b) => a.sort_order - b.sort_order || a.team_index - b.team_index) : [] },
    maxTeams() { return (this.season && this.season.max_teams) || Number(this.alliance && this.alliance.plan && this.alliance.plan.entitlements && this.alliance.plan.entitlements.max_cwl_teams) || 1 },
    maxTeamsLabel() { return this.platformAllianceId ? '不限' : this.maxTeams },
    backFallback() { return this.platformAllianceId ? `/pages/settings/platform-alliance-detail?id=${this.platformAllianceId}` : '/pages/settings/settings' },
    status() { return this.season ? this.season.status : 'draft' },
    statusLabel() { return ({ draft: '草稿', active: '已确认', frozen: '已冻结', complete: '已结束' })[this.status] || this.status },
    canEdit() { return this.canManage && (!this.season || this.season.can_edit) }
  },
  async onLoad(options) {
    try {
      const platformAllianceId = Number(options && options.platform_alliance_id)
      if (platformAllianceId) {
        this.platformAllianceId = platformAllianceId
        const detail = await getPlatformAlliance(platformAllianceId)
        this.alliance = {
          id: detail.alliance.id,
          name: detail.alliance.name,
          role: 'platform_admin',
          role_label: '超级管理',
          plan: { entitlements: { max_cwl_teams: 10000 } }
        }
      } else {
        const loaded = await loadAllianceContext()
        this.alliance = loaded.current || getCurrentAlliance()
      }
      if (!this.canManage) {
        uni.showToast({ title: '联赛配置需要联盟管理权限', icon: 'none' })
      }
      await this.loadSeason()
    } catch (e) {
      this.loading = false
      uni.showToast({ title: e.message || '联赛配置加载失败', icon: 'none' })
    }
  },
  methods: {
    async loadSeason() {
      this.loading = true
      try {
        this.season = await getAllianceCwlSeason(this.period, this.platformAllianceId)
      } catch (e) {
        if ((e.message || '').indexOf('不存在') >= 0) this.season = null
        else throw e
      } finally { this.loading = false }
    },
    async ensureSeason() {
      if (!this.season) this.season = await createAllianceCwlSeason(this.period, this.platformAllianceId)
      return this.season
    },
    async selectPeriod(period) {
      if (period === this.period || this.loading) return
      this.period = period
      this.cancelEdit()
      this.cancelCorrection()
      await this.loadSeason()
    },
    async createSelectedSeason() {
      if (!this.canManage || this.busy) return
      this.busy = true
      try {
        this.season = await createAllianceCwlSeason(this.period, this.platformAllianceId)
        uni.showToast({ title: `${this.periodLabel}联赛已创建`, icon: 'success' })
      } catch (e) { uni.showToast({ title: e.message || '创建失败', icon: 'none' }) }
      finally { this.busy = false }
    },
    async openNextSeason() {
      if (this.busy) return
      this.period = this.periodOptions[1].period
      this.cancelEdit()
      this.cancelCorrection()
      await this.loadSeason()
      if (!this.season) await this.createSelectedSeason()
    },
    changeCategory(event) {
      this.categoryIndex = Number(event.detail.value)
      this.form.category = this.categoryOptions[this.categoryIndex].key
    },
    async copyPrevious() {
      this.busy = true
      try {
        await this.ensureSeason()
        this.season = await copyPreviousAllianceCwlSeason(this.period, this.platformAllianceId)
      } catch (e) { uni.showToast({ title: e.message || '复制失败', icon: 'none' }) }
      finally { this.busy = false }
    },
    async addTeam() {
      if (!this.form.clan_tag.trim()) { uni.showToast({ title: '请输入部落标签', icon: 'none' }); return }
      this.busy = true
      try {
        await this.ensureSeason()
        await addAllianceCwlTeam(this.period, this.form, this.platformAllianceId)
        this.form = { clan_tag: '', clan_name: '', team_alias: '', manager_names: '', category: 'combat' }
        this.categoryIndex = 0
        await this.loadSeason()
      } catch (e) { uni.showToast({ title: e.message || '添加失败', icon: 'none' }) }
      finally { this.busy = false }
    },
    async saveTeam(team, overrides) {
      const payload = Object.assign({
        clan_tag: team.clan_tag,
        clan_name: team.clan_name_snapshot,
        team_alias: team.team_alias,
        manager_names: team.manager_names,
        category: team.category,
        sort_order: team.sort_order
      }, overrides || {})
      await updateAllianceCwlTeam(this.period, team.id, payload, this.platformAllianceId)
    },
    startEdit(team) {
      this.cancelCorrection()
      this.editingTeamId = team.id
      this.editCategoryIndex = Math.max(0, this.categoryOptions.findIndex(item => item.key === team.category))
      this.editForm = {
        clan_tag: team.clan_tag || '',
        clan_name: team.clan_name_snapshot || '',
        team_alias: team.team_alias || '',
        manager_names: team.manager_names || '',
        category: team.category || 'combat'
      }
    },
    cancelEdit() {
      this.editingTeamId = null
      this.editCategoryIndex = 0
      this.editForm = { clan_tag: '', clan_name: '', team_alias: '', manager_names: '', category: 'combat' }
    },
    changeEditCategory(event) {
      this.editCategoryIndex = Number(event.detail.value) || 0
      this.editForm.category = this.categoryOptions[this.editCategoryIndex].key
    },
    async submitEdit(team) {
      if (!this.editForm.clan_tag.trim()) {
        uni.showToast({ title: '请输入部落标签', icon: 'none' })
        return
      }
      this.busy = true
      try {
        await this.saveTeam(team, {
          clan_tag: this.editForm.clan_tag.trim(),
          clan_name: this.editForm.clan_name.trim(),
          team_alias: this.editForm.team_alias.trim(),
          manager_names: this.editForm.manager_names.trim(),
          category: this.editForm.category
        })
        this.cancelEdit()
        await this.loadSeason()
        uni.showToast({ title: '队伍已更新', icon: 'success' })
      } catch (e) { uni.showToast({ title: e.message || '保存失败', icon: 'none' }) }
      finally { this.busy = false }
    },
    async moveTeam(index, direction) {
      const targetIndex = index + direction
      if (targetIndex < 0 || targetIndex >= this.teams.length || this.busy) return
      const current = this.teams[index]
      const target = this.teams[targetIndex]
      this.busy = true
      try {
        const temporary = Math.max.apply(null, this.teams.map(item => item.sort_order)) + 1
        await this.saveTeam(current, { sort_order: temporary })
        await this.saveTeam(target, { sort_order: current.sort_order })
        await this.saveTeam(current, { sort_order: target.sort_order })
        await this.loadSeason()
      } catch (e) { uni.showToast({ title: e.message || '排序失败', icon: 'none' }) }
      finally { this.busy = false }
    },
    removeTeam(team) {
      uni.showModal({
        title: '删除联赛队伍',
        content: `确认删除 ${team.clan_name_snapshot || team.clan_tag}？`,
        success: async (res) => {
          if (!res.confirm) return
          this.busy = true
          try { await deleteAllianceCwlTeam(this.period, team.id, this.platformAllianceId); await this.loadSeason() }
          catch (e) { uni.showToast({ title: e.message || '删除失败', icon: 'none' }) }
          finally { this.busy = false }
        }
      })
    },
    startCorrection(team) {
      this.cancelEdit()
      this.correctingTeamId = team.id
      this.correctionCategoryIndex = Math.max(0, this.categoryOptions.findIndex(item => item.key === team.category))
      this.correction = {
        clan_tag: team.clan_tag || '',
        clan_name: team.clan_name_snapshot || '',
        team_alias: team.team_alias || '',
        manager_names: team.manager_names || '',
        category: team.category || 'combat'
      }
    },
    cancelCorrection() {
      this.correctingTeamId = null
      this.correctionCategoryIndex = 0
      this.correction = { clan_tag: '', clan_name: '', team_alias: '', manager_names: '', category: 'combat' }
    },
    changeCorrectionCategory(event) {
      this.correctionCategoryIndex = Number(event.detail.value) || 0
      this.correction.category = this.categoryOptions[this.correctionCategoryIndex].key
    },
    async submitCorrection(team) {
      if (!this.correction.clan_tag.trim()) {
        uni.showToast({ title: '请输入部落标签', icon: 'none' })
        return
      }
      this.busy = true
      try {
        await amendAllianceCwlTeam(this.period, team.id, {
          clan_tag: this.correction.clan_tag.trim(),
          clan_name: this.correction.clan_name.trim(),
          team_alias: this.correction.team_alias.trim(),
          manager_names: this.correction.manager_names.trim(),
          category: this.correction.category,
          reason: '联赛设置页面编辑'
        }, this.platformAllianceId)
        this.cancelCorrection()
        await this.loadSeason()
        uni.showToast({ title: '队伍已更新', icon: 'success' })
      } catch (e) { uni.showToast({ title: e.message || '保存失败', icon: 'none' }) }
      finally { this.busy = false }
    },
    roleLabel(value) { return ({ leader: '首领', admin: '管理', member: '成员', platform_admin: '超级管理' }[value] || value) },
    confirmSeason() {
      uni.showModal({
        title: '确认联赛队伍',
        content: `确认后系统开始读取${this.periodLabel}官方联赛数据；发现官方分组后配置将冻结。`,
        success: async (res) => {
          if (!res.confirm) return
          this.busy = true
          try {
            this.season = await confirmAllianceCwlSeason(this.period, this.platformAllianceId)
            uni.showToast({ title: '已确认', icon: 'success' })
          } catch (e) { uni.showToast({ title: e.message || '确认失败', icon: 'none' }) }
          finally { this.busy = false }
        }
      })
    }
  }
}
</script>

<style>
.page { height: 100vh; display: flex; flex-direction: column; color: #dce1ed; background: #0f0f23; }
.content { flex: 1; min-height: 0; padding: 24rpx; box-sizing: border-box; }
.state { padding: 180rpx 24rpx; color: #717b91; font-size: 26rpx; text-align: center; }
.summary { display: flex; align-items: center; justify-content: space-between; padding: 24rpx; border: 1rpx solid #292945; border-radius: 14rpx; background: #18182d; }
.summary-title, .summary-sub { display: block; }.summary-title { color: #f2f3f8; font-size: 31rpx; font-weight: 700; }.summary-sub { margin-top: 8rpx; color: #737d92; font-size: 22rpx; }.summary-role { color: #68a8e9; font-size: 22rpx; }
.period-tabs { margin-top: 18rpx; padding: 6rpx; display: flex; border: 1rpx solid #292945; border-radius: 13rpx; background: #18182d; }
.period-tab { width: 50%; padding: 14rpx 8rpx; box-sizing: border-box; border-radius: 9rpx; color: #778197; text-align: center; }
.period-tab.active { color: #dce8f7; background: #263654; }.period-tab-main, .period-tab-sub { display: block; }.period-tab-main { font-size: 25rpx; font-weight: 600; }.period-tab-sub { margin-top: 4rpx; font-size: 19rpx; }
.section-title { margin: 30rpx 8rpx 14rpx; color: #7f8aa2; font-size: 23rpx; }
.card, .status-card, .toolbar-card, .empty-card { border: 1rpx solid #292945; border-radius: 14rpx; background: #18182d; }
.status-card { margin-top: 18rpx; padding: 18rpx 24rpx; }.status-row { display: flex; justify-content: space-between; padding: 8rpx 0; }.status-label, .status-tip { color: #8d95aa; }.status-value { font-weight: 600; }.status-active { color: #4aa3ff; }.status-frozen { color: #cba45e; }.status-complete { color: #8d95aa; }.status-tip { display: block; border-top: 1rpx solid #292b49; margin-top: 12rpx; padding-top: 16rpx; font-size: 22rpx; }
.next-season-btn { width: 100%; margin: 18rpx 0 0; border: 0; border-radius: 10rpx; color: #fff; background: #315f9a; font-size: 24rpx; line-height: 2.45; }.next-season-btn::after { border: 0; }
.toolbar-card { margin-top: 18rpx; padding: 18rpx; display: flex; align-items: center; }.toolbar-card .secondary-btn { width: 180rpx; flex-shrink: 0; }.toolbar-tip { margin-left: 18rpx; color: #69738a; font-size: 20rpx; line-height: 1.5; }
.team-list { overflow: hidden; }.team-item { border-bottom: 1rpx solid #25253e; }.team-item:last-child { border-bottom: 0; }.team-row { min-height: 132rpx; padding: 14rpx 18rpx; box-sizing: border-box; display: flex; align-items: center; }
.order-actions { width: 54rpx; min-height: 70rpx; flex-shrink: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; }.order-btn { color: #6da9e8; font-size: 27rpx; line-height: 1.45; }.order-btn.disabled { color: #3d4558; }
.team-main { flex: 1; min-width: 0; }.team-name, .team-meta, .team-staff { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.team-name { color: #e7e9f0; font-size: 26rpx; font-weight: 600; }.team-meta { margin-top: 7rpx; color: #69738a; font-size: 20rpx; }.team-staff { margin-top: 7rpx; color: #7e8ba2; font-size: 19rpx; }
.category { margin-left: 10rpx; padding: 8rpx 10rpx; border-radius: 8rpx; color: #78afe8; background: #202940; font-size: 20rpx; }.category-shell { color: #aa8dc2; background: #30283d; }.edit { margin-left: 14rpx; color: #6da9e8; font-size: 21rpx; }.remove { margin-left: 14rpx; color: #b8757d; font-size: 21rpx; }
.edit-form { padding: 4rpx 18rpx 24rpx 72rpx; }
.input, .picker {
  height: 84rpx;
  padding: 0 18rpx;
  box-sizing: border-box;
  border: 1rpx solid #30304d;
  border-radius: 10rpx;
  color: #dce1ed;
  background: #111126;
  font-size: 24rpx;
  line-height: 84rpx;
}
.input + .input, .picker { margin-top: 14rpx; }
.picker { display: flex; align-items: center; color: #a4adbf; }
.form-actions { margin-top: 16rpx; display: flex; gap: 14rpx; }.form-actions .primary-btn, .form-actions .secondary-btn { flex: 1; margin-top: 0; }
.primary-btn, .secondary-btn, .confirm-btn { border: 0; border-radius: 10rpx; font-size: 24rpx; line-height: 2.45; }.primary-btn, .confirm-btn { color: #fff; background: #315f9a; }.secondary-btn { color: #91b9e2; background: #202b42; }.primary-btn::after, .secondary-btn::after, .confirm-btn::after { border: 0; }.primary-btn[disabled], .secondary-btn[disabled] { color: #6f7890; background: #222b40; }
.empty-card { margin-top: 18rpx; padding: 70rpx 30rpx; text-align: center; }.empty-title, .empty-tip { display: block; }.empty-title { color: #ced3df; font-size: 27rpx; }.empty-tip { margin-top: 14rpx; color: #6c758a; font-size: 22rpx; line-height: 1.6; }.create-season-btn { margin-top: 24rpx; }
.add-card { padding: 24rpx; }.add-card .input:first-child { margin-top: 0; }.add-btn { margin-top: 18rpx; width: 100%; }.limit-tip, .notice { display: block; color: #8790a2; font-size: 22rpx; line-height: 1.6; }.notice { margin-top: 18rpx; color: #646e84; }
.confirm-btn { width: 100%; margin: 24rpx 0 0; }.bottom-space { height: 80rpx; }
</style>
