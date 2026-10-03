# 版本发布规则

> 状态：当前正式规则
>
> 适用范围：`sky-admin` 后端、调度器和微信小程序
>
> 当前发布分支：`feat/wechat`

本文统一版本号、提交、Tag、远端推送、后端部署和微信小程序发布流程。目标是保证每个线上版本都能追溯到唯一 Git 提交，并且发布前经过与风险相匹配的验证。

## 1. 发布对象与边界

一次完整发布可能包含三个相互独立的动作：

1. **Git 发布**：提交代码、创建版本 Tag、推送发布分支和 Tag；
2. **后端上线**：迁移数据库、重启 `sky-admin.service` / `sky-scheduler.service` 并验证接口；
3. **小程序上线**：构建、开发者工具上传、微信公众平台提交审核并发布。

创建或推送 Tag **不会自动完成后端部署，也不会自动发布微信小程序**。执行人必须分别确认三个动作的状态，不得把“Tag 已推送”表述为“线上已发布”。

## 2. 版本号规则

版本采用语义化格式：

```text
Git Tag：v主版本.次版本.修订版本，例如 v1.0.3
微信版本号：主版本.次版本.修订版本，例如 1.0.3
```

版本递增规则：

| 类型 | 适用情况 | 示例 |
| --- | --- | --- |
| 修订版本 `PATCH` | 缺陷修复、样式与交互优化、性能优化，不改变核心业务兼容性 | `v1.0.2` → `v1.0.3` |
| 次版本 `MINOR` | 新增向后兼容的业务页面、接口或统计能力 | `v1.0.3` → `v1.1.0` |
| 主版本 `MAJOR` | 存在不兼容的数据模型、接口或操作流程变更 | `v1.1.0` → `v2.0.0` |

规则：

- 正式 Tag 使用 annotated tag，不使用临时或含糊名称；
- 已推送的版本 Tag 视为不可变，不覆盖、不强制移动；
- 发布后发现问题时创建新的修订版本，不复用原版本号；
- Tag 必须指向已经提交并完成验证的 commit，未提交文件永远不会进入 Tag。

## 3. 发布前置条件

### 3.1 范围冻结

发布前明确本次版本包含哪些功能，停止顺带修改相邻模块。设计稿、运行数据、数据库、日志、密钥、构建产物和其它窗口的工作不得混入提交。

执行：

```bash
git status --short --branch
git diff --check
git log --oneline origin/feat/wechat..feat/wechat
```

要求：

- 所有准备发布的实现与正式文档均已提交；
- 暂存区为空；
- 若仍有未跟踪或未提交文件，必须逐项确认它们不属于本次版本，并在发布交接中说明；
- 不得为了得到“干净状态”覆盖或删除他人的工作区改动。

### 3.2 文档同步

行为发生变化时，同一个业务提交必须更新对应正式文档。临时设计稿不能替代当前行为文档；尚未实施的方案不得写成已上线能力。

至少检查：

- 小程序交互：`docs/11-uni-app.md`；
- 数据库和字段：`docs/02-database.md`；
- API：`docs/10-api-server.md`；
- 调度任务：`docs/15-scheduler.md`；
- 具体业务模块对应的专题文档。

### 3.3 验证要求

根据改动范围执行测试，并只记录实际成功的结果。

后端基础检查：

```bash
venv/bin/python -m pytest <相关测试>
git diff --check
```

微信小程序生产构建：

```bash
cd uni-app
source ../.frontend-env/activate
npm run build:mp-weixin
```

涉及 Shell 脚本时执行：

```bash
bash -n <脚本路径>
```

高风险改动应扩大验证范围：

- SQLite schema 或迁移：先在生产库一致性备份的副本上演练；
- 调度任务：检查对应 `sync_jobs` 状态和失败隔离；
- 公开 API：检查本机与公网接口；
- 小程序表格：使用微信开发者工具和至少一台真机检查横向滚动、分页、固定列和底部 TabBar。

## 4. 提交规则

提交按单一业务目的组织，只暂存本次相关文件：

```bash
git add -- <明确文件列表>
git diff --cached --check
git diff --cached --stat
git diff --cached
git commit -m "<type>(<scope>): <description>"
```

推荐提交类型：

- `feat`：新增功能；
- `fix`：修复缺陷；
- `perf`：性能优化；
- `style`：不改变业务语义的界面调整；
- `refactor`：内部重构；
- `docs`：仅文档；
- `chore`：配置或维护工作。

提交后再次运行 `git status --short --branch`，确认暂存区为空，并记录仍保留的无关改动。

## 5. Tag 与远端推送

### 5.1 确认发布提交

```bash
git show --no-patch --decorate --date=iso-local --pretty=fuller HEAD
git tag --list 'v*' --sort=-version:refname
git ls-remote --tags origin 'refs/tags/v*'
```

确认新版本号在本地和远端均不存在，并确认 `HEAD` 是希望发布的唯一 commit。

### 5.2 推荐推送顺序

