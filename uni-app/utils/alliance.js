import {
  createAllianceShare,
  getMyAlliances,
  joinAllianceShare,
  openAllianceShare,
  previewAllianceShare,
  visitAlliance
} from './api.js'
import {
  ALLIANCE_CHANGED_EVENT,
  clearCurrentAlliance,
  getCurrentAlliance,
  getCurrentAllianceId,
  setCurrentAlliance
} from './alliance-state.js'

export { ALLIANCE_CHANGED_EVENT, getCurrentAlliance, getCurrentAllianceId }

export const ALLIANCE_SHARE_READY_EVENT = 'alliance-share-ready'

const PENDING_SHARE_KEY = 'pendingAllianceShareToken'
const SHARE_TOKEN_CACHE_KEY = 'allianceShareTokens'
const LOCAL_HISTORY_KEY = 'localAllianceHistory'

export function isSkyAlliance() {
  const current = getCurrentAlliance()
  return Boolean(current && current.key === 'sky-internal')
}

function tokenExists() {
  return Boolean(uni.getStorageSync('token'))
}

function rememberAlliance(alliance, emitChange) {
  if (!alliance || !alliance.id) return null
  const previousId = getCurrentAllianceId()
  setCurrentAlliance(alliance)
  if (emitChange && Number(previousId) !== Number(alliance.id)) {
    uni.$emit(ALLIANCE_CHANGED_EVENT, alliance)
  }
  return alliance
}

export function clearAllianceContext() {
  clearCurrentAlliance()
}

function visitorAlliance(preview) {
  return {
    id: Number(preview.alliance_id),
    key: '',
    name: preview.name,
    role: 'visitor',
    role_label: '浏览',
    relationship: 'visited',
    clan_count: Number(preview.clan_count || 0),
    plan: { name: preview.plan_name || '' },
    last_visited_at: new Date().toISOString()
  }
}

function localHistory() {
  const value = uni.getStorageSync(LOCAL_HISTORY_KEY)
  return Array.isArray(value) ? value : []
}

function rememberLocalVisit(alliance) {
  if (!alliance || !alliance.id) return
  const items = localHistory().filter(item => Number(item.id) !== Number(alliance.id))
  items.unshift({ ...alliance, last_visited_at: new Date().toISOString() })
  uni.setStorageSync(LOCAL_HISTORY_KEY, items.slice(0, 50))
}

function confirmInvitation(allianceName) {
  return new Promise(resolve => {
    uni.showModal({
      title: '加入联盟邀请',
      content: `是否以普通成员身份加入${allianceName || '该联盟'}？`,
      confirmText: '加入',
      success: result => resolve(Boolean(result.confirm)),
      fail: () => resolve(false)
    })
  })
}

export async function loadAllianceContext(preferredId, emitChange = false) {
  if (!tokenExists()) {
    const browsed = localHistory()
    const requestedId = Number(preferredId || getCurrentAllianceId())
    const current = browsed.find(item => Number(item.id) === requestedId) || browsed[0] || getCurrentAlliance()
    if (current) rememberAlliance(current, emitChange)
    return { alliances: [], browsedAlliances: browsed, hiddenAlliances: [], current: current || null, features: {} }
  }
  const response = await getMyAlliances()
  const alliances = response.alliances || []
  const browsedAlliances = response.browsed_alliances || []
  const hiddenAlliances = response.hidden_alliances || []
  const requestedId = Number(preferredId || getCurrentAllianceId())
  const available = alliances.concat(browsedAlliances)
  const current = available.find(item => Number(item.id) === requestedId) ||
    available.find(item => item.is_default) || alliances[0] || browsedAlliances[0] || null
  if (current) rememberAlliance(current, emitChange)
  else clearAllianceContext()
  return { alliances, browsedAlliances, hiddenAlliances, current, features: response.features || {} }
}

export async function selectAlliance(allianceId) {
  if (!tokenExists()) throw new Error('登录后才能切换联盟')
  const selected = await visitAlliance(Number(allianceId))
  rememberAlliance(selected, true)
  return selected
}

export function selectLocalAlliance(alliance) {
  if (!alliance || !alliance.id) throw new Error('联盟记录无效')
  rememberAlliance(alliance, true)
  rememberLocalVisit(alliance)
  return alliance
}

