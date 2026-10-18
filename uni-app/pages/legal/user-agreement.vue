<template>
  <view class="page">
    <scroll-view scroll-y class="scroll">
      <view class="content">
        <text class="title">苍穹联赛助手用户协议</text>
        <text class="updated">更新日期：2026年10月12日</text>
        <text class="heading">一、服务说明</text>
        <text class="paragraph">苍穹联赛助手为《部落冲突》玩家和联盟提供成员、部落战、联赛、运营管理与数据查询服务。你可以在阅读并同意本协议后选择使用微信登录及相关功能。</text>
        <text class="heading">二、账号与使用</text>
        <text class="paragraph">你应使用本人微信账号并提供真实、准确的游戏账号信息。请勿利用本服务进行违法活动、恶意请求接口或干扰其他用户正常使用。</text>
        <text class="heading">三、联盟、角色与分享</text>
        <text class="paragraph">联盟首领和管理员应仅在获得相应部落授权后管理部落。通过联盟邀请加入的用户默认仅获得普通成员身份，分享者的管理权限不会传递。被移除、封禁或联盟暂停后，相关访问权限会立即受到限制。</text>
        <text class="heading">四、认证与套餐</text>
        <text class="paragraph">部落认证当前由运营方人工处理，认证按钮不代表自动通过。免费版最多管理3个部落，普通会员和高级会员最多管理10个部落；免费版与普通会员支持页面打开、下拉和按钮触发的按需刷新，高级会员增加后台高频自动刷新。会员权益由运营方人工开通并以页面显示的有效期为准；未接入在线支付前，本服务不会通过小程序自动扣费。</text>
        <text class="heading">五、数据来源与可用性</text>
        <text class="paragraph">部落成员和战绩信息来自你授权使用的游戏账号、部落管理数据及相关公开接口。由于第三方接口或网络原因，展示数据可能存在延迟。</text>
        <text class="heading">六、协议变更</text>
        <text class="paragraph">我们会在本页面更新协议内容。重要变更会在小程序中提示，你可以选择停止使用相关服务。</text>
        <text class="heading">七、联系我们</text>
        <text class="paragraph">如需注销账号、反馈问题或咨询协议，请通过小程序“管理”页面联系运营方。</text>
      </view>
    </scroll-view>
  </view>
</template>

<style scoped>
.page { min-height: 100vh; background: #0f0f23; }
.scroll { height: 100vh; box-sizing: border-box; }
.content { padding: 36rpx 34rpx 80rpx; display: flex; flex-direction: column; }
.title { color: #fff; font-size: 40rpx; font-weight: 700; margin-bottom: 14rpx; }
.updated { color: #777f96; font-size: 22rpx; margin-bottom: 34rpx; }
.heading { color: #d9e3f0; font-size: 30rpx; font-weight: 600; margin-top: 24rpx; margin-bottom: 12rpx; }
.paragraph { color: #b9c0cf; font-size: 27rpx; line-height: 1.8; }
</style>
