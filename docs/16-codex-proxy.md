# Codex 远程开发代理

本文记录 `115.159.64.19` 上 VS Code Remote Codex 扩展的代理配置、影响范围和维护方法。该配置仅用于解决服务器直连 OpenAI 不稳定或不可达的问题，不属于 `sky-admin` 的生产运行依赖。

> 安全要求：不得把代理订阅地址、访问令牌、节点信息、OpenAI 认证文件或其他凭据写入本仓库。

## 当前架构

```text
VS Code Remote Codex
        |
        | HTTP(S)/SOCKS 代理
        v
127.0.0.1:7890 (Mihomo)
        |
        v
OpenAI 官方服务
```

- Mihomo 以 Ubuntu 用户级 systemd 服务运行。
- 代理只监听 `127.0.0.1:7890`，不向公网或局域网开放。
- Codex 扩展通过专用启动脚本设置代理环境变量。
- `sky-admin`、Nginx、数据库、Docker、Git、SSH 和其他 VS Code 扩展默认不使用该代理。
- `~/.vscode-server/server-env-setup` 已删除，不应使用它设置 VS Code Remote 全局代理。

## 配置位置

| 用途 | 路径 |
| --- | --- |
| Mihomo 程序 | `~/.local/bin/mihomo` |
| Mihomo 配置 | `~/.config/mihomo/config.yaml` |
| GeoIP 数据 | `~/.config/mihomo/geoip.metadb` |
| 用户级 systemd 单元 | `~/.config/systemd/user/codex-mihomo.service` |
| Codex 扩展目录 | `~/.vscode-server/extensions/openai.chatgpt-*/bin/linux-x86_64/` |
| Codex 专用启动脚本 | 上述目录中的 `codex` |
| 原始 Codex 二进制 | 上述目录中的 `codex.real` |
| Codex 认证状态 | `~/.codex/`，敏感，不得查看或输出认证文件内容 |
| 命令行 Codex CLI | `~/.local/bin/codex` → `~/.local/share/codex/<版本>/bin/codex` |
| CLI 专用启动脚本 | 上述版本目录中的 `codex` |
| CLI 原始二进制 | 上述版本目录中的 `codex.real` |

Codex 启动脚本（扩展与命令行 CLI 共用同一套变量）为当前进程设置以下变量：

```text
HTTP_PROXY=http://127.0.0.1:7890
HTTPS_PROXY=http://127.0.0.1:7890
ALL_PROXY=socks5://127.0.0.1:7890
NO_PROXY=127.0.0.1,localhost
```

### 命令行 Codex CLI 的代理

命令行 `codex` 与扩展复用同一个 Mihomo 代理，方式与扩展启动脚本一致：将真实二进制改名为 `codex.real`，再用同名 shell 脚本设置代理变量后 `exec codex.real`。

命令行 CLI 通过软链 `~/.local/bin/codex` 指向版本目录，因此启动脚本需用 `readlink -f` 解析软链后再定位真实二进制：

```sh
#!/bin/sh
export HTTP_PROXY=http://127.0.0.1:7890
export HTTPS_PROXY=http://127.0.0.1:7890
export ALL_PROXY=socks5://127.0.0.1:7890
export NO_PROXY=127.0.0.1,localhost
export http_proxy="$HTTP_PROXY"
export https_proxy="$HTTPS_PROXY"
export all_proxy="$ALL_PROXY"
export no_proxy="$NO_PROXY"
BIN_DIR="$(dirname "$(readlink -f "$0")")"
exec "$BIN_DIR/codex.real" "$@"
```

验证时直接裸调 `codex`（不带任何代理环境变量）即可，若返回正常说明代理已由启动脚本自动注入：

```bash
codex --version
codex login status
codex exec "只回复两个字：正常"
```

## 日常检查

检查代理服务和监听地址：

```bash
systemctl --user is-active codex-mihomo
systemctl --user is-enabled codex-mihomo
ss -lntp | grep ':7890'
```

预期服务为 `active`、`enabled`，且只监听 `127.0.0.1:7890`。

在不发送凭据的情况下验证 OpenAI 网络：

```bash
curl -sS -o /dev/null \
  -w '%{http_code} %{time_total}\n' \
  --connect-timeout 8 --max-time 20 \
  -x http://127.0.0.1:7890 \
  https://api.openai.com/v1/models
```

返回 `401` 表示已经连到 OpenAI，只是该诊断请求没有携带认证信息；`000`、超时或连接拒绝表示网络或本地代理异常。

检查 Codex 登录方式时，只运行状态命令，不读取 `~/.codex/auth.json`：

```bash
~/.vscode-server/extensions/openai.chatgpt-*/bin/linux-x86_64/codex login status
```

正常情况下应显示 `Logged in using ChatGPT`。

## 常见故障

### iOS App 连接后对话无响应

现象：iOS Codex App 通过 SSH 连上服务器、能正常认证，但对话一直无响应或卡住；此时命令行 `codex exec` 通常仍能正常工作（它走独立会话，不经 app-server）。

