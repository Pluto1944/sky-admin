# uni-app 微信小程序文档

## 概述

`uni-app/` 是基于 [uni-app](https://uniapp.dcloud.net.cn/) 框架开发的微信小程序，为"苍穹联赛"提供移动端管理入口。支持微信一键登录、游戏账号绑定、成员查看等功能。

- **AppID**: `wx6a46dda85a013a34`
- **框架**: uni-app (Vue 2)
- **后端 API**: `https://api.skycoc.cc`（备案通过前临时使用 `https://115.159.64.19`）
- **UI 主题**: 暗色风格
- **备案状态**: ⏳ 等待 ICP 备案通过

---

## 文件结构

```
uni-app/
├── manifest.json              # 小程序配置（AppID、权限等）
├── pages.json                 # 页面路由配置
├── App.vue                    # 应用入口（全局样式、登录状态检查）
├── main.js                    # Vue 入口
├── uni.scss                   # 主题色变量
├── package.json               # Node.js 依赖 + 编译脚本
├── vue.config.js              # Webpack 构建配置（UNI_INPUT_DIR、输出目录）
├── postcss.config.js          # PostCSS 配置
├── pages/
│   ├── login/
│   │   └── login.vue          # 微信登录页
│   ├── bind/
│   │   └── bind.vue           # 游戏账号绑定页
│   └── index/
│       └── index.vue          # 首页（用户信息 + 功能入口）
├── utils/
│   └── api.js                 # API 请求封装
├── patches/
│   └── apply-patches.sh       # 依赖补丁脚本
├── dist/                      # 编译产物（不提交 git）
│   └── build/mp-weixin/       # 微信小程序原生代码
├── sync-to-local.sh           # Mac 本地同步脚本
└── .gitignore
```

---

## 页面说明

### 1. 登录页 (`pages/login/login`)

**路由**: `/pages/login/login`

**功能**：
- 展示 App 名称和品牌标识
- 点击"微信一键登录"按钮 → 调用 `wx.login()` 获取 code
- 用 code 调用后端 `POST /api/wechat/login` 换取 JWT token
- 登录成功后将 token 存入 `uni.storage`
- 首次登录（未绑定账号）→ 自动跳转绑定页
- 已绑定用户 → 跳转首页

**状态处理**：
| 场景 | 行为 |
|------|------|
| 登录成功 + 未绑定 | → 跳转绑定页 `/pages/bind/bind` |
| 登录成功 + 已绑定 | → 跳转首页 `/pages/index/index` |
| 登录失败 | 弹窗提示错误信息 |
| 非微信环境 | 提示"请在小程序环境中运行" |

---

### 2. 绑定页 (`pages/bind/bind`)

**路由**: `/pages/bind/bind`

**功能**：
- 填写游戏昵称 (`account_name`)
- 填写玩家标签 (`player_tag`，如 `#ABC123`)
- 至少填一项即可提交
- 调用 `POST /api/wechat/bind` 绑定
- 支持"暂不绑定，先看看"跳过

**表单校验**：
- 两项都为空 → Toast 提示"请至少填写一项"
- `player_tag` 不以 `#` 开头 → 弹窗确认后仍可提交
- 昵称最大 30 字符，标签最大 15 字符

---

### 3. 首页 (`pages/index/index`)

**路由**: `/pages/index/index`

**功能**：
- 展示用户信息卡片（昵称、游戏账号、角色）
- 功能入口菜单：
  - 👥 成员列表（待开发）
  - 🔗 绑定/修改游戏账号
- 退出登录（清除 token + 跳转登录页）
- `onShow` 时自动刷新用户信息（`GET /api/wechat/me`）

---

## API 封装 (`utils/api.js`)

统一封装后端 API 调用，提供以下特性：

- **自动携带 token**: `needAuth=true` 时自动从 `uni.storage` 读取 token 并放入 `Authorization` header
- **401 自动处理**: token 过期/无效时自动清除本地状态并跳转登录页
- **统一错误提示**: 网络错误、业务错误统一处理

### 导出的方法

| 方法 | 对应接口 | 需要认证 |
|------|---------|---------|
| `wechatLogin(code)` | `POST /api/wechat/login` | ❌ |
| `getMyInfo()` | `GET /api/wechat/me` | ✅ |
| `bindAccount(name, tag)` | `POST /api/wechat/bind` | ✅ |
| `getMembers()` | `GET /api/members` | ❌ |

### 使用示例

```javascript
import { wechatLogin, getMyInfo, bindAccount } from '@/utils/api.js'

// 登录
const res = await wechatLogin(code)
uni.setStorageSync('token', res.token)

// 获取用户信息
const user = await getMyInfo()

// 绑定账号
await bindAccount('玩家昵称', '#ABC123')
```

---

## 全局状态管理

通过 `App.vue` 的 `globalData` 管理：

```javascript
globalData: {
  apiBase: 'https://api.skycoc.cc',  // 后端 API 地址
  userInfo: null,                      // 当前用户信息
  isLoggedIn: false                    // 登录状态
}
```

页面中通过 `getApp().globalData` 访问。

---

## 主题色

暗色主题，变量定义在 `uni.scss` 和 `App.vue` 的 `:root` 中：

| 变量 | 色值 | 用途 |
|------|------|------|
| `--primary-color` | `#4a90d9` | 主色调（按钮、链接） |
| `--bg-dark` | `#0f0f23` | 页面背景 |
| `--bg-card` | `#1a1a2e` | 卡片背景 |
| `--text-primary` | `#e0e0e0` | 主要文字 |
| `--text-secondary` | `#8890a0` | 次要文字 |
| `--text-accent` | `#f0c060` | 强调文字 |
| `--border-color` | `#2a2a4a` | 边框颜色 |
| `--success-color` | `#5cb85c` | 成功/微信绿 |
| `--danger-color` | `#d9534f` | 错误/危险 |

---

## 备案状态

> ⚠️ **当前域名 `api.skycoc.cc` 尚未通过 ICP 备案**，腾讯云会拦截对该域名的 HTTP/HTTPS 请求。
>
> **备案通过前**：前端代码使用 `https://115.159.64.19`（IP 直连），Nginx 已配置 IP 访问的 server 块。
> **备案通过后**：需要将前端代码中的 `115.159.64.19` 改回 `api.skycoc.cc`，详见 [备案通过后操作](#备案通过后操作)。

---

## 开发环境搭建

### 整体架构

代码存放在远程 Linux 服务器上，通过 VS Code Remote SSH 编辑。编译在服务器端完成，编译产物（微信小程序原生代码）同步到本地 Mac，再用微信开发者工具打开调试。

```
┌─ 远程服务器 (Linux) ─────────────────────┐
│                                            │
│  uni-app/  (Vue 2 源码)                    │
│     │  npm run build:mp-weixin             │
│     ▼                                      │
│  dist/build/mp-weixin/  (小程序产物)        │
│     │  rsync                               │
└─────┼──────────────────────────────────────┘
      │
      ▼
┌─ 本地 Mac ────────────────────────────────┐
│  ~/Desktop/project/code/uni-app-dist/     │
│     │                                       │
│     ▼                                       │
│  微信开发者工具 (编译 + 预览 + 真机调试)     │
└────────────────────────────────────────────┘
```

### 1. 服务器端编译环境

#### 1.1 安装 Node.js（通过 nvm）

```bash
# 安装 nvm
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
source ~/.bashrc

# 安装 Node.js 16（uni-app 2.x 兼容性最好）
nvm install 16
nvm use 16

# 验证
node -v   # v16.x.x
npm -v    # 8.x.x
```

#### 1.2 安装项目依赖

```bash
cd /home/ubuntu/YANG/sky-admin/uni-app
npm install --legacy-peer-deps
```

> **注意**: `--legacy-peer-deps` 是必需的，因为部分依赖（如 `mini-css-extract-plugin`）存在 peer dependency 版本冲突，但不影响编译。

#### 1.3 安装缺失依赖（如初次编译报错）

`@dcloudio/vue-cli-plugin-uni` 没有完整声明其所有 peer dependencies。如果编译时提示模块缺失，按以下方式安装：

```bash
npm install --legacy-peer-deps \
  webpack@4 \
  @vue/cli-plugin-babel@4 \
  regenerator-runtime \
  file-loader \
  url-loader \
  postcss@7 \
  autoprefixer@9
```

#### 1.4 应用编译补丁

由于 uni-app 2.x 的 `vue-loader` fork 版本与当前 npm 生态存在兼容性问题，需要手动 patch 两个文件：

```bash
bash patches/apply-patches.sh
```

**Patch 内容说明**：

| 文件 | 问题 | 修复 |
|------|------|------|
| `@dcloudio/vue-cli-plugin-uni/lib/configure-webpack.js` | `updateJsLoader()` 未做空值检查，当 webpack 规则不匹配时崩溃 | 添加 `if (!matchRule \|\| !matchRule.use) return` 防御 |
| `@dcloudio/vue-cli-plugin-uni/packages/vue-loader/lib/loaders/templateLoader.js` | 模板 export 语句引用了 `recyclableRender`、`components` 但编译产物中不存在这些变量 | 在 export 前添加 `var recyclableRender` 和 `var components` 声明 |

> ⚠️ 每次执行 `npm install` 重新安装依赖后，需要重新运行 `bash patches/apply-patches.sh`。

#### 1.5 编译配置文件

**`vue.config.js`**：
```javascript
const path = require('path');

// 设置源码目录（当前目录，因为 vue/manifest/pages 都在根目录）
process.env.UNI_INPUT_DIR = __dirname;

module.exports = {
  transpileDependencies: ['@dcloudio/uni-ui'],
  outputDir: path.resolve(__dirname, 'dist/build/mp-weixin')
};
```

> `UNI_INPUT_DIR` 必须显式设置，因为 uni-app CLI 默认期望源码在 `src/` 子目录下，而本项目文件直接放在 `uni-app/` 根目录。

**`postcss.config.js`**：
```javascript
module.exports = {
  plugins: [
    require('autoprefixer')({
      overrideBrowserslist: ['Android >= 4.4', 'ios >= 9']
    })
  ]
};
```

#### 1.6 编译命令

```bash
# 生产构建（发布用）
npm run build:mp-weixin

# 开发构建 + watch 模式
npm run dev:mp-weixin
```

`package.json` 中的脚本已经预设了所需环境变量：

```json
{
  "scripts": {
    "build:mp-weixin": "cross-env NODE_ENV=production UNI_PLATFORM=mp-weixin UNI_CLI_CONTEXT=./ UNI_INPUT_DIR=./ UNI_OUTPUT_DIR=./dist/build/mp-weixin vue-cli-service uni-build",
    "dev:mp-weixin": "cross-env NODE_ENV=development UNI_PLATFORM=mp-weixin UNI_CLI_CONTEXT=./ UNI_INPUT_DIR=./ UNI_OUTPUT_DIR=./dist/dev/mp-weixin vue-cli-service uni-build --watch"
  }
}
```

关键环境变量说明：

| 变量 | 作用 | 默认值 |
|------|------|--------|
| `NODE_ENV` | `production` 生成优化代码；`development` 包含 sourcemap | — |
| `UNI_PLATFORM` | 目标平台：`mp-weixin` | `h5` |
| `UNI_CLI_CONTEXT` | 项目根目录（用于解析 package.json 等） | node_modules 内部路径（需覆盖） |
| `UNI_INPUT_DIR` | 源码目录（manifest.json / pages.json / App.vue 所在目录） | `src/`（需覆盖） |
| `UNI_OUTPUT_DIR` | 编译产物输出目录 | `dist/build/{platform}` |

#### 1.7 编译产物结构

```
dist/build/mp-weixin/
├── app.js / app.json / app.wxss   # 小程序入口
├── project.config.json             # 开发者工具配置
├── common/                         # 公共代码
│   ├── runtime.js                  # Vue 运行时
│   ├── vendor.js                   # 第三方依赖
│   ├── main.js                     # 主入口逻辑
│   └── main.wxss                   # 全局样式
└── pages/                          # 页面（每个页面一个目录）
    ├── index/  (index.js/.json/.wxml/.wxss)
    ├── login/  (login.js/.json/.wxml/.wxss)
    └── bind/   (bind.js/.json/.wxml/.wxss)
```

### 2. 同步到本地 Mac

#### 2.1 使用同步脚本

在 Mac 终端执行 `sync-to-local.sh`：

```bash
bash sync-to-local.sh
```

脚本内容（修改 `SERVER` 为你的服务器地址）：

```bash
SERVER="ubuntu@115.159.64.19"
REMOTE_PATH="/home/ubuntu/YANG/sky-admin/uni-app/dist/build/mp-weixin/"
LOCAL_PATH="$HOME/Desktop/project/code/uni-app-dist"

mkdir -p "$LOCAL_PATH"
rsync -avz --delete --exclude='.DS_Store' "$SERVER:$REMOTE_PATH" "$LOCAL_PATH"
```

#### 2.2 手动 rsync

```bash
rsync -avz --delete \
  ubuntu@<服务器IP>:/home/ubuntu/YANG/sky-admin/uni-app/dist/build/mp-weixin/ \
  ~/Desktop/project/code/uni-app-dist/
```

### 3. 微信开发者工具配置

1. 打开微信开发者工具
2. 左侧选择 **"小程序"**（不是多端应用或小游戏）
3. 点击 **"导入项目"**（或右上角 `+`）
4. 填写信息：
   - **项目名称**：`sky-admin`（任意）
   - **目录**：选择本地同步路径 `~/Desktop/project/code/uni-app-dist/`
   - **AppID**：`wx6a46dda85a013a34`
   - **开发模式**：小程序
5. 后端服务选择 **"不使用云服务"**（你的后端是自建 FastAPI 服务器，非微信云开发）
6. 点击"确定"

### 4. 开发流程

```
远程服务器                        本地 Mac
     │                              │
     │ 编辑源码 (*.vue)              │
     │                              │
     │ npm run build:mp-weixin      │
     │      ↓                       │
     │ dist/build/mp-weixin/        │
     │      │                       │
     │      └── rsync ──────────→ 同步到本地 ──→ 微信开发者工具
     │                                           │
     │                                           ├── 模拟器预览
     │                                           ├── 真机调试（扫码）
     │                                           └── 预览（生成二维码）
```

> **注意**：因为源码在远程服务器上，无法使用 HBuilderX 的热更新功能。每次修改后需要在服务器重新编译，再同步到本地。

### 5. 调试技巧

- **不校验合法域名**: 开发阶段可在微信开发者工具 → 详情 → 本地设置 → 勾选"不校验合法域名、web-view、TLS 版本"
- **真机调试**: 点击工具栏"真机调试" → 扫码 → 在手机上测试
- **预览**: 点击"预览"生成二维码 → 手机微信扫码体验
- **生产环境**：需要在[微信公众平台](https://mp.weixin.qq.com/) → 开发管理 → 开发设置 → 服务器域名，把 `https://api.skycoc.cc` 加到 **request 合法域名** 列表中

### 6. 依赖版本说明

核心依赖固定版本，避免自动升级导致兼容性问题：

| 包 | 版本 | 说明 |
|----|------|------|
| `@dcloudio/vue-cli-plugin-uni` | `2.0.2-5020320260806001` | uni-app 编译器插件 |
| `@dcloudio/uni-mp-weixin` | `2.0.2-5020320260806001` | 微信小程序平台适配 |
| `@dcloudio/uni-template-compiler` | `2.0.2-5020320260806001` | 模板编译器 |
| `vue` | `^2.6.12` | Vue 2.x（uni-app 不支持 Vue 3） |
| `@vue/cli-service` | `^4.5.0` | Vue CLI 构建服务 |
| `webpack` | `^4.47.0` | Webpack 4（必须 4.x，5.x 不兼容） |
| `postcss` | `^7.0.39` | PostCSS 7（必须 7.x，8.x 不兼容） |
| `autoprefixer` | `^9.8.8` | Autoprefixer 9（必须 9.x，10.x 需要 PostCSS 8） |

---

## 备案通过后操作

备案通过后，按以下步骤切换回域名访问：

### 1. 修改前端代码

**`utils/api.js`**：
```javascript
// 改回域名
const BASE_URL = 'https://api.skycoc.cc'
```

**`App.vue`**：
```javascript
globalData: {
    apiBase: 'https://api.skycoc.cc',
```

### 2. 修改 project.config.json

```json
"setting": {
    "urlCheck": true  // 恢复域名校验
}
```

### 3. 重新编译并同步

```bash
# 服务器端
cd /home/ubuntu/YANG/sky-admin/uni-app
npm run build:mp-weixin

# Mac 端
bash sync-to-local.sh
```

### 4. 微信公众平台配置

登录 [微信公众平台](https://mp.weixin.qq.com/) → 开发管理 → 开发设置 → 服务器域名：

- **request 合法域名**：添加 `https://api.skycoc.cc`
- 点击保存提交

### 5. 移除 Nginx IP 访问配置（可选）

备案通过后，可删除 Nginx 中为 IP 访问添加的 server 块，仅保留域名配置：

```bash
sudo vim /etc/nginx/sites-enabled/sky-admin
# 删除 "# IP 直接访问（备案前开发用）" 段落
sudo nginx -t && sudo systemctl reload nginx
```

---

## 待开发功能

- [ ] 成员列表页（调用 `GET /api/members`）
- [ ] 成员详情页
- [ ] 联赛数据展示
- [ ] 管理员面板（role=admin 可见）
- [ ] 微信用户信息获取（`wx.getUserProfile` 获取昵称和头像）
