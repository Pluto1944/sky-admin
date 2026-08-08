#!/bin/bash
# apply-patches.sh - 修复 uni-app vue-loader 在小程序编译时的兼容性问题
# 在 npm install 后执行此脚本

set -e

DIR="$(cd "$(dirname "$0")/.." && pwd)"
echo "Applying patches..."

# Patch 1: configure-webpack.js - updateJsLoader 防御性检查
TARGET1="$DIR/node_modules/@dcloudio/vue-cli-plugin-uni/lib/configure-webpack.js"
if grep -q "if (!matchRule || !matchRule.use) return" "$TARGET1" 2>/dev/null; then
  echo "  configure-webpack.js already patched"
else
  sed -i 's/function updateJsLoader (rawRules, fakeFile, checkLoaderRegex, loader) {\n    const matchRule = rawRules.find(createMatcher(fakeFile))\n\n    const matchUse = matchRule.use/function updateJsLoader (rawRules, fakeFile, checkLoaderRegex, loader) {\n    const matchRule = rawRules.find(createMatcher(fakeFile))\n    if (!matchRule || !matchRule.use) return\n\n    const matchUse = matchRule.use/' "$TARGET1"
  sed -i 's/if (matchLoaderUseIndex < 0) {\n      throw new Error(`No matching use for ${fakeFile}`)/if (matchLoaderUseIndex < 0) {\n      return/' "$TARGET1"
  echo "  configure-webpack.js patched"
fi

# Patch 2: templateLoader.js - 补充缺失的 export 变量
TARGET2="$DIR/node_modules/@dcloudio/vue-cli-plugin-uni/packages/vue-loader/lib/loaders/templateLoader.js"
if grep -q "var recyclableRender" "$TARGET2" 2>/dev/null; then
  echo "  templateLoader.js already patched"
else
  sed -i 's|return code + \`\\nexport { render, staticRenderFns, recyclableRender, components }\`|return code + \`\\nvar recyclableRender\\nvar components\\nexport { render, staticRenderFns, recyclableRender, components }\`|' "$TARGET2"
  echo "  templateLoader.js patched"
fi

echo "All patches applied."
