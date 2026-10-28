/* Chromium owns wheel/touchpad scrolling: no main-thread interception,
   forced layout reads or competing JavaScript animation clock. */
(() => {
  const style=document.createElement('style');
  style.textContent='*{scrollbar-width:none!important;scrollbar-gutter:auto!important}*::-webkit-scrollbar{display:none!important;width:0!important;height:0!important}';
  document.head.append(style);
})();
