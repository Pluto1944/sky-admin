# uni-app 微信小程序文档

## 概述

`uni-app/` 是基于 [uni-app](https://uniapp.dcloud.net.cn/) 框架开发的微信小程序，为"苍穹联赛"提供移动端管理入口。支持微信一键登录、游戏账号绑定、成员查看等功能。

### 当前审核相关实现（2026-09）

- 登录前必须由用户主动勾选同意项；《用户协议》和《隐私政策》分别通过 `pages/legal/` 页面打开，未同意时不会调用微信登录或读取账号资料。
- 部落 Tab 内部为“概览 / 成员 / 战营 / 互刷”四个入口，默认显示全部自有部落概览卡片；单部落详情也在同一 Tab 页内展示，因此始终保留原生底部 TabBar。成员表格只在首次点击“成员”后加载。
- 战斗页顶栏提供“部落战”“联赛数据”“联赛点名”三个主功能入口；部落战已实现全部自有部落汇总、筛选和单部落详情宽表，联赛数据已实现当月参赛部落卡片、单部落战斗日和联赛总览，联赛点名当前包含集结检查和出刀提醒。
- 联赛实时看板采用“参赛部落 → 单部落详情”的两层结构；详情内再切换战斗日和联赛总览，完整设计见 `docs/19-cwl-live-dashboard.md`。
- 本文件下方的“旧架构”和“待开发功能”仅保留作历史记录，不代表当前页面状态。

- **AppID**: `wx6a46dda85a013a34`
- **框架**: uni-app (Vue 2)
- **后端 API**: `https://api.skycoc.cc`（备案通过前临时使用 `https://115.159.64.19`）
- **UI 主题**: 暗色风格
- **备案状态**: ⏳ 等待 ICP 备案通过
- **架构状态**: ✅ 原生 TabBar 多页架构（4 个主页：部落/战斗/账号/设置）

---

## 文件结构

```
uni-app/
├── manifest.json              # 小程序配置（AppID、权限等）
├── pages.json                 # 页面路由 + TabBar 配置
├── App.vue                    # 应用入口（全局样式、全局状态）
├── main.js                    # Vue 入口
├── uni.scss                   # 主题色变量
├── package.json               # Node.js 依赖 + 编译脚本
├── vue.config.js              # Webpack 构建配置（UNI_INPUT_DIR、输出目录）
├── postcss.config.js          # PostCSS 配置
├── pages/
│   ├── clan/
│   │   ├── clan.vue           # 部落主页（TabBar 页，四入口编排）
│   │   └── components/        # 概览、单部落详情、成员、战营、互刷内嵌组件
│   ├── war/
│   │   ├── war.vue            # 战斗主页（TabBar 页，自定义顶栏）
│   │   ├── check-in.vue       # 联赛点名内嵌组件（集结检查/出刀提醒）
│   │   ├── current-detail.vue # 当前普通部落战详情
│   │   ├── cwl-detail.vue     # CWL 战斗日与联赛总览详情
│   │   └── detail.vue         # 历史战绩详情（子页，原生导航栏）
│   ├── account/
│   │   └── account.vue        # 账号主页（TabBar 页，自定义顶栏）
│   ├── settings/
│   │   └── settings.vue       # 设置主页（TabBar 页，自定义顶栏）
│   ├── login/
│   │   └── login.vue          # 微信登录页（已有，整合到设置流程）
│   └── bind/
│       └── bind.vue           # 游戏账号绑定页（已有，整合到设置流程）
├── components/
│   └── TopBar.vue             # 自定义顶部栏组件（预留 buttons props）
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

## 页面架构

### 整体布局模型

采用**三层布局**：

```
┌──────────────────────────────────┐
│ 状态栏（系统，微信自动处理）        │
├──────────────────────────────────┤
│  上控制区域（自定义顶栏）          │  ← 每个主页面不同
│  按钮右对齐，后续按页面功能设计    │     主页面无 < 返回
├──────────────────────────────────┤
│                                  │
│       中间展示区域                │  ← 各页面不同，后续设计
│                                  │
├──────────────────────────────────┤
│  下控制区域（原生 tabBar）        │  ← 全局固定 4 按钮
│  [部落]  [战斗]  [账号]  [设置]   │
│  (系统自动处理 iPhone 底部安全区)  │
└──────────────────────────────────┘
```

### TabBar 设计

使用 uni-app 原生 `tabBar` 实现底部 4 个固定按钮，始终可见（除子页面外）：

| 按钮 | 对应页面 | 职责 |
|------|---------|------|
| **部落** | 部落主页 | 部落信息、成员列表、部落动态 |
| **战斗** | 战斗主页 | 联赛战绩、战斗记录、排名 |
| **账号** | 账号主页 | 个人信息、绑定管理、我的数据 |
| **设置** | 设置主页 | 系统设置、关于、退出登录、登录/绑定 |

> **方案选择**：使用 uni-app 原生 `tabBar`（方案 A），而非完全自定义。原因：
> 1. 原生切换动画流畅，页面状态自动缓存
> 2. uni-app 自动处理跨平台适配（iOS/Android App、各小程序平台）
> 3. 开发量少，代码量少
> 4. 不需要动态隐藏 TabBar 或角标等高级功能

小程序默认启动页为“战斗”。`pages.json` 将 `pages/war/war` 放在页面列表首位；
底部 TabBar 仍保持“部落、战斗、账号、设置”的既有排列顺序。

### 页面内导航层级规范

页面内功能切换统一区分两种视觉层级，不混用选中样式：

| 层级 | 使用位置 | 默认样式 | 选中样式 |
|------|----------|----------|----------|
| **主功能入口** | 自定义顶栏右侧，例如“概览 / 成员 / 战营 / 互刷”和“部落战 / 联赛数据 / 联赛点名” | 图标加文字，横向紧凑排列 | 蓝色文字和图标、半透明蓝色圆角背景 |
| **内容区次级页面** | 当前主功能内部的并列页面，例如“部落 / 成员”“集结检查 / 出刀提醒”“战斗日 / 联赛总览” | 内容区顶部等宽横向 Tab、深色背景、灰色文字 | 蓝色文字、字重加粗、底部蓝色横线；不再使用圆角背景 |

内容区次级 Tab 的实现约束：

- 固定在当前内容区域顶部，位于数据更新时间、卡片或表格之前；
- 标签栏铺满内容区域且不设置左右内边距；各项使用 `flex: 1` 等宽分布，两个标签时各占 50%，文字在各自区域水平、垂直居中，整个区域均可点击，触控高度保持约 `72–76rpx`；
- 默认只显示文字，不重复添加 emoji，避免字体基线和视觉重心不一致；
- 使用底部分隔线承接内容，激活横线建议为 `4rpx`，并铺满当前标签单元格宽度；主题色使用 `#4a90d9` 或同级亮蓝色；
- 切换只替换当前内容区域，不应离开所属 TabBar 主页面，因此底部四项主导航保持可见；
- 第三级选择（例如第 1～7 场）数据项较多时，可使用横向滚动的小标签，不强制套用等宽次级 Tab。

当前已采用该规范的页面包括互刷“部落 / 成员”、联赛点名“集结检查 / 出刀提醒”和联赛详情“战斗日 / 联赛总览”。新增同级切换时应复用相同结构、色值和尺寸，避免每个业务页面单独设计一套标签样式。

### 页面清单 & 路由

| 路由 | 页面 | 类型 | TabBar | 顶部栏 |
|------|------|------|--------|--------|
| `pages/clan/clan` | 部落主页（含概览/成员/战营/互刷和单部落详情） | Tab 页 | ✅ 部落 | 自定义顶栏 |
| `pages/war/war` | 战斗主页（含部落战/联赛数据/联赛点名） | Tab 页 | ✅ 战斗 | 自定义顶栏 |
| `pages/account/account` | 账号主页 | Tab 页 | ✅ 账号 | 自定义顶栏（按钮后续设计） |
| `pages/settings/settings` | 设置主页 | Tab 页 | ✅ 设置 | 自定义顶栏（按钮后续设计） |
| `pages/war/detail` | 战绩详情 | 子页 | ❌ | 原生导航栏 `< 返回` |
| `pages/war/current-detail` | 当前普通部落战详情 | 子页 | ❌ | 自定义顶栏 `< 返回` |
| `pages/war/cwl-detail` | CWL 单部落详情 | 子页 | ❌ | 自定义顶栏 `< 返回` |
| `pages/login/login` | 微信登录 | 子页 | ❌ | 原生导航栏 `< 返回` |
| `pages/bind/bind` | 绑定账号 | 子页 | ❌ | 原生导航栏 `< 返回` |

### 登录/绑定流程

登录和绑定整合到「设置」页面内：

```
用户进入小程序
    │
    ▼
TabBar「设置」页
    │
    ├── 已登录？──→ 显示用户信息 + 设置项 + 退出按钮
    │
    └── 未登录？──→ 显示登录入口（点击进入登录流程）
                      │
                      ▼
                  登录页（子页 navigateTo）
                      │
                      ├── 已绑定？──→ 返回设置页（显示用户信息）
                      └── 未绑定？──→ 绑定页（子页 navigateTo）
                                        │
                                        └── 完成 → 返回设置页
```

### 各页面职责 & 顶部栏预留

#### 1. 部落 `pages/clan/clan`

| 项目 | 内容 |
|------|------|
| **职责** | 部落概览、单部落详情、成员排序筛选、战营、互刷 |
| **顶栏标题** | 部落 |
| **顶栏按钮** | 🏠概览、👥成员、⚔️战营、🔄互刷；选中项为蓝色文字/图标和浅蓝底 |
| **中间区域** | 默认显示自有部落概览卡片；其他功能首次激活才加载，缓存本次会话数据 |

概览和单部落详情的完整字段、导航、分享和数据边界见 [20-clan-overview.md](20-clan-overview.md)。

#### 2. 战斗 `pages/war/war`

> 当前部落战的“全部自有部落汇总页 + 单部落详情页”方案见
> [18-current-war-dashboard.md](18-current-war-dashboard.md)。
>
> CWL 联赛的“参赛部落 + 单部落战斗日/联赛总览”方案见
> [19-cwl-live-dashboard.md](19-cwl-live-dashboard.md)。
>
> 联赛正式名单与成员到位检查见 [21-cwl-assembly-check.md](21-cwl-assembly-check.md)。

| 项目 | 内容 |
|------|------|
| **职责** | 当前部落战、每部落最近15场普通战争、按月份回看的联赛战斗日与联赛总览、当月联赛集结检查与出刀提醒 |
| **顶栏标题** | 战斗 |
| **顶栏按钮** | 部落战、联赛数据、联赛点名；当前子页使用与部落主页一致的蓝色文字和半透明圆角背景选中态 |
| **中间区域** | 部落战显示全部自有部落战争摘要、筛选和单部落详情宽表；联赛先显示当月参赛部落，进入单部落详情后切换战斗日/联赛总览；联赛点名在战斗 TabBar 主页面内切换集结检查/出刀提醒 |

只有当前战争汇总页和当前战争详情页在进入、返回前台时立即读取后端缓存；停留期间每 1 分钟读取一次。
页面隐藏或卸载后停止轮询。该前端轮询不直接请求 COC；后端 `current_wars` 每 2 分钟检查一次，战斗日每 2 分钟、准备日通常每 30 分钟（开战前 30 分钟内每 2 分钟）、无战争 / 已结束每 5 分钟、CWL 跳转状态每 30 分钟更新缓存。

部落战内容区使用下拉菜单切换“当前部落战 / 具体部落最近15场”。每个历史选项使用“完整部落名 · 业务分类 · 最近15场”，以区分多个互刷部落。历史列表进入时只拉一次轻量摘要，不执行分钟轮询；部落由顶部下拉菜单确定，筛选面板只保留胜、平、负条件。单场详情复用 `current-detail.vue`，传入 `war_key` 后同样不轮询；列表分享和详情回退都保留 `clan_tag`。联赛内容区使用后端返回的月份选择，默认当前月；只有当前月的参赛部落预览和单部落详情执行分钟轮询，历史月份首次进入时读取一次固定缓存，分享链接必须保留月份。

战斗主页内嵌的联赛点名组件默认打开“出刀提醒”，汇总当月所有处于战斗日的联赛队伍，按当月 `league_teams.team_index` 固定顺序展示倒计时和未出刀成员。每个部落可独立折叠，首次进入时全部展开，缓存自动刷新后保留当前折叠状态。只统计当轮实际上阵成员，前端每 1 分钟读取现有 `cwl_live` 缓存，倒计时每秒本地更新。

“联赛数据”的参赛部落卡片在部落标题下使用同一行展示“首领 / 联赛管理”。首领优先取正式表生成时的 COC 完整昵称，缺失时回退 `league_teams.leader` 配置简称，两者都为空才由快照任务补查一次 COC；它们代表同一人，不重复展示。联赛管理取当月正式名单抬头的 `manager`，与首领是不同概念。

“集结检查”第一层显示当月全部联赛部落卡片及正式、到位、未到、额外人数，点击后在同一 TabBar 页面内显示单部落详情；红色为正式名单中未到位，绿色为名单外当前成员，默认色为已到位。详情展示昵称、职位和大本等级，不展示官方接口不存在的最近登录时间。前端每 1 分钟读取 `cwl_assembly` 缓存，不直接读取腾讯文档或调用 COC。该组件必须留在 `pages/war/war` 内，确保微信原生底部四项 TabBar 始终可见。

微信真机不会自动把内嵌自定义组件主机节点拉伸到父级剩余高度。战斗主页必须为联赛点名组件主机显式设置 `flex: 1`、`height: 0` 和 `min-height: 0`，组件根节点再使用 `height: 100%`；否则次级 Tab 因固定高度可见，但其下方的加载状态、摘要和列表会被压缩为空白。此约束同样适用于后续嵌入 TabBar 主页面的全高滚动组件。

#### 3. 账号 `pages/account/account`

| 项目 | 内容 |
|------|------|
| **职责** | 个人信息展示、数据统计 |
| **顶栏标题** | 账号 |
| **顶栏按钮（预留）** | 后续根据功能确定，如：编辑 |
| **中间区域（后续设计）** | 用户卡片 + 个人数据 + 历史记录 |

#### 4. 设置 `pages/settings/settings`

| 项目 | 内容 |
|------|------|
| **职责** | 登录/绑定、系统设置、关于、退出 |
| **顶栏标题** | 设置 |
| **顶栏按钮（预留）** | 可能不需要按钮 |
| **中间区域（后续设计）** | 登录入口 / 已登录状态 + 设置项列表 + 退出登录 |

### 页面切换关系

```
                    ┌──────────────┐
                    │   小程序启动   │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │   TabBar     │
                    │   [设置] 页   │  ← 默认进入设置（检测登录状态）
                    └──────────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
         未登录         已登录        其他 TabBar 页
              │            │          可正常使用
              ▼            ▼
        login.vue     settings.vue
              │       （用户信息+设置项+退出）
              ▼
         已绑定？──是──→ settings.vue
              │否
              ▼
         bind.vue
              │
              ▼
         settings.vue
```

### TopBar 组件接口（预留）

```javascript
// TopBar.vue props
{
  title: String,           // 标题文字，如 "部落"
  buttons: Array           // 右侧按钮列表，后续按页面需求传入
  // buttons 结构（预留）:
  // [
  //   { key: 'filter', icon: '🔍', action: 'onFilter' },
  //   { key: 'search', icon: '⏬', action: 'onSearch' }
  // ]
}
```

顶部栏通过 `$emit` 向上传递按钮点击事件，各页面自行处理：

```
┌──────────────────────────────────┐
│  部落                    🔍  ⏬  │  ← TopBar 组件
│                                  │     title="部落"
├──────────────────────────────────┤     buttons=[...]
│  中间内容（clan.vue）             │
```

### pages.json 配置草案

```json
{
  "pages": [
    {
      "path": "pages/clan/clan",
      "style": {
        "navigationStyle": "custom",
        "navigationBarTitleText": "部落"
      }
    },
    {
      "path": "pages/war/war",
      "style": {
        "navigationStyle": "custom",
        "navigationBarTitleText": "战斗"
      }
    },
    {
      "path": "pages/account/account",
      "style": {
        "navigationStyle": "custom",
        "navigationBarTitleText": "账号"
      }
    },
    {
      "path": "pages/settings/settings",
      "style": {
        "navigationStyle": "custom",
        "navigationBarTitleText": "设置"
      }
    },
    {
      "path": "pages/login/login",
      "style": {
        "navigationBarTitleText": "微信登录"
      }
    },
    {
      "path": "pages/bind/bind",
      "style": {
        "navigationBarTitleText": "绑定游戏账号"
      }
    },
    {
      "path": "pages/war/detail",
      "style": {
        "navigationBarTitleText": "战绩详情"
      }
    }
  ],
  "tabBar": {
    "color": "#8890a0",
    "selectedColor": "#4a90d9",
    "backgroundColor": "#1a1a2e",
    "borderStyle": "black",
    "list": [
      {
        "pagePath": "pages/clan/clan",
        "text": "部落"
      },
      {
        "pagePath": "pages/war/war",
        "text": "战斗"
      },
      {
        "pagePath": "pages/account/account",
        "text": "账号"
      },
      {
        "pagePath": "pages/settings/settings",
        "text": "设置"
      }
    ]
  },
  "globalStyle": {
    "navigationBarTextStyle": "white",
    "navigationBarTitleText": "苍穹联赛助手",
    "navigationBarBackgroundColor": "#1a1a2e",
    "backgroundColor": "#0f0f23"
  }
}
```

> **注意**：4 个 TabBar 页用 `navigationStyle: "custom"` 隐藏原生导航栏，自己画顶栏；子页面（登录/绑定/详情）用原生导航栏，自带 `<` 返回按钮。

---

## 现有页面说明（旧架构，待重构）

以下页面为当前已实现的页面，后续将按上述新架构重构：

### 1. 登录页 (`pages/login/login`)

**路由**: `/pages/login/login`

**功能**：
- 展示 App 名称和品牌标识
- 展示协议勾选框；协议链接可打开用户协议和隐私政策，未勾选时登录按钮不可用
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

> ⚠️ 上述 3 个页面为当前已实现页面，将在新架构中：`index.vue` 废弃（功能拆分到 4 个主页面），`login.vue` 和 `bind.vue` 保留为设置流程子页。

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
| `getClanOverview()` | `GET /api/clan/overview` | ❌ |
| `getClanOverviewDetail(tag)` | `GET /api/clan/overview/{clan_tag}` | ❌ |

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

## 小程序表格渲染注意事项

微信小程序端的表格页面（如部落战绩、互刷、部落成员列表）需遵循以下约定：

- 表格样式使用非 scoped 的 `<style>`，不要使用 `<style scoped>`。当前 uni-app/微信运行时下，scoped 属性样式在 flex 表格单元格上可能无法可靠命中，表现为数据能加载但列宽、边框和背景样式失效。
- 行容器必须显式设置 `display: flex` 和 `flex-direction: row`；flex 默认主轴为纵向，遗漏后单元格会逐个竖排。
- 表格建议采用固定表头 + 独立 `scroll-view scroll-y` 数据体的结构，避免同一个 `scroll-view` 同时承担横向和纵向滚动。
- 单元格使用固定宽度并设置 `flex-shrink: 0`，必要时配合 `box-sizing: border-box`，防止小屏设备压缩列宽。
- 修改表格结构或样式后必须重新执行 `npm run build:mp-weixin`，并在微信开发者工具中清除缓存、重新导入 `dist/build/mp-weixin`，否则可能继续运行旧产物。

部落成员主表实现位于 `uni-app/pages/clan/components/ClanMembers.vue`，战营与互刷表格分别位于同目录的 `ClanStats.vue` 和 `ClanFarm.vue`。组件样式类名必须使用各自前缀，避免非 scoped 样式互相污染。

部落成员主表使用 15 列：昵称、玩家标签、部落、职位、大本、联赛、主世界奖杯、赛季进攻、赛季捐兵、赛季收兵、最近活动、普战近15战、联赛近3月、都城近4周和竞赛贡献。“最近活动”在一个单元格内用两行展示相对时间和变化依据；归属人、经验等级、所有夜世界字段、历史分、报名状态、最近报名和逐行最近同步隐藏，整批更新时间保留在页面工具栏。主世界奖杯仅展示，不参与活跃判断。只有首次切换到“成员”时才调用 `/api/members`，页面不轮询，表格横向和纵向滚动，排序在前端完成。

成员页默认只展示仍在自有部落的当前成员。成员状态保留为筛选条件，提供“在部落 / 已离开 / 全部”；选择后两项时，已离开玩家在昵称旁显示灰色“已离开”标签，不再占用独立状态列。

“最近活动”表示后端最后一次检测到有效公开数据变化的时间，不是官方登录时间。成员 `coc_raw` 覆盖前比较捐兵、收兵、经验、大本、昵称和玩家小屋；累计字段只认增加，赛季归零不刷新活动时间。赛季进攻来自每日玩家详情任务缓存的 `attackWins`，普通战和 CWL 的新进攻也会更新活动时间。完整字段白名单和初始观察规则见 [22-member-activity.md](22-member-activity.md)。

“普战近15战”按玩家标签汇总最近 90 天内、跨全部自有部落最近最多 15 场参战普通战，显示三星率、三星/进攻样本和出刀率；“联赛近3月”汇总最近 3 个完整联赛月内玩家在全部自有联赛队伍的实际进攻，显示三星率和三星/进攻样本。两项都限制在自有部落边界内，但不限制战营、混营、互刷、偷矿、`combat` 或 `shell` 等类型，玩家当前部落只用于展示和筛选。无样本显示 `-`，不能与真实 `0%` 混淆。两列读取后端预计算的本地汇总，成员页不加载完整战争 JSON。

“都城近4周”显示最近 4 个已结束突袭周末的总掠夺、实际/可用刀数和每刀掠夺；“竞赛贡献”显示最近完成月份积分和近 3 期平均值。都城按周、竞赛按月读取后端结果，页面不在活动期间轮询官方 API。竞赛缺少上期基准时显示“记录不完整”，不能显示为 0。

成员页将当前结果人数、数据更新时间、筛选摘要和重置入口合并在表格外的单层紧凑工具栏中；筛选与搜索按钮固定在右侧。筛选生效时按钮显示条件数量角标，筛选或搜索生效时使用高亮状态。表头紧接工具栏，状态信息不得放入横向滚动的宽表区域，避免随表格偏移并减少首屏纵向占用。

`last_synced_at` 为 UTC ISO 时间，页面必须转换为设备本地时间后显示，避免直接截取字符串造成北京时间少 8 小时。

通过 `App.vue` 的 `globalData` 管理：

```javascript
globalData: {
  apiBase: 'https://115.159.64.19',  // 备案通过前 IP 直连；备案后改回域名
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

## 历史开发清单（仅作背景）

> 下列为早期规划快照，不可用于判断当前实现状态。当前页面和接口以本文前半部以及 `pages.json` / `utils/api.js` 为准。

### 前端重构（早期规划）

- [ ] 创建 `pages/clan/clan.vue`（部落主页，TabBar 页，自定义顶栏）
- [ ] 创建 `pages/war/war.vue`（战斗主页，TabBar 页，自定义顶栏）
- [ ] 创建 `pages/account/account.vue`（账号主页，TabBar 页，自定义顶栏）
- [ ] 创建 `pages/settings/settings.vue`（设置主页，TabBar 页，自定义顶栏）
- [ ] 创建 `components/TopBar.vue`（自定义顶部栏组件）
- [ ] 创建 `pages/clan/detail.vue`（成员详情，子页，空壳）
- [ ] 创建 `pages/war/detail.vue`（战绩详情，子页，空壳）
- [ ] 重写 `pages.json`（加入 TabBar + 新页面路由）
- [ ] 调整 `App.vue`（去掉首页登录检查，改到设置页）
- [ ] 废弃 `pages/index/index.vue`（功能拆分到 4 个主页面）

### 功能开发（按页面）

- [ ] 部落主页：成员列表展示、搜索筛选
- [ ] 战斗主页：联赛战绩列表、排名、月份切换
- [ ] 账号主页：个人数据展示、历史记录
- [ ] 设置主页：登录/绑定流程、系统设置、退出登录
- [ ] 成员详情页：完整个人档案
- [ ] 战绩详情页：联赛战绩明细
- [ ] 微信用户信息获取（`wx.getUserProfile` 获取昵称和头像）

### 后端 API（配合前端）

- [ ] `GET /api/wechat/me` 增强（join accounts 表，返回游戏数据）
- [ ] `GET /api/members` 增强（支持 search/clan_tag/status 筛选）
- [ ] `GET /api/league/teams` 新增（返回某月队伍配置）
- [ ] `GET /api/league/results` 新增（返回某月联赛战绩）
- [ ] `GET /api/members/{player_tag}` 新增（成员详情含报名+战绩历史）
