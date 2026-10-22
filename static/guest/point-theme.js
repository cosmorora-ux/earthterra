var sitePointTheme = document.documentElement.dataset.point || '';
function applyPointTheme() {
  const t = (typeof loopPointTheme !== 'undefined' && loopPointTheme) || sitePointTheme;
  if (document.documentElement.dataset.point !== t) document.documentElement.dataset.point = t;
}
