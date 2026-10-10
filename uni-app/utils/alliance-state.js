export const ALLIANCE_ID_KEY = 'currentAllianceId'
export const ALLIANCE_CHANGED_EVENT = 'alliance-changed'

let currentAlliance = null

export function getCurrentAllianceId() {
  const value = Number(uni.getStorageSync(ALLIANCE_ID_KEY))
  return value > 0 ? value : 0
}

export function getCurrentAlliance() {
  return currentAlliance
}

export function getCurrentAllianceKey() {
  return currentAlliance ? currentAlliance.key : ''
}

export function setCurrentAlliance(alliance) {
  currentAlliance = alliance || null
  if (currentAlliance && currentAlliance.id) uni.setStorageSync(ALLIANCE_ID_KEY, currentAlliance.id)
}

export function clearCurrentAlliance() {
  currentAlliance = null
  uni.removeStorageSync(ALLIANCE_ID_KEY)
}
