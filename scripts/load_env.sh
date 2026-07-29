#!/usr/bin/env bash
#
# 公共环境变量加载器：被其它脚本 source。
#   source "$(dirname "$0")/load_env.sh"
#
# 从项目根 .env 读取 KEY=VALUE 到环境变量。安全考虑：
#   - 不使用 `source .env`（避免 .env 内命令/特殊字符被执行，防注入）；
#   - 逐行解析，跳过空行与 # 注释，去除首尾空白与可选的成对引号；
#   - 已在当前环境显式 export 的同名变量优先，不被 .env 覆盖（便于临时覆写）。

# 定位项目根（本文件在 scripts/ 下）
_ENV_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
_ENV_FILE="${ENV_FILE:-$_ENV_ROOT/.env}"

if [[ ! -f "$_ENV_FILE" ]]; then
  echo "错误: 未找到 .env（$_ENV_FILE）。请先复制模板并填入凭证：" >&2
  echo "  cp .env.example .env" >&2
  exit 1
fi

while IFS= read -r _line || [[ -n "$_line" ]]; do
  # 去掉行尾 CR（兼容 CRLF 文件）
  _line="${_line%$'\r'}"
  # 跳过空行与注释
  [[ -z "$_line" || "$_line" =~ ^[[:space:]]*# ]] && continue
  # 必须是 KEY=VALUE 形式
  [[ "$_line" != *"="* ]] && continue

  _key="${_line%%=*}"
  _val="${_line#*=}"
  # 去除 key 首尾空白
  _key="${_key#"${_key%%[![:space:]]*}"}"
  _key="${_key%"${_key##*[![:space:]]}"}"
  # key 合法性校验（仅字母数字下划线，且非数字开头）
  [[ "$_key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
  # 去除 value 首尾空白
  _val="${_val#"${_val%%[![:space:]]*}"}"
  _val="${_val%"${_val##*[![:space:]]}"}"
  # 去除成对包裹的引号
  if [[ "$_val" == \"*\" && "$_val" == *\" ]]; then
    _val="${_val%\"}"; _val="${_val#\"}"
  elif [[ "$_val" == \'*\' && "$_val" == *\' ]]; then
    _val="${_val%\'}"; _val="${_val#\'}"
  fi

  # 当前环境已显式设置（非空）的同名变量优先，不覆盖
  if [[ -z "${!_key:-}" ]]; then
    export "$_key=$_val"
  fi
done < "$_ENV_FILE"

unset _line _key _val _ENV_FILE _ENV_ROOT