根因：多个 Codex 实例（VS Code 插件、iOS App，以及残留的孤儿 `app-server` 进程）共享同一套 `~/.codex/` 状态，互相争抢 thread 写锁，导致新连接创建会话失败。表现为 `~/.codex/app-server-control/app-server.log` 中反复出现 `thread-store conflict: thread ... already has an active writer`。

排查：

```bash
# 查看所有 app-server 进程，重点关注 PPID=1 的孤儿进程和重复实例
ps -eo pid,ppid,lstart,etime,cmd | grep -i 'app-server'

# 查看 app-server 日志（去除 ANSI 颜色码）
sed 's/\x1b\[[0-9;]*m//g' ~/.codex/app-server-control/app-server.log | tail -20
```

恢复：终止冲突的残留 `app-server` 进程（尤其是 PPID=1 的孤儿进程），iOS App 会自动重连并启动干净的 app-server；清理后日志应不再新增 `thread-store conflict` 错误。

注意：`app-server.log` 中出现的 `403 Country, region, or territory not supported` 属于历史登录 token 交换失败的旧记录，需结合时间戳判断是否与本次连接相关，不要仅凭该错误误判为代理问题。清理进程会影响 VS Code 插件与 iOS App 的当前连接，操作前应确认无正在进行的会话。

1. 检查 `codex-mihomo` 是否为 `active`。
2. 检查 `127.0.0.1:7890` 是否正在监听。
3. 使用上面的 `curl` 命令验证 OpenAI 连通性。
4. 在 VS Code 执行 `Developer: Reload Window`，使 Codex 扩展重新启动。
5. 如果 Codex 扩展刚升级，检查专用启动脚本是否被覆盖。

### 扩展升级后代理失效

VS Code 更新 OpenAI 扩展时可能创建新的版本目录，并恢复官方 `codex` 二进制。此时新的扩展目录可能没有 `codex.real` 和专用启动脚本。

恢复时应：

1. 确认新的 `openai.chatgpt-*` 目录是当前启用版本。
2. 将官方 `codex` 二进制重命名为同目录下的 `codex.real`。
3. 重新安装只包含上述代理变量、最终执行 `codex.real "$@"` 的启动脚本。
4. 执行 `Developer: Reload Window`。
5. 检查新 Codex 进程的环境及实际对话能力。

不要修改旧扩展目录来代替确认当前启用版本，也不要在脚本中写入代理订阅或 OpenAI 凭据。

### 命令行 CLI 升级后代理失效

运行 `codex update` 或重装 CLI 后，版本目录会更新，可能恢复官方 `codex` 二进制、覆盖启动脚本，导致代理失效。

恢复时应：

1. 确认新的 `~/.local/share/codex/<版本>/bin/` 目录是当前生效版本。
2. 将官方 `codex` 二进制重命名为同目录下的 `codex.real`。
3. 重新安装上文「命令行 Codex CLI 的代理」中的启动脚本。
4. 确认 `~/.local/bin/codex` 软链仍指向当前版本目录。
5. 用 `codex --version` 和 `codex exec` 验证。

不要在脚本中写入代理订阅或 OpenAI 凭据。

### Mihomo 无法启动

查看用户服务日志：

```bash
journalctl --user -u codex-mihomo -n 100 --no-pager
```

日志可能包含代理节点名称或目标域名，复制到工单、聊天或仓库前必须脱敏。若提示 GeoIP 数据损坏，应从 Mihomo/MetaCubeX 官方发布源重新获取对应数据文件，不要使用未知来源文件。

## 影响和流量

- 代理故障只应影响 Codex 联网，不应停止 `sky-admin` 后台服务。
- 代理会增加少量 CPU、内存、网络延迟和订阅流量。
- Codex 流量主要来自提示、相关代码片段、命令输出和模型响应；仓库不会仅因体积较大而在每次对话中整体上传。
- 避免反复把大型日志、构建产物、数据库导出、压缩包或图片送入上下文。
- Git 拉取、依赖下载和 Docker 镜像默认不经过该代理，除非以后另行显式配置。

## 停用和移除

临时停用代理服务：

```bash
systemctl --user stop codex-mihomo
```

取消自动启动：

```bash
systemctl --user disable codex-mihomo
```

恢复 Codex 官方二进制前，应先关闭 Codex 扩展进程，然后在当前启用的扩展目录中确认 `codex.real` 确实是 ELF 可执行文件，再将其恢复为 `codex`。这是覆盖操作，必须先核对准确路径和文件类型。

删除代理程序、配置、systemd 单元或认证信息属于破坏性操作，必须单独确认；不得顺带删除 `~/.codex`。

## 安全与维护

- 代理订阅配置权限应保持为仅 Ubuntu 用户可读。
- 不要开放 `7890` 到 `0.0.0.0`，也不要添加安全组或防火墙公网放行规则。
- 不要提交 `~/.config/mihomo/config.yaml`、`~/.codex/` 或任何订阅内容。
- 订阅地址一旦出现在不可信位置，应在服务商后台重置。
- 代理节点运营方可观察连接目标、时间和流量大小；OpenAI HTTPS 正文仍由 TLS 加密。
- 修改代理、SSH、防火墙、DNS 或 systemd 配置前，需要获得明确授权。
