import { getMyAlliances, joinAllianceShare, previewAllianceShare, visitAlliance } from './api.js'
import {
  ALLIANCE_CHANGED_EVENT,
  clearCurrentAlliance,
  getCurrentAlliance,
  getCurrentAllianceId,
  setCurrentAlliance
} from './alliance-state.js'

export { ALLIANCE_CHANGED_EVENT, getCurrentAlliance, getCurrentAllianceId }

const PENDING_SHARE_KEY = 'pendingAllianceShareToken'
const SHARE_TOKEN_CACHE_KEY = 'allianceShareTokens'

export function isSkyAlliance() {
  const current = getCurrentAlliance()
  // 无联盟上下文时保留旧版默认行为；已选择联盟后严格按 key 判断。
  return !current || current.key === 'sky-internal'
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

export async function loadAllianceContext(preferredId, emitChange = false) {
  if (!tokenExists()) {
    clearAllianceContext()
    return { alliances: [], hiddenAlliances: [], current: null, features: {} }
  }
  const response = await getMyAlliances()
  const alliances = response.alliances || []
  const hiddenAlliances = response.hidden_alliances || []
  const requestedId = Number(preferredId || getCurrentAllianceId())
  const current = alliances.find(item => Number(item.id) === requestedId) ||
    alliances.find(item => item.is_default) || alliances[0] || null
  if (current) rememberAlliance(current, emitChange)
  else clearAllianceContext()
  return { alliances, hiddenAlliances, current, features: response.features || {} }
}

export async function selectAlliance(allianceId) {
  if (!tokenExists()) throw new Error('登录后才能切换联盟')
  const selected = await visitAlliance(Number(allianceId))
  rememberAlliance(selected, true)
  return selected
}

export async function activateSharedAlliance(options) {
  let shareToken = ''
  try { shareToken = decodeURIComponent((options && options.share_token) || '') } catch (e) { shareToken = (options && options.share_token) || '' }
  if (shareToken) {
    uni.setStorageSync(PENDING_SHARE_KEY, shareToken)
    if (!tokenExists()) {
      let preview = null
      try { preview = await previewAllianceShare(shareToken) } catch (e) {}
      uni.switchTab({ url: '/pages/settings/settings' })
      throw new Error(preview ? `登录后加入${preview.name}` : '请先登录后加入联盟')
    }
    const joined = await joinAllianceShare(shareToken)
    uni.removeStorageSync(PENDING_SHARE_KEY)
    const loaded = await loadAllianceContext(joined.alliance_id, true)
    if (loaded.current && Number(loaded.current.id) === Number(joined.alliance_id)) {
      loaded.current = await selectAlliance(joined.alliance_id)
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
  const joined = await joinAllianceShare(token)
  uni.removeStorageSync(PENDING_SHARE_KEY)
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
  if (item && item.token && item.expiresAt && Date.parse(item.expiresAt) > Date.now()) {
    query.push(`share_token=${encodeURIComponent(item.token)}`)
  }
  return query.join('&')
}

export function rememberAllianceShareToken(allianceId, token, expiresAt) {
  if (!allianceId || !token || !expiresAt) return
  const cache = uni.getStorageSync(SHARE_TOKEN_CACHE_KEY) || {}
  cache[String(allianceId)] = { token, expiresAt }
  uni.setStorageSync(SHARE_TOKEN_CACHE_KEY, cache)
}
