#!/usr/bin/env node

'use strict'

const fs = require('fs')
const path = require('path')
const { execFileSync } = require('child_process')

const REPOSITORY_ROOT = path.resolve(__dirname, '..', '..')
const UNI_APP_ROOT = path.join(REPOSITORY_ROOT, 'uni-app')
const BUILD_ROOT = path.join(UNI_APP_ROOT, 'dist', 'build', 'mp-weixin')
const DEFAULT_KEY_PATH = '/etc/sky-admin/secrets/miniprogram-ci/private.wx6a46dda85a013a34.key'
const DEFAULT_QR_DIR = '/var/tmp/sky-admin/miniprogram-ci'
const PROXY_ENV_NAMES = [
  'HTTP_PROXY',
  'HTTPS_PROXY',
  'ALL_PROXY',
  'http_proxy',
  'https_proxy',
  'all_proxy',
  'npm_config_proxy',
  'npm_config_https_proxy'
]
const WECHAT_NO_PROXY_HOSTS = [
  'servicewechat.com',
  '.servicewechat.com',
  'mp.weixin.qq.com',
  '.mp.weixin.qq.com'
]

function fail(message) {
  throw new Error(message)
}

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, 'utf8'))
}

function runGit(args) {
  return execFileSync('git', args, {
    cwd: REPOSITORY_ROOT,
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe']
  }).trim()
}

function normalizeReleaseVersion(tagVersion) {
  const match = /^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.exec(tagVersion)
  if (!match) {
    fail(`VERSION 必须是 vX.Y.Z，当前值为 ${JSON.stringify(tagVersion)}`)
  }
  return {
    tag: tagVersion,
    plain: `${match[1]}.${match[2]}.${match[3]}`,
    code: String(Number(match[1]) * 10000 + Number(match[2]) * 100 + Number(match[3]))
  }
}

function mergeNoProxy(currentValue, requiredHosts = WECHAT_NO_PROXY_HOSTS) {
  const values = String(currentValue || '')
    .split(',')
    .map(value => value.trim())
    .filter(Boolean)
  const seen = new Set(values.map(value => value.toLowerCase()))
  for (const host of requiredHosts) {
    if (!seen.has(host.toLowerCase())) {
      values.push(host)
      seen.add(host.toLowerCase())
    }
  }
  return values.join(',')
}

function forceDirectWechatRouting(environment = process.env) {
  const existingNoProxy = environment.NO_PROXY || environment.no_proxy || ''
  for (const name of PROXY_ENV_NAMES) {
    delete environment[name]
  }
  const noProxy = mergeNoProxy(existingNoProxy)
  environment.NO_PROXY = noProxy
  environment.no_proxy = noProxy
}

function parseArgs(argv) {
  const command = argv[0]
  if (!['check', 'preview', 'upload'].includes(command)) {
    fail('用法：node scripts/miniprogram-ci.js <check|preview|upload> [--desc 文本] [--output 文件] [--robot 1-30]')
  }

  const options = { command }
  for (let index = 1; index < argv.length; index += 1) {
    const argument = argv[index]
    if (!argument.startsWith('--')) {
      fail(`无法识别的参数：${argument}`)
    }
    const equalAt = argument.indexOf('=')
    const name = equalAt === -1 ? argument.slice(2) : argument.slice(2, equalAt)
    const inlineValue = equalAt === -1 ? null : argument.slice(equalAt + 1)
    if (!['desc', 'output', 'robot'].includes(name)) {
      fail(`无法识别的选项：--${name}`)
    }
    const value = inlineValue === null ? argv[++index] : inlineValue
    if (value === undefined || value.startsWith('--')) {
      fail(`选项 --${name} 缺少值`)
    }
    options[name] = value
  }
  return options
}

