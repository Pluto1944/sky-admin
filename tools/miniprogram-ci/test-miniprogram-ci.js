#!/usr/bin/env node

'use strict'

// Keep the release guard helpers testable without contacting WeChat.

const assert = require('assert')
const {
  forceDirectWechatRouting,
  mergeNoProxy,
  normalizeReleaseVersion,
  parseArgs,
  parseLsRemote,
  resolveRobot
} = require('./miniprogram-ci')

assert.deepStrictEqual(normalizeReleaseVersion('v1.10.2'), {
  tag: 'v1.10.2',
  plain: '1.10.2',
  code: '11002'
})
assert.throws(() => normalizeReleaseVersion('1.10.2'), /vX.Y.Z/)

assert.strictEqual(
  mergeNoProxy('localhost,servicewechat.com'),
  'localhost,servicewechat.com,.servicewechat.com,mp.weixin.qq.com,.mp.weixin.qq.com'
)
const environment = {
  HTTP_PROXY: 'http://secret-proxy.invalid',
  https_proxy: 'http://secret-proxy.invalid',
  NO_PROXY: 'localhost'
}
forceDirectWechatRouting(environment)
assert.strictEqual(environment.HTTP_PROXY, undefined)
assert.strictEqual(environment.https_proxy, undefined)
assert.match(environment.NO_PROXY, /servicewechat\.com/)
assert.strictEqual(environment.NO_PROXY, environment.no_proxy)

assert.deepStrictEqual(parseArgs(['upload', '--desc', '新版本', '--robot=2']), {
  command: 'upload',
  desc: '新版本',
  robot: '2'
})
assert.throws(() => parseArgs(['delete']), /用法/)
assert.throws(() => parseArgs(['preview', '--unknown', 'x']), /无法识别/)
assert.throws(() => parseArgs(['preview', '--desc']), /缺少值/)
assert.strictEqual(resolveRobot('30'), 30)
assert.throws(() => resolveRobot('31'), /1 到 30/)

assert.deepStrictEqual(
  parseLsRemote('abc\trefs/heads/feat/wechat\ndef\trefs/tags/v1.2.3^{}\n'),
  new Map([
    ['refs/heads/feat/wechat', 'abc'],
    ['refs/tags/v1.2.3^{}', 'def']
  ])
)

console.log('miniprogram-ci helper tests passed')
