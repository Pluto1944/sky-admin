import { getMyAlliances, visitAlliance } from './api.js'
import {
  ALLIANCE_CHANGED_EVENT,
  clearCurrentAlliance,
  getCurrentAlliance,
  getCurrentAllianceId,
  setCurrentAlliance
} from './alliance-state.js'

export { ALLIANCE_CHANGED_EVENT, getCurrentAlliance, getCurrentAllianceId }

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
    return { alliances: [], current: null }
  }
  const response = await getMyAlliances()
  const alliances = response.alliances || []
  const requestedId = Number(preferredId || getCurrentAllianceId())
  const current = alliances.find(item => Number(item.id) === requestedId) ||
    alliances.find(item => item.is_default) || alliances[0] || null
  if (current) rememberAlliance(current, emitChange)
  else clearAllianceContext()
  return { alliances, current }
}

export async function selectAlliance(allianceId) {
  if (!tokenExists()) throw new Error('登录后才能切换联盟')
  const selected = await visitAlliance(Number(allianceId))
  rememberAlliance(selected, true)
  return selected
}

export async function activateSharedAlliance(options) {
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

export function allianceQuery() {
  const id = getCurrentAllianceId()
  return id ? `alliance_id=${encodeURIComponent(id)}` : ''
}