function assertKeyFile(keyPath) {
  const resolved = path.resolve(keyPath)
  if (resolved === REPOSITORY_ROOT || resolved.startsWith(`${REPOSITORY_ROOT}${path.sep}`)) {
    fail('代码上传密钥不能放在 Git 仓库内')
  }
  const stat = fs.lstatSync(resolved)
  if (stat.isSymbolicLink() || !stat.isFile() || stat.size === 0) {
    fail('代码上传密钥必须是非空普通文件，不能是符号链接')
  }
  const permissions = stat.mode & 0o777
  if ((permissions & 0o027) !== 0) {
    fail(`代码上传密钥权限过宽：${permissions.toString(8)}，要求禁止组写入及其他用户访问`)
  }
  fs.accessSync(resolved, fs.constants.R_OK)
  return resolved
}

function readReleaseMetadata() {
  const tag = fs.readFileSync(path.join(REPOSITORY_ROOT, 'VERSION'), 'utf8').trim()
  const version = normalizeReleaseVersion(tag)
  const manifest = readJson(path.join(UNI_APP_ROOT, 'manifest.json'))
  const packageJson = readJson(path.join(UNI_APP_ROOT, 'package.json'))
  const releaseSource = fs.readFileSync(path.join(UNI_APP_ROOT, 'config', 'release.js'), 'utf8')
  const releaseMatch = /APP_VERSION\s*=\s*['"]([^'"]+)['"]/.exec(releaseSource)
  const builtProject = readJson(path.join(BUILD_ROOT, 'project.config.json'))

  const appids = [manifest.appid, manifest['mp-weixin'] && manifest['mp-weixin'].appid, builtProject.appid]
  if (appids.some(appid => !appid) || new Set(appids).size !== 1) {
    fail(`AppID 不一致：${appids.map(value => value || '<empty>').join(', ')}`)
  }
  if (manifest.versionName !== version.plain || packageJson.version !== version.plain) {
    fail(`版本不一致：VERSION=${version.tag}, manifest=${manifest.versionName}, package=${packageJson.version}`)
  }
  if (String(manifest.versionCode) !== version.code) {
    fail(`manifest.versionCode 应为 ${version.code}，当前为 ${manifest.versionCode}`)
  }
  if (!releaseMatch || releaseMatch[1] !== version.tag) {
    fail(`config/release.js 必须声明 APP_VERSION=${version.tag}`)
  }
  if (builtProject.compileType !== 'miniprogram') {
    fail(`构建产物 compileType 非 miniprogram：${builtProject.compileType}`)
  }
  if (!fs.existsSync(path.join(BUILD_ROOT, 'app.json'))) {
    fail('缺少生产构建产物 app.json')
  }

  return {
    appid: appids[0],
    version,
    commit: runGit(['rev-parse', 'HEAD']),
    branch: runGit(['branch', '--show-current'])
  }
}

function parseLsRemote(output) {
  const rows = new Map()
  for (const line of output.split('\n')) {
    if (!line.trim()) continue
    const [commit, ref] = line.trim().split(/\s+/)
    rows.set(ref, commit)
  }
  return rows
}

function assertReleaseGitState(metadata) {
  if (runGit(['status', '--porcelain', '--untracked-files=all'])) {
    fail('上传前 Git 工作区必须干净')
  }
  const tagRef = `refs/tags/${metadata.version.tag}`
  let tagType
  try {
    tagType = runGit(['cat-file', '-t', tagRef])
  } catch (error) {
    fail(`当前版本缺少本地 Tag：${metadata.version.tag}`)
  }
  if (tagType !== 'tag') {
    fail(`${metadata.version.tag} 必须是 annotated tag`)
  }
  if (runGit(['rev-list', '-n', '1', tagRef]) !== metadata.commit) {
    fail(`${metadata.version.tag} 未指向当前提交`)
  }

  const remoteOutput = runGit([
    'ls-remote',
    'origin',
    `refs/heads/${metadata.branch}`,
    tagRef,
    `${tagRef}^{}`
  ])
  const remoteRefs = parseLsRemote(remoteOutput)
  if (remoteRefs.get(`refs/heads/${metadata.branch}`) !== metadata.commit) {
    fail(`远端分支 origin/${metadata.branch} 未指向当前提交`)
  }
  if (remoteRefs.get(`${tagRef}^{}`) !== metadata.commit) {
    fail(`远端 annotated Tag ${metadata.version.tag} 未指向当前提交`)
  }
}

