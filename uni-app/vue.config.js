const path = require('path');

// 设置源码目录（当前目录，因为 vue/manifest/pages 都在根目录）
process.env.UNI_INPUT_DIR = __dirname;

module.exports = {
  transpileDependencies: ['@dcloudio/uni-ui'],
  outputDir: path.resolve(__dirname, 'dist/build/mp-weixin')
};