export async function activateSharedAlliance(options) {
  let shareToken = ''
  try { shareToken = decodeURIComponent((options && options.share_token) || '') } catch (e) { shareToken = (options && options.share_token) || '' }
  if (shareToken) {
    uni.setStorageSync(PENDING_SHARE_KEY, shareToken)
    const preview = await previewAllianceShare(shareToken)
    const publicAlliance = visitorAlliance(preview)
    rememberAllianceShareToken(preview.alliance_id, shareToken, preview.expires_at, preview.share_type)
    rememberLocalVisit(publicAlliance)
    if (!tokenExists()) {
      rememberAlliance(publicAlliance, true)
      return { alliances: [], browsedAlliances: localHistory(), current: publicAlliance, features: {} }
    }
    const opened = await openAllianceShare(shareToken)
    if (preview.can_join && await confirmInvitation(preview.name)) {
      await joinAllianceShare(shareToken)
    }
    uni.removeStorageSync(PENDING_SHARE_KEY)
    const loaded = await loadAllianceContext(opened.alliance_id, true)
    if (loaded.current && Number(loaded.current.id) === Number(opened.alliance_id)) {
      loaded.current = await selectAlliance(opened.alliance_id)
    }
    return loaded
  }
  const value = options && Number(options.alliance_id)
  if (!value || !tokenExists()) return loadAllianceContext(null, true)
  // 分享页进入时必须通知 TopBar 和已挂载组件，否则页面数据已切换而顶部仍显示旧联盟。
  const loaded = await loadAllianceContext(value, true)
  if (!loaded.current || Number(loaded.current.id) !== value) {
    throw new Error('你还不是该联盟成员')
  }
  if (Number(getCurrentAllianceId()) !== value || !loaded.current.is_default) {
    loaded.current = await selectAlliance(value)
  }
  return loaded
}

export async function acceptPendingAllianceShare() {
  const token = uni.getStorageSync(PENDING_SHARE_KEY)
  if (!token || !tokenExists()) return null
  const preview = await previewAllianceShare(token)
  const opened = await openAllianceShare(token)
  let joined = false
  if (preview.can_join && await confirmInvitation(preview.name)) {
    await joinAllianceShare(token)
    joined = true
  }
  uni.removeStorageSync(PENDING_SHARE_KEY)
  const loaded = await loadAllianceContext(opened.alliance_id, true)
  if (loaded.current) loaded.current = await selectAlliance(opened.alliance_id)
  return { ...opened, joined, alliance: loaded.current }
}

export async function acceptAllianceInvitation(token) {
  if (!tokenExists()) throw new Error('请先登录后接受邀请')
  const joined = await joinAllianceShare(token)
  const loaded = await loadAllianceContext(joined.alliance_id, true)
  if (loaded.current) loaded.current = await selectAlliance(joined.alliance_id)
  return { ...joined, alliance: loaded.current }
}

export function allianceQuery() {
  const id = getCurrentAllianceId()
  if (!id) return ''
  const query = [`alliance_id=${encodeURIComponent(id)}`]
  const cache = uni.getStorageSync(SHARE_TOKEN_CACHE_KEY) || {}
  const item = cache[String(id)]
  if (item && item.shareType === 'browse' && item.token && item.expiresAt && Date.parse(item.expiresAt) > Date.now()) {
    query.push(`share_token=${encodeURIComponent(item.token)}`)
  }
  return query.join('&')
}

export function rememberAllianceShareToken(allianceId, token, expiresAt, shareType = '') {
  if (!allianceId || !token || !expiresAt) return
  const cache = uni.getStorageSync(SHARE_TOKEN_CACHE_KEY) || {}
  cache[String(allianceId)] = { token, expiresAt, shareType }
  uni.setStorageSync(SHARE_TOKEN_CACHE_KEY, cache)
}

export async function ensureBrowseShareToken(allianceId) {
  if (!allianceId || !tokenExists()) return null
  const cache = uni.getStorageSync(SHARE_TOKEN_CACHE_KEY) || {}
  const existing = cache[String(allianceId)]
  if (existing && existing.token && existing.shareType === 'browse' && Date.parse(existing.expiresAt) > Date.now()) {
    return existing
  }
  const created = await createAllianceShare(allianceId, 7, 'browse')
  cache[String(allianceId)] = {
    token: created.token,
    expiresAt: created.expires_at,
    shareType: 'browse'
  }
  uni.setStorageSync(SHARE_TOKEN_CACHE_KEY, cache)
  return cache[String(allianceId)]
}
