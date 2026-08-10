<script>
export default {
  onLaunch() {
    console.log('App Launch')
    // 启动时验证 token 是否有效
    const token = uni.getStorageSync('token')
    if (token) {
      this.checkLoginStatus()
    }
  },
  onShow() {
    console.log('App Show')
  },
  onHide() {
    console.log('App Hide')
  },
  methods: {
    checkLoginStatus() {
      uni.request({
        url: this.globalData.apiBase + '/api/wechat/me',
        header: {
          'Authorization': 'Bearer ' + uni.getStorageSync('token')
        },
        success: (res) => {
          if (res.statusCode === 200) {
            this.globalData.userInfo = res.data
            this.globalData.isLoggedIn = true
          } else {
            uni.removeStorageSync('token')
            this.globalData.isLoggedIn = false
          }
        },
        fail: () => {
          this.globalData.isLoggedIn = false
        }
      })
    }
  },
  globalData: {
    apiBase: 'https://api.skycoc.cc',
    userInfo: null,
    isLoggedIn: false
  }
}
</script>

<style>
/* 全局样式 */
page {
  background-color: #0f0f23;
  color: #e0e0e0;
  font-family: -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Helvetica, 'Segoe UI', Arial, sans-serif;
  min-height: 100vh;
}

/* 主题色变量 */
:root {
  --primary-color: #4a90d9;
  --primary-dark: #3a7bc8;
  --bg-dark: #0f0f23;
  --bg-card: #1a1a2e;
  --bg-card-hover: #252545;
  --text-primary: #e0e0e0;
  --text-secondary: #8890a0;
  --text-accent: #f0c060;
  --border-color: #2a2a4a;
  --success-color: #5cb85c;
  --danger-color: #d9534f;
  --warning-color: #f0ad4e;
}
</style>
