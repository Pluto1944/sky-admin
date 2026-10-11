/**
 * API 请求封装
 * 统一管理后端接口调用，自动携带 token
 */

import {
  clearCurrentAlliance,
  getCurrentAllianceId as storedAllianceId,
  getCurrentAllianceKey,
  setCurrentAlliance
} from './alliance-state.js'

// 后端 API 基地址
// 域名备案已通过，使用正式域名访问后端
const BASE_URL = 'https://api.skycoc.cc'

function currentAllianceId() {
  return uni.getStorageSync('token') ? storedAllianceId() : 0
}

function scopedPath(suffix) {
  const allianceId = currentAllianceId()
  return allianceId ? `/api/alliances/${allianceId}${suffix}` : ''
}

function legacySkyRequest(path) {
  const allianceKey = getCurrentAllianceKey()
  const allianceId = currentAllianceId()
  if (allianceId && allianceKey && allianceKey !== 'sky-internal') {
    return Promise.reject(new Error('该联盟的此项功能将在后续阶段开放'))
  }
  if (allianceId && !allianceKey) {
    return request('/api/me/alliances', 'GET', {}, true).then((response) => {
      const alliance = (response.alliances || []).find(item => Number(item.id) === allianceId)
      if (!alliance) throw new Error('当前联盟访问权限已失效')
      setCurrentAlliance(alliance)
      if (alliance.key !== 'sky-internal') throw new Error('该联盟的此项功能将在后续阶段开放')
      return request(path)
    })
  }
  return request(path)
}

/**
 * 通用请求方法
 * @param {string} url       - 接口路径（如 /api/wechat/login）
 * @param {string} method    - 请求方法 GET/POST/PUT/DELETE
 * @param {object} data      - 请求体（POST 时使用）
 * @param {boolean} needAuth - 是否需要登录认证
 * @returns {Promise}
 */
function request(url, method = 'GET', data = {}, needAuth = false) {
  return new Promise((resolve, reject) => {
    const header = {
      'Content-Type': 'application/json'
    }

    // 需要认证时自动添加 token
    if (needAuth) {
      const token = uni.getStorageSync('token')
      if (token) {
        header['Authorization'] = 'Bearer ' + token
      }
    }

    uni.request({
      url: BASE_URL + url,
      method: method,
      data: method === 'GET' ? undefined : data,
      header: header,
      timeout: 15000,
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data)
        } else if (res.statusCode === 401) {
          // token 过期，清除本地状态
          uni.removeStorageSync('token')
          clearCurrentAlliance()
          getApp().globalData.isLoggedIn = false
          getApp().globalData.userInfo = null
          uni.switchTab({
            url: '/pages/settings/settings'
          })
          reject(new Error('登录已过期，请重新登录'))
        } else {
          const msg = res.data && res.data.detail ? res.data.detail : '请求失败'
          reject(new Error(msg))
        }
      },
      fail: (err) => {
        reject(new Error('网络请求失败，请检查网络连接'))
      }
    })
  })
}

/** 获取公开的服务健康状态及已部署版本。 */
export function getServerInfo() {
  return request('/api/ping')
}

/** 获取 API 与调度器的实际运行版本和一致性状态。 */
export function getSystemVersion() {
  return request('/api/system/version')
}

/**
 * 微信登录
 * @param {string} code - wx.login() 返回的 code
 * @returns {Promise} { token, user }
 */
export function wechatLogin(code) {
  return request('/api/wechat/login', 'POST', { code })
}

/**
 * 获取当前用户信息
 * @returns {Promise} { openid, nickname, role, account_name, player_tag, ... }
 */
export function getMyInfo() {
  return request('/api/wechat/me', 'GET', {}, true)
}

/** 获取当前用户可以访问的联盟。 */
export function getMyAlliances() {
  return request('/api/me/alliances', 'GET', {}, true)
}

/** 将联盟记录为当前用户最近选择的默认联盟。 */
export function visitAlliance(allianceId) {
  return request(`/api/me/alliances/${encodeURIComponent(allianceId)}/visit`, 'POST', {}, true)
}

/**
 * 绑定游戏账号
 * @param {string} accountName - 游戏内昵称
 * @param {string} playerTag   - 玩家标签（如 #XXXX）
 * @returns {Promise} { success, user }
 */
export function bindAccount(accountName, playerTag) {
  const data = {}
  if (accountName) data.account_name = accountName
  if (playerTag) data.player_tag = playerTag
  return request('/api/wechat/bind', 'POST', data, true)
}

/**
 * 分页获取成员列表
 * @param {object} options - page/pageSize/memberStatus/clanTags/search/sortKey/sortOrder
 * @returns {Promise} { count, page, page_size, total_pages, members, clans }
 */
