/**
 * API 请求封装
 * 统一管理后端接口调用，自动携带 token
 */

// 后端 API 基地址
// 备案完成前临时用 IP 访问
const BASE_URL = 'https://115.159.64.19'

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
 * 获取成员列表
 * @returns {Promise} { count, members }
 */
export function getMembers() {
  return request('/api/members')
}

/**
 * 获取联赛战绩统计（滚动窗口三星率）
 * @param {string} period - 基准月份 YYYY-MM，不传则自动取当前 CWL 月份
 * @returns {Promise} { period, stats: [{ player_tag, account_name, town_hall_level, offense_1m, ... }] }
 */
export function getLeagueStats(period) {
  const query = period ? `?period=${period}` : ''
  return request(`/api/clan/league-stats${query}`)
}

/**
 * 获取部落战战绩统计（按场次滚动窗口三星率）
 * @returns {Promise} { period, stats: [{ player_tag, account_name, town_hall_level, offense_5, ... }] }
 */
export function getWarStats() {
  return request('/api/clan/war-stats')
}

export default {
  wechatLogin,
  getMyInfo,
  bindAccount,
  getMembers,
  getLeagueStats,
  getWarStats
}