function resolveRobot(value) {
  const robot = Number(value || process.env.MINIPROGRAM_CI_ROBOT || '1')
  if (!Number.isInteger(robot) || robot < 1 || robot > 30) {
    fail('CI 机器人编号必须是 1 到 30 的整数')
  }
  return robot
}

function timestamp() {
  return new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d{3}Z$/, 'Z')
}

function ensurePreviewOutput(value, version) {
  const output = value
    ? path.resolve(value)
    : path.join(process.env.MINIPROGRAM_CI_QR_DIR || DEFAULT_QR_DIR, `preview-${version}-${timestamp()}.jpg`)
  const outputDirectory = path.dirname(output)
  fs.mkdirSync(outputDirectory, { recursive: true, mode: 0o700 })
  const directoryPermissions = fs.statSync(outputDirectory).mode & 0o777
  if ((directoryPermissions & 0o077) !== 0) {
    fail(`二维码目录权限过宽：${directoryPermissions.toString(8)}，要求仅当前用户可访问`)
  }
  if (fs.existsSync(output)) {
    fail(`拒绝覆盖已有二维码文件：${output}`)
  }
  return output
}

async function execute(options) {
  forceDirectWechatRouting()
  const keyPath = assertKeyFile(process.env.MINIPROGRAM_CI_PRIVATE_KEY_PATH || DEFAULT_KEY_PATH)
  const metadata = readReleaseMetadata()
  const robot = resolveRobot(options.robot)
  try {
    require.resolve('miniprogram-ci')
  } catch (error) {
    fail('CI 工具依赖未安装，请先运行 bash tools/miniprogram-ci/install.sh')
  }

  console.log(`预检通过：appid=${metadata.appid} version=${metadata.version.plain} commit=${metadata.commit.slice(0, 12)} robot=${robot}`)
  console.log('网络策略：微信上传域名强制直连，当前进程不使用 HTTP(S) 代理')

  if (options.command === 'check') {
    console.log('本地 CI 配置检查完成；未调用微信接口')
    return
  }

  if (options.command === 'upload') {
    if (!options.desc || !options.desc.trim()) {
      fail('上传必须通过 --desc 提供用户可见的版本介绍')
    }
    if (options.desc.trim().length > 200) {
      fail('版本介绍不能超过 200 个字符')
    }
    assertReleaseGitState(metadata)
  }

  const ci = require('miniprogram-ci')
  const project = new ci.Project({
    appid: metadata.appid,
    type: 'miniProgram',
    projectPath: BUILD_ROOT,
    privateKeyPath: keyPath,
    ignores: ['node_modules/**/*']
  })
  const common = {
    project,
    robot,
    setting: { useProjectConfig: true }
  }

  if (options.command === 'preview') {
    const output = ensurePreviewOutput(options.output, metadata.version.plain)
    await ci.preview({
      ...common,
      desc: (options.desc || `预览 ${metadata.version.plain} ${metadata.commit.slice(0, 12)}`).trim(),
      qrcodeFormat: 'image',
      qrcodeOutputDest: output
    })
    fs.chmodSync(output, 0o600)
    console.log(`体验预览二维码已生成：${output}`)
    return
  }

  const result = await ci.upload({
    ...common,
    version: metadata.version.plain,
    desc: options.desc.trim()
  })
  const packages = Array.isArray(result && result.subPackageInfo) ? result.subPackageInfo.length : 0
  console.log(`微信开发版本上传成功：version=${metadata.version.plain} commit=${metadata.commit} packages=${packages}`)
}

async function main() {
  try {
    await execute(parseArgs(process.argv.slice(2)))
  } catch (error) {
    console.error(`miniprogram-ci 失败：${error.message}`)
    process.exitCode = 1
  }
}

if (require.main === module) {
  main()
}

module.exports = {
  forceDirectWechatRouting,
  mergeNoProxy,
  normalizeReleaseVersion,
  parseArgs,
  parseLsRemote,
  resolveRobot
}
