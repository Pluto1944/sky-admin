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
  return storedAllianceId()
}

function scopedPath(suffix, allianceId = currentAllianceId()) {
  return allianceId ? `/api/alliances/${allianceId}${suffix}` : ''
}

function missingAlliance() {
  return Promise.reject(new Error('请先创建、加入或通过分享打开一个联盟'))
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

    const shareTokens = uni.getStorageSync('allianceShareTokens') || {}
    const allianceId = storedAllianceId()
    const shared = shareTokens[String(allianceId)]
    if (shared && shared.token && shared.expiresAt && Date.parse(shared.expiresAt) > Date.now()) {
      header['X-Alliance-Share'] = shared.token
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

/** 互刷系统请求使用独立 farm_token，绝不读写微信 token。 */
function farmRequest(url, method = 'GET', data = {}, needAuth = true) {
  return new Promise((resolve, reject) => {
    const header = { 'Content-Type': 'application/json' }
    if (needAuth) {
      const token = uni.getStorageSync('farm_token')
      if (token) header.Authorization = 'Bearer ' + token
    }
    uni.request({
      url: BASE_URL + url,
      method,
      data: method === 'GET' ? undefined : data,
      header,
      timeout: 15000,
      success: (res) => {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data)
          return
        }
        const msg = res.data && res.data.detail ? res.data.detail : '请求失败'
        if (res.statusCode === 401 && needAuth) {
          uni.removeStorageSync('farm_token')
          uni.removeStorageSync('farm_account')
          uni.redirectTo({ url: '/pages/farm/login' })
        }
        reject(new Error(msg))
      },
      fail: () => reject(new Error('网络请求失败，请检查网络连接'))
    })
  })
}

export function farmLogin(username, password) {
  return farmRequest('/api/farm-system/auth/login', 'POST', { username, password }, false)
}

export function farmLogout() {
  return farmRequest('/api/farm-system/auth/logout', 'POST')
}

export function getFarmMe() {
  return farmRequest('/api/farm-system/me')
}

export function getFarmClans() {
  return farmRequest('/api/farm-system/clans')
}

export function getFarmAdminAccounts() {
  return farmRequest('/api/farm-system/admin/accounts')
}

export function createFarmAccount(payload) {
  return farmRequest('/api/farm-system/admin/accounts', 'POST', payload)
}

export function updateFarmAccount(accountId, payload) {
  return farmRequest(`/api/farm-system/admin/accounts/${encodeURIComponent(accountId)}`, 'PATCH', payload)
}

export function getFarmAdminClans() {
  return farmRequest('/api/farm-system/admin/clans')
}

export function createFarmClan(payload) {
  return farmRequest('/api/farm-system/admin/clans', 'POST', payload)
}

export function requestFarmClanSync(payload) {
  return farmRequest('/api/farm-system/admin/clan-sync-requests', 'POST', payload)
}

export function getFarmClanSyncStatus(clanTag, accountId) {
  return farmRequest(
    `/api/farm-system/admin/clan-sync-requests/${encodeURIComponent(clanTag)}?account_id=${encodeURIComponent(accountId)}`
  )
}

export function updateFarmClan(clanTag, payload) {
  return farmRequest(`/api/farm-system/admin/clans/${encodeURIComponent(clanTag)}`, 'PATCH', payload)
}

export function transferFarmClan(clanTag, accountId) {
  return farmRequest(
    `/api/farm-system/admin/clans/${encodeURIComponent(clanTag)}/transfer`,
    'POST',
    { account_id: accountId }
  )
}

export function getFarmDashboard() {
  return farmRequest('/api/farm-system/dashboard')
}

export function createFarmRound(payload) {
  return farmRequest('/api/farm-system/admin/rounds', 'POST', payload)
}

export function updateFarmRound(roundId, payload) {
  return farmRequest(`/api/farm-system/admin/rounds/${encodeURIComponent(roundId)}`, 'PATCH', payload)
}

export function getFarmRoundResults(roundId) {
  return farmRequest(`/api/farm-system/admin/rounds/${encodeURIComponent(roundId)}/results`)
}

export function registerFarmClan(roundId, clanTag) {
  return farmRequest(
    `/api/farm-system/rounds/${encodeURIComponent(roundId)}/clans/${encodeURIComponent(clanTag)}/register`,
    'POST'
  )
}

