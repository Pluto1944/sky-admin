<template>
  <view class="page">
    <scroll-view scroll-y class="scroll">
      <view class="content">
        <text class="title">苍穹联赛助手隐私政策</text>
        <text class="updated">更新日期：2026年10月15日</text>
        <text class="heading">一、我们收集什么信息</text>
        <text class="paragraph">在你主动勾选同意并使用服务时，我们会处理微信登录所需的临时登录凭证、应用内账号标识，以及你主动选择或填写的小程序昵称、游戏昵称和玩家标签。小程序昵称不是登录必需信息，你可以暂不设置。使用成员、联赛、战绩、联盟分享和管理功能时，还会处理相关的联盟成员关系、角色、部落认证状态、套餐状态、操作审计及公开游戏数据。</text>
        <text class="heading">二、我们如何使用信息</text>
        <text class="paragraph">上述信息仅用于完成登录、在联盟成员和申请列表中展示你选择的小程序昵称、绑定游戏账号、展示部落成员、联赛和战绩、建立你主动加入的联盟关系、执行权限控制并保障服务安全。使用微信昵称建议前，微信会展示平台《用户隐私保护指引》，只有在你主动同意后才会启用；拒绝后仍可手工填写或暂不设置昵称。登录后只有在你主动点击“复制 OpenID”或“复制邀请参数”时，才会将相应文本写入系统剪切板；小程序不会读取剪切板中原有内容。联盟成员列表和平台页面不会直接展示完整 OpenID。我们不会将个人信息出售给第三方，也不会将其用于与本服务无关的营销。</text>
        <text class="heading">三、第三方服务</text>
        <text class="paragraph">为提供登录和游戏数据查询，我们会与微信及游戏数据接口进行必要的数据交互。我们只发送完成对应功能所需的信息，并要求服务方按照其隐私规则处理数据。</text>
        <text class="heading">四、保存与删除</text>
        <text class="paragraph">账号资料和联盟关系在你使用服务期间保存；收到删除请求并完成身份核验后，我们会删除与账号直接关联且不再需要的信息。依法或为安全审计、争议处理所必需的记录会在相应期限内保留。停用联盟、移除订阅或套餐到期不会删除不以微信身份为所有者的公共战争历史。你可以在“管理”页面退出登录，并通过运营方申请查询、更正或删除与账号相关的信息。</text>
        <text class="heading">五、你的选择</text>
        <text class="paragraph">登录按钮在未勾选同意前不可用。你可以随时停止使用服务；隐私政策更新后，我们会再次请求你的确认。</text>
        <text class="heading">六、联系我们</text>
        <text class="paragraph">如对隐私保护有疑问或需要行使相关权利，请通过小程序“管理”页面联系运营方。</text>
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
