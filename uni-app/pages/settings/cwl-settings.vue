<template>
  <view class="page-container">
    <TopBar title="联赛设置" :showBack="true" backFallback="/pages/settings/settings" />

    <scroll-view scroll-y class="content-scroll">
      <view class="period-card">
        <view>
          <text class="card-title">月度联赛队伍</text>
          <text class="card-desc">联赛队伍按月配置，不要求加入日常部落列表或完成认证</text>
        </view>
        <picker :range="periodOptions" range-key="label" :value="periodIndex" @change="changePeriod">
          <text class="period-picker">{{ periodOptions[periodIndex].label }}⌄</text>
        </picker>
      </view>

      <view v-if="loading" class="state-card">加载联赛配置...</view>
      <template v-else>
        <view class="status-card">
          <view class="status-row">
            <text class="status-label">配置状态</text>
            <text class="status-value" :class="'status-' + status">{{ statusLabel }}</text>
          </view>
          <view class="status-row">
            <text class="status-label">队伍数量</text>
            <text class="status-value">{{ teams.length }}/{{ maxTeams }}</text>
          </view>
          <text v-if="!season" class="status-tip">当前联盟本月暂无联赛队伍</text>
          <text v-else-if="!canEdit" class="status-tip">官方联赛组已发现或月份已结束，配置只读</text>
        </view>

        <view v-if="canManage && canEdit" class="toolbar-card">
          <button class="secondary-btn" @tap="copyPrevious" :disabled="busy || teams.length > 0">复制上月</button>
          <button class="primary-btn" @tap="showAddForm = !showAddForm" :disabled="busy || teams.length >= maxTeams">添加队伍</button>
        </view>

        <view v-if="showAddForm && canEdit" class="form-card">
          <text class="section-title">添加联赛队伍</text>
          <input v-model="form.clan_tag" class="input" placeholder="部落标签，例如 #2QQ" maxlength="15" />
          <input v-model="form.clan_name" class="input" placeholder="部落名称（可选）" maxlength="30" />
          <input v-model="form.team_alias" class="input" placeholder="队伍别名（可选）" maxlength="30" />
          <picker :range="categoryOptions" range-key="label" :value="categoryIndex" @change="changeCategory">
            <view class="picker-input">队伍类别：{{ categoryOptions[categoryIndex].label }}⌄</view>
          </picker>
          <view class="form-actions">
            <button class="secondary-btn" @tap="showAddForm = false">取消</button>
            <button class="primary-btn" :loading="busy" @tap="addTeam">保存</button>
          </view>
        </view>

        <view class="team-list">
          <view v-for="(team, index) in teams" :key="team.id" class="team-card">
            <view class="team-main">
              <view class="team-title-row">
                <text class="team-name">{{ team.clan_name_snapshot || team.team_alias || team.clan_tag }}</text>
                <text class="category-badge" :class="'category-' + team.category">{{ team.category === 'combat' ? '实战队' : '壳子队' }}</text>
              </view>
              <text class="team-tag">{{ team.clan_tag }}</text>
              <text v-if="team.team_alias && team.team_alias !== team.clan_name_snapshot" class="team-alias">别名：{{ team.team_alias }}</text>
            </view>
            <view v-if="canManage && canEdit" class="team-actions">
              <text class="sort-btn" :class="{ disabled: index === 0 }" @tap="moveTeam(index, -1)">↑</text>
              <text class="sort-btn" :class="{ disabled: index === teams.length - 1 }" @tap="moveTeam(index, 1)">↓</text>
              <text class="category-toggle" @tap="toggleCategory(team)">切换类别</text>
              <text class="delete-btn" @tap="removeTeam(team)">删除</text>
            </view>
            <text
              v-else-if="canManage && (status === 'frozen' || status === 'complete')"
              class="correct-btn"
              @tap="startCorrection(team)"
            >纠正Tag</text>
            <view v-if="correctingTeamId === team.id" class="correction-form">
              <input v-model="correction.clan_tag" class="input" placeholder="纠正后的部落标签" maxlength="15" />
              <input v-model="correction.reason" class="input" placeholder="纠正原因（必填）" maxlength="80" />
              <view class="form-actions correction-actions">
                <button class="secondary-btn" @tap="cancelCorrection">取消</button>
                <button class="primary-btn" :loading="busy" @tap="submitCorrection(team)">提交纠正</button>
              </view>
            </view>
          </view>
          <view v-if="!teams.length" class="empty-card">当前联盟本月暂无联赛队伍</view>
        </view>

        <button
          v-if="canManage && canEdit && teams.length"
          class="confirm-btn"
          :loading="busy"
          @tap="confirmSeason"
        >确认本月联赛队伍</button>
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
  correctAllianceCwlTeamTag,
  confirmAllianceCwlSeason
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
        { period: current, label: `${current.slice(0, 4)}年${Number(current.slice(5))}月` },
        { period: nextPeriod(current), label: `${nextPeriod(current).slice(0, 4)}年${Number(nextPeriod(current).slice(5))}月` }
      ],
      categoryOptions: [{ key: 'combat', label: '实战队' }, { key: 'shell', label: '壳子队' }],
      categoryIndex: 0,
      alliance: null,
      season: null,
      loading: true,
      busy: false,
      showAddForm: false,
      form: { clan_tag: '', clan_name: '', team_alias: '', category: 'combat' },
      correctingTeamId: null,
      correction: { clan_tag: '', reason: '' }
    }
  },
  computed: {
    periodIndex() { const index = this.periodOptions.findIndex(item => item.period === this.period); return index < 0 ? 0 : index },
    canManage() { return this.alliance && ['admin', 'leader'].indexOf(this.alliance.role) >= 0 },
    teams() { return this.season && this.season.teams ? this.season.teams.slice().sort((a, b) => a.sort_order - b.sort_order || a.team_index - b.team_index) : [] },
    maxTeams() { return (this.season && this.season.max_teams) || Number(this.alliance && this.alliance.plan && this.alliance.plan.entitlements && this.alliance.plan.entitlements.max_cwl_teams) || 1 },
    status() { return this.season ? this.season.status : 'draft' },
    statusLabel() { return ({ draft: '草稿', active: '已确认', frozen: '已冻结', complete: '已结束' })[this.status] || this.status },
    canEdit() { return this.canManage && (!this.season || this.season.can_edit) }
  },
  async onLoad() {
    try {
      const loaded = await loadAllianceContext()
      this.alliance = loaded.current || getCurrentAlliance()
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
        this.season = await getAllianceCwlSeason(this.period)
      } catch (e) {
        if ((e.message || '').indexOf('不存在') >= 0) this.season = null
        else throw e
      } finally { this.loading = false }
    },
    async ensureSeason() {
      if (!this.season) this.season = await createAllianceCwlSeason(this.period)
      return this.season
    },
    async changePeriod(event) {
      this.period = this.periodOptions[Number(event.detail.value)].period
      this.showAddForm = false
      this.cancelCorrection()
      await this.loadSeason()
    },
    changeCategory(event) {
      this.categoryIndex = Number(event.detail.value)
      this.form.category = this.categoryOptions[this.categoryIndex].key
    },
    async copyPrevious() {
      this.busy = true
      try {
        await this.ensureSeason()
        this.season = await copyPreviousAllianceCwlSeason(this.period)
      } catch (e) { uni.showToast({ title: e.message || '复制失败', icon: 'none' }) }
      finally { this.busy = false }
    },
    async addTeam() {
      if (!this.form.clan_tag.trim()) { uni.showToast({ title: '请输入部落标签', icon: 'none' }); return }
      this.busy = true
      try {
        await this.ensureSeason()
        await addAllianceCwlTeam(this.period, this.form)
        this.form = { clan_tag: '', clan_name: '', team_alias: '', category: 'combat' }
        this.categoryIndex = 0
        this.showAddForm = false
        await this.loadSeason()
      } catch (e) { uni.showToast({ title: e.message || '添加失败', icon: 'none' }) }
      finally { this.busy = false }
    },
    async saveTeam(team, overrides) {
      const payload = Object.assign({
        clan_tag: team.clan_tag,
        clan_name: team.clan_name_snapshot,
        team_alias: team.team_alias,
        category: team.category,
        sort_order: team.sort_order
      }, overrides || {})
      await updateAllianceCwlTeam(this.period, team.id, payload)
    },
    async toggleCategory(team) {
      this.busy = true
      try {
        await this.saveTeam(team, { category: team.category === 'combat' ? 'shell' : 'combat' })
        await this.loadSeason()
      } catch (e) { uni.showToast({ title: e.message || '修改失败', icon: 'none' }) }
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
          try { await deleteAllianceCwlTeam(this.period, team.id); await this.loadSeason() }
          catch (e) { uni.showToast({ title: e.message || '删除失败', icon: 'none' }) }
          finally { this.busy = false }
        }
      })
    },
    startCorrection(team) {
      this.correctingTeamId = team.id
      this.correction = { clan_tag: team.clan_tag, reason: '' }
    },
    cancelCorrection() {
      this.correctingTeamId = null
      this.correction = { clan_tag: '', reason: '' }
    },
    async submitCorrection(team) {
      if (!this.correction.clan_tag.trim() || !this.correction.reason.trim()) {
        uni.showToast({ title: '请填写新Tag和纠正原因', icon: 'none' })
        return
      }
      this.busy = true
      try {
        await correctAllianceCwlTeamTag(this.period, team.id, this.correction)
        this.cancelCorrection()
        await this.loadSeason()
        uni.showToast({ title: '已纠正并留痕', icon: 'success' })
      } catch (e) { uni.showToast({ title: e.message || '纠正失败', icon: 'none' }) }
      finally { this.busy = false }
    },
    confirmSeason() {
      uni.showModal({
        title: '确认联赛队伍',
        content: '确认后系统开始读取本月官方联赛数据；发现官方分组后配置将冻结。',
        success: async (res) => {
          if (!res.confirm) return
          this.busy = true
          try {
            this.season = await confirmAllianceCwlSeason(this.period)
            uni.showToast({ title: '已确认', icon: 'success' })
          } catch (e) { uni.showToast({ title: e.message || '确认失败', icon: 'none' }) }
          finally { this.busy = false }
        }
      })
    }
  }
}
</script>