先推送发布分支，再创建和推送 Tag：

```bash
git push origin feat/wechat:feat/wechat
git tag -a v1.0.3 <commit> -m 'v1.0.3'
git push origin refs/tags/v1.0.3
```

推送后验证：

```bash
git rev-parse feat/wechat
git rev-parse origin/feat/wechat
git ls-remote origin refs/heads/feat/wechat
git ls-remote --tags origin \
  'refs/tags/v1.0.3' 'refs/tags/v1.0.3^{}'
```

四个位置最终应指向预期发布提交。若 Tag 已先推送，也必须随后推送其所属发布分支并完成同样核对。

## 6. 微信小程序发布

### 6.1 上传前检查

- 使用 `uni-app/dist/build/mp-weixin` 生产构建目录；
- 确认 API 地址为正式环境；
- 确认首页、四个底部主页面、分享入口和本次修改页面可正常打开；
- 不把开发调试开关或“忽略合法域名校验”当作正式环境能力；
- 微信开发者工具中的版本号与 Git Tag 一致，但不带 `v`。

### 6.2 版本介绍

版本介绍只写用户能感知的变化，不写 commit 哈希、数据库迁移、内部重构或测试数量。建议控制为一段简洁中文，按“新增 → 优化 → 修复”排列。

模板：

```text
新增【用户可见能力】；优化【页面或交互】；修复【用户可感知问题】，提升使用稳定性。
```

`v1.0.3` 示例：

```text
优化部落成员与联赛数据展示，新增成员近期活动、部落战与联赛战绩、都城及竞赛贡献统计；新增联赛集结检查、进攻提醒和管理成员标识；优化成员筛选、状态提示、表格分页及横向滚动体验，并修复部分部落标签兼容问题。
```

### 6.3 微信平台人工步骤

以下步骤必须由具备权限的人员在微信开发者工具或公众平台完成：

1. 上传代码；
2. 填写与 Tag 一致的版本号和版本介绍；
3. 选择体验版并真机验收；
4. 提交审核；
5. 审核通过后确认发布；
6. 发布后从普通用户入口重新进入并复测。

上传成功、审核通过和正式发布是三个不同状态，交接记录中必须明确当前处于哪一步。

## 7. 后端上线

后端代码或 schema 有变化时，Tag 推送后仍需独立部署。

上线前：

- 执行 `source scripts/load_env.sh`；
- 涉及 schema、大批量写入或迁移时，先对 `data/league.db` 做 SQLite 一致性备份并运行 `PRAGMA integrity_check`；
- 不打印 `.env`、Token 或授权头；
- 不手动启动与生产竞争的 `uvicorn --reload`。

上线操作使用 systemd：

```bash
sudo systemctl restart sky-admin.service sky-scheduler.service
systemctl is-active sky-admin.service sky-scheduler.service
systemctl status --no-pager sky-admin.service sky-scheduler.service
```

上线后至少验证：

- `http://127.0.0.1:8000/api/ping`；
- `https://api.skycoc.cc/api/ping`；
- 本次改动涉及的实际业务接口；
- 相关 `sync_jobs` 的最近状态和运行时间；
- 服务日志中无持续异常。

外部 COC API 故障与本地服务故障必须区分。若官方接口不可用但本地服务和缓存回退正常，应明确标注外部依赖异常，不得通过清空缓存或盲目更换 Token 制造更大问题。

## 8. 发布验收清单

- [ ] 发布范围已经冻结；
- [ ] 实现与正式文档一致；
- [ ] 相关测试成功；
- [ ] 微信小程序生产构建成功；
- [ ] 真机检查关键页面；
- [ ] 发布 commit 已确认；
- [ ] 发布分支已推送且远端提交一致；
- [ ] annotated Tag 已创建并推送；
- [ ] Tag 解引用后的 commit 与发布 commit 一致；
- [ ] 后端变更已备份、部署并验证；
- [ ] 小程序版本号和版本介绍已填写；
- [ ] 已明确记录上传、审核、发布三个状态；
- [ ] 发布后完成普通用户入口复测。

## 9. 回滚原则

- 微信小程序优先使用微信公众平台已有的版本回退能力；
- 后端回滚前先确认数据库 schema 是否向后兼容，并保留当前生产库备份；
- 不使用 `git reset --hard` 或覆盖工作区的方式回滚；
- 已推送的错误 Tag 不强制改写，修复后发布新的修订版本；
- 回滚完成后仍需执行服务、接口、调度任务和小程序入口验收。

## 10. 发布记录建议

每次发布至少记录：

```text
版本：vX.Y.Z
发布 commit：<完整哈希>
发布分支：feat/wechat
后端状态：未部署 / 已部署并验证
小程序状态：未上传 / 体验版 / 审核中 / 已发布
验证结果：测试、构建、接口、真机
已知问题：无，或列出外部依赖/暂缓项
```

发布记录可以写入发布工单、GitHub Release 或当次交接说明；不要把密钥、用户隐私或生产数据库内容写入记录。