export function getMembers(options = {}) {
  const query = [
    `page=${encodeURIComponent(options.page || 1)}`,
    `page_size=${encodeURIComponent(options.pageSize || 100)}`,
    `membership_status=${encodeURIComponent(options.memberStatus || 'member')}`,
    `sort_key=${encodeURIComponent(options.sortKey || 'town_hall_level')}`,
    `sort_order=${encodeURIComponent(options.sortOrder || 'desc')}`
  ]
  if (options.clanTags && options.clanTags.length) query.push(`clan_tags=${encodeURIComponent(options.clanTags.join(','))}`)
  if (options.search) query.push(`search=${encodeURIComponent(options.search)}`)
  const scoped = scopedPath('/members')
  return request(`${scoped || '/api/members'}?${query.join('&')}`, 'GET', {}, Boolean(scoped))
}

/** 获取全部自有部落的概览卡片。 */
export function getClanOverview() {
  const scoped = scopedPath('/clans')
  return request(scoped || '/api/clan/overview', 'GET', {}, Boolean(scoped))
}

/** 获取单个自有部落的聚合详情。 */
export function getClanOverviewDetail(clanTag) {
  const scoped = scopedPath(`/clans/${encodeURIComponent(clanTag)}`)
  return scoped
    ? request(scoped, 'GET', {}, true)
    : request(`/api/clan/overview/${encodeURIComponent(clanTag)}`)
}

/**
 * 获取联赛战绩统计（滚动窗口三星率）
 * @param {string} period - 基准月份 YYYY-MM，不传则自动取当前 CWL 月份
 * @returns {Promise} { period, updated_at, stats: [{ player_tag, account_name, town_hall_level, offense_1m, ... }] }
 */
export function getLeagueStats(period) {
  const query = period ? `?period=${period}` : ''
  const scoped = scopedPath('/league-stats')
  return request(`${scoped || '/api/clan/league-stats'}${query}`, 'GET', {}, Boolean(scoped))
}

/**
 * 获取部落战战绩统计（按场次滚动窗口三星率）
 * @param {string} clanTag - 自有部落标签；不传时保留战营默认值
 * @returns {Promise} { clan_tag, updated_at, history_coverage, stats: [{ player_tag, account_name, town_hall_level, offense_5, ... }] }
 */
export function getWarStats(clanTag) {
  const query = clanTag ? `?clan_tag=${encodeURIComponent(clanTag)}` : ''
  const scoped = scopedPath('/war-stats')
  return request(`${scoped || '/api/clan/war-stats'}${query}`, 'GET', {}, Boolean(scoped))
}

/**
 * 获取互刷部落配置及清退辅助名单。
 * @returns {Promise} { clans: [{ clan_tag, realtime, despeed, replace_candidates, fill_accounts, inactive_members }] }
 */
export function getFarmConfig() {
  const scoped = scopedPath('/farm-config')
  return request(scoped || '/api/clan/farm-config', 'GET', {}, Boolean(scoped))
}

/** 获取全部自有部落的当前战争摘要。 */
export function getCurrentWars() {
  const scoped = scopedPath('/wars/current')
  return request(scoped || '/api/clan/current-wars', 'GET', {}, Boolean(scoped))
}

/** 获取单个自有部落的当前战争详情。 */
export function getCurrentWar(clanTag) {
  const scoped = scopedPath(`/wars/current/${encodeURIComponent(clanTag)}`)
  return scoped
    ? request(scoped, 'GET', {}, true)
    : request(`/api/clan/current-wars/${encodeURIComponent(clanTag)}`)
}

/** 获取全部自有部落最近 15 场已结束普通部落战摘要。 */
export function getWarHistory(clanTag) {
  const query = clanTag ? `?clan_tag=${encodeURIComponent(clanTag)}` : ''
  const scoped = scopedPath('/wars/history')
  return request(`${scoped || '/api/clan/war-history'}${query}`, 'GET', {}, Boolean(scoped))
}

/** 获取一场已归档普通部落战的完整详情。 */
export function getWarHistoryDetail(clanTag, warKey) {
  const suffix = `/wars/history/${encodeURIComponent(clanTag)}/${encodeURIComponent(warKey)}`
  const scoped = scopedPath(suffix)
  return scoped
    ? request(scoped, 'GET', {}, true)
    : request(`/api/clan/war-history/${encodeURIComponent(clanTag)}/${encodeURIComponent(warKey)}`)
}

/** 获取当前月份 CWL 参赛部落摘要。 */
export function getCwlLive(period) {
  const query = period ? `?period=${encodeURIComponent(period)}` : ''
  const scoped = scopedPath('/cwl/live')
  return request(`${scoped || '/api/clan/cwl-live'}${query}`, 'GET', {}, Boolean(scoped))
}

