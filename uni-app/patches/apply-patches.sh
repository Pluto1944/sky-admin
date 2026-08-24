#!/bin/bash
# apply-patches.sh - 修复 uni-app vue-loader 在小程序编译时的兼容性问题
# 在 npm install 后执行此脚本
#
# 说明：原脚本用 sed 做多行匹配，但把换行符写成了字面的 \n / \\n，
# 导致永远匹配不上、补丁从未真正生效。现改用 python3 做精确字符串替换，
# 更可靠，且幂等（重复执行安全）。

set -e

DIR="$(cd "$(dirname "$0")/.." && pwd)"
echo "Applying patches..."

if ! command -v python3 >/dev/null 2>&1; then
  echo "  ERROR: python3 not found, patches not applied" >&2
  exit 1
fi

python3 - "$DIR" <<'PYEOF'
import sys, os

base = sys.argv[1]

def patch_file(rel, replacements):
    path = os.path.join(base, rel)
    if not os.path.exists(path):
        print(f"  SKIP (not found): {rel}")
        return
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    original = content
    for old, new, desc in replacements:
        if old in content:
            content = content.replace(old, new)
            print(f"  PATCHED {desc}: {rel}")
        else:
            print(f"  already patched / no match: {desc}")
    if content != original:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)

# Patch 1: configure-webpack.js - updateJsLoader 增加 matchRule.use 空值检查，
# 避免 webpack 规则不匹配时 matchRule.use 为 undefined 导致崩溃。
patch_file(
    "node_modules/@dcloudio/vue-cli-plugin-uni/lib/configure-webpack.js",
    [
        (
            "    const matchRule = rawRules.find(createMatcher(fakeFile))\n\n    const matchUse = matchRule.use",
            "    const matchRule = rawRules.find(createMatcher(fakeFile))\n    if (!matchRule || !matchRule.use) return\n\n    const matchUse = matchRule.use",
            "configure-webpack.js updateJsLoader null-check",
        ),
        (
            "    if (matchLoaderUseIndex < 0) {\n      throw new Error(`No matching use for ${fakeFile}`)",
            "    if (matchLoaderUseIndex < 0) {\n      return",
            "configure-webpack.js throw -> return",
        ),
    ],
)

# Patch 2: templateLoader.js - 补充缺失的 recyclableRender / components 变量声明，
# 避免编译产物出现 "Export 'recyclableRender' is not defined"。
patch_file(
    "node_modules/@dcloudio/vue-cli-plugin-uni/packages/vue-loader/lib/loaders/templateLoader.js",
    [
        (
            "return code + `\\nexport { render, staticRenderFns, recyclableRender, components }`",
            "return code + `\\nvar recyclableRender\\nvar components\\nexport { render, staticRenderFns, recyclableRender, components }`",
            "templateLoader.js recyclableRender/components",
        ),
    ],
)

print("All patches applied.")
PYEOF