export function revokeFarmMatch(matchId, reason) {
  return farmRequest(
    `/api/farm-system/creator/matches/${encodeURIComponent(matchId)}/revoke`,
    'POST',
    { reason }
  )
}

export function reopenFarmMatch(matchId) {
  return farmRequest(
    `/api/farm-system/creator/matches/${encodeURIComponent(matchId)}/reopen`,
    'POST'
  )
}

export function cancelFarmRound(roundId, reason) {
  return farmRequest(
    `/api/farm-system/creator/rounds/${encodeURIComponent(roundId)}/cancel`,
    'POST',
    { reason }
  )
}

export function resetFarmAccountPassword(accountId, newPassword) {
  return farmRequest(
    `/api/farm-system/creator/accounts/${encodeURIComponent(accountId)}/reset-password`,
    'POST',
    { new_password: newPassword }
  )
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

/** 保存用户主动选择或填写的小程序昵称。 */
export function updateWechatProfile(nickname) {
  return request('/api/wechat/profile', 'PATCH', { nickname }, true)
}

/** 获取当前用户可以访问的联盟。 */
export function getMyAlliances() {
  return request('/api/me/alliances', 'GET', {}, true)
}

/** 将联盟记录为当前用户最近选择的默认联盟。 */
export function visitAlliance(allianceId) {
  return request(`/api/me/alliances/${encodeURIComponent(allianceId)}/visit`, 'POST', {}, true)
}

/** 仅调整当前用户切换列表的显示偏好，不改变联盟成员关系。 */
export function setAllianceVisibility(allianceId, hidden) {
  return request(
    `/api/me/alliances/${encodeURIComponent(allianceId)}/visibility`,
    'PATCH',
    { hidden: Boolean(hidden) },
    true
  )
}

/** M5 内部灰度：创建当前用户的免费单部落联盟。 */
export function createFreeAlliance(name) {
  return request('/api/me/alliances', 'POST', { name: name || undefined }, true)
}

export function renameAlliance(allianceId, name) {
  return request(`/api/alliances/${encodeURIComponent(allianceId)}`, 'PATCH', { name }, true)
}

// 兼容仍引用旧名称的页面；新代码统一使用联盟语义。
export const renameFreeAlliance = renameAlliance

export function getFreeAllianceSubscription(allianceId) {
  return request(`/api/alliances/${encodeURIComponent(allianceId)}/subscription`, 'GET', {}, true)
}

export function saveFreeAllianceSubscription(allianceId, payload) {
  return request(`/api/alliances/${encodeURIComponent(allianceId)}/subscription`, 'PUT', payload, true)
}

export function refreshFreeAllianceSubscription(allianceId, resourceTypes = ['current_war']) {
  return request(
    `/api/alliances/${encodeURIComponent(allianceId)}/subscription/refresh`,
    'POST',
    { resource_types: resourceTypes },
    true
  )
}

export function archiveAlliance(allianceId, confirmationName) {
  const query = `?confirmation_name=${encodeURIComponent(confirmationName || '')}`
  return request(`/api/alliances/${encodeURIComponent(allianceId)}${query}`, 'DELETE', {}, true)
}

// 兼容已存在的调用；后端删除接口适用于所有非 internal 联盟。
export const archiveFreeAlliance = archiveAlliance

export function getAllianceVerification(allianceId) {
  return request(`/api/alliances/${encodeURIComponent(allianceId)}/verification`, 'GET', {}, true)
}

export function getAllianceManagedClans(allianceId) {
  return request(`/api/alliances/${encodeURIComponent(allianceId)}/managed-clans`, 'GET', {}, true)
}

export function addAllianceManagedClan(allianceId, payload) {
  return request(`/api/alliances/${encodeURIComponent(allianceId)}/managed-clans`, 'POST', payload, true)
}

export function updateAllianceManagedClan(allianceId, clanTag, payload) {
  return request(`/api/alliances/${encodeURIComponent(allianceId)}/managed-clans/${encodeURIComponent(clanTag)}`, 'PATCH', payload, true)
}

export function reorderAllianceManagedClans(allianceId, clanTags) {
  return request(`/api/alliances/${encodeURIComponent(allianceId)}/managed-clans/order`, 'PUT', { clan_tags: clanTags }, true)
}

export function removeAllianceManagedClan(allianceId, clanTag) {
  return request(`/api/alliances/${encodeURIComponent(allianceId)}/managed-clans/${encodeURIComponent(clanTag)}`, 'DELETE', {}, true)
}

export function refreshAllianceManagedClan(allianceId, clanTag, resourceTypes = ['current_war']) {
  return request(
    `/api/alliances/${encodeURIComponent(allianceId)}/managed-clans/${encodeURIComponent(clanTag)}/refresh`,
    'POST',
    { resource_types: resourceTypes },
    true
  )
}

/**
 * 为当前可访问的按需刷新套餐页面提交公共资源刷新任务。
 * 认证用户、历史访问者和有效分享访客都复用页面读取权限。
 */
export function requestAlliancePageRefresh(allianceId, clanTag, resourceTypes, period = '', trigger = 'manual') {
  return request(
    `/api/alliances/${encodeURIComponent(allianceId)}/sync-requests`,
    'POST',
    {
      clan_tag: clanTag,
      resource_types: resourceTypes,
      period: period || null,
      trigger
    },
    true
  )
}

export function createAllianceShare(allianceId, expiresDays = 30, shareType = 'invite') {
  return request(`/api/alliances/${encodeURIComponent(allianceId)}/shares`, 'POST', {
    expires_days: expiresDays,
    share_type: shareType
  }, true)
}

export function getAllianceShares(allianceId) {
  return request(`/api/alliances/${encodeURIComponent(allianceId)}/shares`, 'GET', {}, true)
}

export function revokeAllianceShare(allianceId, linkId) {
  return request(`/api/alliances/${encodeURIComponent(allianceId)}/shares/${encodeURIComponent(linkId)}`, 'DELETE', {}, true)
}

export function previewAllianceShare(token) {
  return request('/api/alliance-shares/preview', 'POST', { token })
}

export function joinAllianceShare(token) {
  return request('/api/alliance-shares/join', 'POST', { token }, true)
}

export function openAllianceShare(token) {
  return request('/api/alliance-shares/open', 'POST', { token }, true)
}

export function requestAllianceJoin(allianceId) {
  return request(`/api/alliances/${encodeURIComponent(allianceId)}/join-requests`, 'POST', {}, true)
}

export function getAllianceJoinRequests(allianceId) {
  return request(`/api/alliances/${encodeURIComponent(allianceId)}/join-requests`, 'GET', {}, true)
}

export function reviewAllianceJoinRequest(allianceId, requestId, action) {
  return request(
    `/api/alliances/${encodeURIComponent(allianceId)}/join-requests/${encodeURIComponent(requestId)}`,
    'PATCH',
    { action },
    true
  )
}

export function deleteAllianceHistory(allianceId) {
  return request(`/api/me/alliance-history/${encodeURIComponent(allianceId)}`, 'DELETE', {}, true)
}

export function getAllianceUserMembers(allianceId) {
  return request(`/api/alliances/${encodeURIComponent(allianceId)}/user-members`, 'GET', {}, true)
}

export function addAllianceUserMember(allianceId, openid, role = 'member') {
  return request(`/api/alliances/${encodeURIComponent(allianceId)}/user-members`, 'POST', { openid, role }, true)
}

export function updateAllianceUserRole(allianceId, memberId, role) {
  return request(`/api/alliances/${encodeURIComponent(allianceId)}/user-members/${encodeURIComponent(memberId)}`, 'PATCH', { role }, true)
}

export function removeAllianceUser(allianceId, memberId, block = false) {
  return request(`/api/alliances/${encodeURIComponent(allianceId)}/user-members/${encodeURIComponent(memberId)}?block=${block ? 'true' : 'false'}`, 'DELETE', {}, true)
}

export function leaveAlliance(allianceId) {
  return request(`/api/alliances/${encodeURIComponent(allianceId)}/leave`, 'POST', {}, true)
}

export function getPlatformCapability() {
  return request('/api/platform/capability', 'GET', {}, true)
}

export function getPlatformAlliances(search = '') {
  const query = search ? `?search=${encodeURIComponent(search)}` : ''
  return request(`/api/platform/alliances${query}`, 'GET', {}, true)
}

export function createPlatformAlliance(name) {
  return request('/api/platform/alliances', 'POST', { name }, true)
}

export function getPlatformAlliance(allianceId) {
  return request(`/api/platform/alliances/${encodeURIComponent(allianceId)}`, 'GET', {}, true)
}

export function renamePlatformAlliance(allianceId, name) {
  return request(`/api/platform/alliances/${encodeURIComponent(allianceId)}`, 'PATCH', { name }, true)
}

export function addPlatformAllianceMember(allianceId, openid, role = 'member') {
  return request(`/api/platform/alliances/${encodeURIComponent(allianceId)}/members`, 'POST', { openid, role }, true)
}

export function updatePlatformAllianceMemberRole(allianceId, memberId, role) {
  return request(`/api/platform/alliances/${encodeURIComponent(allianceId)}/members/${encodeURIComponent(memberId)}`, 'PATCH', { role }, true)
}

export function removePlatformAllianceMember(allianceId, memberId) {
  return request(`/api/platform/alliances/${encodeURIComponent(allianceId)}/members/${encodeURIComponent(memberId)}`, 'DELETE', {}, true)
}

export function getPlatformManagedClans(allianceId) {
  return request(`/api/platform/alliances/${encodeURIComponent(allianceId)}/managed-clans`, 'GET', {}, true)
}

export function addPlatformManagedClan(allianceId, payload) {
  return request(`/api/platform/alliances/${encodeURIComponent(allianceId)}/managed-clans`, 'POST', payload, true)
}

export function updatePlatformManagedClan(allianceId, clanTag, payload) {
  return request(`/api/platform/alliances/${encodeURIComponent(allianceId)}/managed-clans/${encodeURIComponent(clanTag)}`, 'PATCH', payload, true)
}

export function reorderPlatformManagedClans(allianceId, clanTags) {
  return request(`/api/platform/alliances/${encodeURIComponent(allianceId)}/managed-clans/order`, 'PUT', { clan_tags: clanTags }, true)
}

export function removePlatformManagedClan(allianceId, clanTag) {
  return request(`/api/platform/alliances/${encodeURIComponent(allianceId)}/managed-clans/${encodeURIComponent(clanTag)}`, 'DELETE', {}, true)
}

export function savePlatformFreeRegistration(enabled, limit) {
  return request('/api/platform/settings/free-registration', 'PUT', {
    free_registration_enabled: Boolean(enabled),
    free_registration_limit: Number(limit)
  }, true)
}

export function savePlatformVerification(allianceId, clanTag, status, note = '') {
  return request(`/api/platform/alliances/${encodeURIComponent(allianceId)}/verification`, 'PUT', {
    clan_tag: clanTag, status, note
  }, true)
}

export function savePlatformPlan(allianceId, planCode, expiresAt, note = '') {
  return request(`/api/platform/alliances/${encodeURIComponent(allianceId)}/plan`, 'PUT', {
    plan_code: planCode, expires_at: expiresAt || null, note
  }, true)
}

export function savePlatformAllianceStatus(allianceId, status, note = '') {
  return request(`/api/platform/alliances/${encodeURIComponent(allianceId)}/status`, 'PUT', { status, note }, true)
}

export function deletePlatformAlliance(allianceId, confirmationName) {
  const query = `?confirmation_name=${encodeURIComponent(confirmationName || '')}`
  return request(`/api/platform/alliances/${encodeURIComponent(allianceId)}${query}`, 'DELETE', {}, true)
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
  if (!scoped) return missingAlliance()
  return request(`${scoped}?${query.join('&')}`, 'GET', {}, true)
}

/** 获取全部自有部落的概览卡片。 */
export function getClanOverview(allianceId) {
  const scoped = scopedPath('/clans', allianceId)
  return scoped ? request(scoped, 'GET', {}, true) : missingAlliance()
}

/** 获取单个自有部落的聚合详情。 */
export function getClanOverviewDetail(clanTag) {
  const scoped = scopedPath(`/clans/${encodeURIComponent(clanTag)}`)
  return scoped
    ? request(scoped, 'GET', {}, true)
    : missingAlliance()
}

/**
 * 获取联赛战绩统计（滚动窗口三星率）
 * @param {string} period - 基准月份 YYYY-MM，不传则自动取当前 CWL 月份
 * @returns {Promise} { period, updated_at, stats: [{ player_tag, account_name, town_hall_level, offense_1m, ... }] }
 */
export function getLeagueStats(period) {
  const query = period ? `?period=${period}` : ''
  const scoped = scopedPath('/league-stats')
  return scoped ? request(`${scoped}${query}`, 'GET', {}, true) : missingAlliance()
}

/**
 * 获取部落战战绩统计（按场次滚动窗口三星率）
 * @param {string} clanTag - 自有部落标签；不传时保留战营默认值
 * @returns {Promise} { clan_tag, updated_at, history_coverage, stats: [{ player_tag, account_name, town_hall_level, offense_5, ... }] }
 */
export function getWarStats(clanTag) {
  const query = clanTag ? `?clan_tag=${encodeURIComponent(clanTag)}` : ''
  const scoped = scopedPath('/war-stats')
  return scoped ? request(`${scoped}${query}`, 'GET', {}, true) : missingAlliance()
}

/**
 * 获取互刷部落配置及清退辅助名单。
 * @returns {Promise} { clans: [{ clan_tag, realtime, despeed, replace_candidates, fill_accounts, inactive_members }] }
 */
export function getFarmConfig() {
  const scoped = scopedPath('/farm-config')
  return scoped ? request(scoped, 'GET', {}, true) : missingAlliance()
}

/** 获取全部自有部落的当前战争摘要。 */
export function getCurrentWars() {
  const scoped = scopedPath('/wars/current')
  return scoped ? request(scoped, 'GET', {}, true) : missingAlliance()
}

/** 获取单个自有部落的当前战争详情。 */
export function getCurrentWar(clanTag) {
  const scoped = scopedPath(`/wars/current/${encodeURIComponent(clanTag)}`)
  return scoped
    ? request(scoped, 'GET', {}, true)
    : missingAlliance()
}

/** 获取全部自有部落最近 15 场已结束普通部落战摘要。 */
export function getWarHistory(clanTag) {
  const query = clanTag ? `?clan_tag=${encodeURIComponent(clanTag)}` : ''
  const scoped = scopedPath('/wars/history')
  return scoped ? request(`${scoped}${query}`, 'GET', {}, true) : missingAlliance()
}

/** 获取一场已归档普通部落战的完整详情。 */
export function getWarHistoryDetail(clanTag, warKey) {
  const suffix = `/wars/history/${encodeURIComponent(clanTag)}/${encodeURIComponent(warKey)}`
  const scoped = scopedPath(suffix)
  return scoped
    ? request(scoped, 'GET', {}, true)
    : missingAlliance()
}

/** 获取当前月份 CWL 参赛部落摘要。 */
export function getCwlLive(period) {
  const query = period ? `?period=${encodeURIComponent(period)}` : ''
  const scoped = scopedPath('/cwl/live')
  return scoped ? request(`${scoped}${query}`, 'GET', {}, true) : missingAlliance()
}

/** 获取当月各联赛队伍的当前战斗日未出刀成员及已结束场次漏刀记录。 */
export function getCwlCheckIn() {
  const scoped = scopedPath('/cwl/check-in')
  return scoped ? request(scoped, 'GET', {}, true) : missingAlliance()
}

/** 获取当月联赛正式名单与到位情况汇总。 */
export function getCwlAssembly() {
  const scoped = scopedPath('/cwl/assembly')
  return scoped ? request(scoped, 'GET', {}, true) : missingAlliance()
}

/** 获取单个联赛部落的集结检查详情。 */
export function getCwlAssemblyDetail(clanTag) {
  const scoped = scopedPath(`/cwl/assembly/${encodeURIComponent(clanTag)}`)
  return scoped ? request(scoped, 'GET', {}, true) : missingAlliance()
}

/** 按需获取单个联赛部落的战斗日或联赛总览。 */
export function getCwlLiveDetail(clanTag, period, round, view) {
  const query = []
  if (period) query.push(`period=${encodeURIComponent(period)}`)
  if (round) query.push(`round=${encodeURIComponent(round)}`)
  if (view) query.push(`view=${encodeURIComponent(view)}`)
  const scoped = scopedPath(`/cwl/live/${encodeURIComponent(clanTag)}`)
  if (!scoped) return missingAlliance()
  return request(`${scoped}${query.length ? '?' + query.join('&') : ''}`, 'GET', {}, true)
}

/** 读取当前联盟的月度联赛配置。普通联盟与平台管理使用独立入口。 */
function cwlSeasonPath(period) {
  return scopedPath(`/cwl/seasons/${encodeURIComponent(period)}`)
}

function platformCwlSeasonPath(allianceId, period) {
  return `/api/platform/alliances/${encodeURIComponent(allianceId)}/cwl/seasons/${encodeURIComponent(period)}`
}

export function getAllianceCwlSeason(period) {
  const scoped = cwlSeasonPath(period)
  if (!scoped) return Promise.reject(new Error('请先选择联盟'))
  return request(scoped, 'GET', {}, true)
}

/** 创建当前联盟的月度联赛配置。 */
export function createAllianceCwlSeason(period) {
  const scoped = cwlSeasonPath(period)
  if (!scoped) return Promise.reject(new Error('请先选择联盟'))
  return request(scoped, 'POST', {}, true)
}

export function copyPreviousAllianceCwlSeason(period) {
  const base = cwlSeasonPath(period)
  const scoped = base ? `${base}/copy-previous` : ''
  if (!scoped) return Promise.reject(new Error('请先选择联盟'))
  return request(scoped, 'POST', {}, true)
}

export function addAllianceCwlTeam(period, payload) {
  const base = cwlSeasonPath(period)
  const scoped = base ? `${base}/teams` : ''
  if (!scoped) return Promise.reject(new Error('请先选择联盟'))
  return request(scoped, 'POST', payload, true)
}

export function updateAllianceCwlTeam(period, teamId, payload) {
  const base = cwlSeasonPath(period)
  const scoped = base ? `${base}/teams/${teamId}` : ''
  if (!scoped) return Promise.reject(new Error('请先选择联盟'))
  return request(scoped, 'PUT', payload, true)
}

export function deleteAllianceCwlTeam(period, teamId) {
  const base = cwlSeasonPath(period)
  const scoped = base ? `${base}/teams/${teamId}` : ''
  if (!scoped) return Promise.reject(new Error('请先选择联盟'))
  return request(scoped, 'DELETE', {}, true)
}

/** 联赛组已发现后，通过留痕操作纠正队伍 Tag。 */
export function correctAllianceCwlTeamTag(period, teamId, payload) {
  const scoped = scopedPath(`/cwl/seasons/${encodeURIComponent(period)}/teams/${teamId}/correct-tag`)
  if (!scoped) return Promise.reject(new Error('请先选择联盟'))
  return request(scoped, 'POST', payload, true)
}

/** 已冻结或结束月份的联赛队伍留痕编辑。 */
export function amendAllianceCwlTeam(period, teamId, payload) {
  const base = cwlSeasonPath(period)
  const scoped = base ? `${base}/teams/${teamId}/amend` : ''
  if (!scoped) return Promise.reject(new Error('请先选择联盟'))
  return request(scoped, 'PUT', payload, true)
}

export function confirmAllianceCwlSeason(period) {
  const base = cwlSeasonPath(period)
  const scoped = base ? `${base}/confirm` : ''
  if (!scoped) return Promise.reject(new Error('请先选择联盟'))
  return request(scoped, 'POST', {}, true)
}

export function getPlatformAllianceCwlSeason(allianceId, period) {
  return request(platformCwlSeasonPath(allianceId, period), 'GET', {}, true)
}

export function createPlatformAllianceCwlSeason(allianceId, period) {
  return request(platformCwlSeasonPath(allianceId, period), 'POST', {}, true)
}

export function copyPreviousPlatformAllianceCwlSeason(allianceId, period) {
  return request(`${platformCwlSeasonPath(allianceId, period)}/copy-previous`, 'POST', {}, true)
}

export function addPlatformAllianceCwlTeam(allianceId, period, payload) {
  return request(`${platformCwlSeasonPath(allianceId, period)}/teams`, 'POST', payload, true)
}

export function updatePlatformAllianceCwlTeam(allianceId, period, teamId, payload) {
  return request(`${platformCwlSeasonPath(allianceId, period)}/teams/${teamId}`, 'PUT', payload, true)
}

export function deletePlatformAllianceCwlTeam(allianceId, period, teamId) {
  return request(`${platformCwlSeasonPath(allianceId, period)}/teams/${teamId}`, 'DELETE', {}, true)
}

export function amendPlatformAllianceCwlTeam(allianceId, period, teamId, payload) {
  return request(`${platformCwlSeasonPath(allianceId, period)}/teams/${teamId}/amend`, 'PUT', payload, true)
}

export function confirmPlatformAllianceCwlSeason(allianceId, period) {
  return request(`${platformCwlSeasonPath(allianceId, period)}/confirm`, 'POST', {}, true)
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
  amendAllianceCwlTeam,
  confirmAllianceCwlSeason
}
