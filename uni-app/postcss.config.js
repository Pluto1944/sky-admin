module.exports = {
  plugins: [
    require('autoprefixer')({
      overrideBrowserslist: ['Android >= 4.4', 'ios >= 9']
    })
  ]
};