<style scoped>
.page-container { min-height: 100vh; background: #0f0f23; color: #e7e9f2; }
.content-scroll { height: calc(100vh - 150rpx); padding: 20rpx 24rpx; box-sizing: border-box; }
.period-card, .status-card, .toolbar-card, .form-card, .team-card, .empty-card { background: #19192f; border: 1rpx solid #2e3054; border-radius: 16rpx; margin-bottom: 18rpx; }
.period-card { padding: 24rpx; display: flex; justify-content: space-between; align-items: center; }
.card-title, .section-title { display: block; font-size: 32rpx; font-weight: 700; }
.card-desc { display: block; color: #7f879e; font-size: 23rpx; margin-top: 8rpx; max-width: 430rpx; }
.period-picker { color: #58a6ff; font-size: 27rpx; }
.state-card { color: #8d95aa; text-align: center; padding: 120rpx 0; }
.status-card { padding: 18rpx 24rpx; }
.status-row { display: flex; justify-content: space-between; padding: 8rpx 0; }
.status-label, .status-tip { color: #8d95aa; }
.status-value { font-weight: 600; }
.status-active { color: #4aa3ff; }.status-frozen { color: #fdcb6e; }.status-complete { color: #8d95aa; }
.status-tip { display: block; border-top: 1rpx solid #292b49; margin-top: 12rpx; padding-top: 16rpx; font-size: 24rpx; }
.toolbar-card, .form-actions { display: flex; gap: 16rpx; padding: 18rpx; }
.primary-btn, .secondary-btn, .confirm-btn { border-radius: 12rpx; font-size: 26rpx; line-height: 72rpx; }
.primary-btn, .confirm-btn { background: #274878; color: #68b2ff; }.secondary-btn { background: #23243f; color: #a6adc4; }
.form-card { padding: 24rpx; }
.input, .picker-input { background: #121226; border: 1rpx solid #303254; border-radius: 10rpx; padding: 18rpx; margin-top: 16rpx; font-size: 26rpx; color: #e7e9f2; }
.team-card { padding: 22rpx; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; }
.team-main { min-width: 0; flex: 1; }.team-title-row { display: flex; align-items: center; gap: 12rpx; }.team-name { font-size: 29rpx; font-weight: 650; max-width: 340rpx; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.category-badge { font-size: 21rpx; padding: 4rpx 9rpx; border-radius: 6rpx; background: #1d3150; color: #67aef5; }.category-shell { background: #342744; color: #bb8bd8; }
.team-tag, .team-alias { display: block; color: #747d96; font-size: 23rpx; margin-top: 8rpx; }
.team-actions { display: flex; align-items: center; gap: 14rpx; margin-left: 12rpx; }.sort-btn, .category-toggle, .delete-btn { color: #6aaeff; font-size: 23rpx; }.delete-btn { color: #d77b7b; }.disabled { color: #3c405c; }
.correct-btn { color: #6aaeff; font-size: 23rpx; margin-left: 12rpx; }.correction-form { width: 100%; border-top: 1rpx solid #292b49; margin-top: 18rpx; padding-top: 4rpx; }.correction-actions { padding: 16rpx 0 0; }
.empty-card { color: #70788f; padding: 70rpx 20rpx; text-align: center; }.confirm-btn { margin: 24rpx 0; width: 100%; }.bottom-space { height: 80rpx; }
</style>