/** 获取当月各联赛队伍的当前战斗日未出刀成员及已结束场次漏刀记录。 */
export function getCwlCheckIn() {
  return legacySkyRequest('/api/clan/cwl-check-in')
}

/** 获取当月联赛正式名单与到位情况汇总。 */
export function getCwlAssembly() {
  return legacySkyRequest('/api/clan/cwl-assembly')
}

/** 获取单个联赛部落的集结检查详情。 */
export function getCwlAssemblyDetail(clanTag) {
  return legacySkyRequest(`/api/clan/cwl-assembly/${encodeURIComponent(clanTag)}`)
}

/** 按需获取单个联赛部落的战斗日或联赛总览。 */
export function getCwlLiveDetail(clanTag, period, round, view) {
  const query = []
  if (period) query.push(`period=${encodeURIComponent(period)}`)
  if (round) query.push(`round=${encodeURIComponent(round)}`)
  if (view) query.push(`view=${encodeURIComponent(view)}`)
  const scoped = scopedPath(`/cwl/live/${encodeURIComponent(clanTag)}`)
  return request(
    `${scoped || '/api/clan/cwl-live/' + encodeURIComponent(clanTag)}${query.length ? '?' + query.join('&') : ''}`,
    'GET', {}, Boolean(scoped)
  )
}

/** 读取当前联盟的月度联赛配置。 */
export function getAllianceCwlSeason(period) {
  const scoped = scopedPath(`/cwl/seasons/${encodeURIComponent(period)}`)
  if (!scoped) return Promise.reject(new Error('请先选择联盟'))
  return request(scoped, 'GET', {}, true)
}

/** 创建当前联盟的月度联赛配置。 */
export function createAllianceCwlSeason(period) {
  const scoped = scopedPath(`/cwl/seasons/${encodeURIComponent(period)}`)
  if (!scoped) return Promise.reject(new Error('请先选择联盟'))
  return request(scoped, 'POST', {}, true)
}

export function copyPreviousAllianceCwlSeason(period) {
  const scoped = scopedPath(`/cwl/seasons/${encodeURIComponent(period)}/copy-previous`)
  if (!scoped) return Promise.reject(new Error('请先选择联盟'))
  return request(scoped, 'POST', {}, true)
}

export function addAllianceCwlTeam(period, payload) {
  const scoped = scopedPath(`/cwl/seasons/${encodeURIComponent(period)}/teams`)
  if (!scoped) return Promise.reject(new Error('请先选择联盟'))
  return request(scoped, 'POST', payload, true)
}

export function updateAllianceCwlTeam(period, teamId, payload) {
  const scoped = scopedPath(`/cwl/seasons/${encodeURIComponent(period)}/teams/${teamId}`)
  if (!scoped) return Promise.reject(new Error('请先选择联盟'))
  return request(scoped, 'PUT', payload, true)
}

export function deleteAllianceCwlTeam(period, teamId) {
  const scoped = scopedPath(`/cwl/seasons/${encodeURIComponent(period)}/teams/${teamId}`)
  if (!scoped) return Promise.reject(new Error('请先选择联盟'))
  return request(scoped, 'DELETE', {}, true)
}

/** 联赛组已发现后，通过留痕操作纠正队伍 Tag。 */
export function correctAllianceCwlTeamTag(period, teamId, payload) {
  const scoped = scopedPath(`/cwl/seasons/${encodeURIComponent(period)}/teams/${teamId}/correct-tag`)
  if (!scoped) return Promise.reject(new Error('请先选择联盟'))
  return request(scoped, 'POST', payload, true)
}

export function confirmAllianceCwlSeason(period) {
  const scoped = scopedPath(`/cwl/seasons/${encodeURIComponent(period)}/confirm`)
  if (!scoped) return Promise.reject(new Error('请先选择联盟'))
  return request(scoped, 'POST', {}, true)
}

export default {
  getServerInfo,
  getSystemVersion,
  wechatLogin,
  getMyInfo,
  getMyAlliances,
  visitAlliance,
  bindAccount,
  getMembers,
  getClanOverview,
  getClanOverviewDetail,
  getLeagueStats,
  getWarStats,
  getFarmConfig,
  getCurrentWars,
  getCurrentWar,
  getWarHistory,
  getWarHistoryDetail,
  getCwlLive,
  getCwlCheckIn,
  getCwlAssembly,
  getCwlAssemblyDetail,
  getCwlLiveDetail,
  getAllianceCwlSeason,
  createAllianceCwlSeason,
  copyPreviousAllianceCwlSeason,
  addAllianceCwlTeam,
  updateAllianceCwlTeam,
  deleteAllianceCwlTeam,
  correctAllianceCwlTeamTag,
  confirmAllianceCwlSeason
}
