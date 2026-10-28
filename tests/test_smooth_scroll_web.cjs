const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const styles=[];
vm.runInNewContext(fs.readFileSync('assets/approved-ui/smooth-scroll.js','utf8'), {
  document:{createElement:()=>({}),head:{append:style=>styles.push(style.textContent)},
    addEventListener:()=>{throw Error('Scrolling must not intercept native input');}},
  setTimeout:()=>{throw Error('Scrolling must not use a timer');},
  requestAnimationFrame:()=>{throw Error('Scrolling must not use a script frame clock');},
  getComputedStyle:()=>{throw Error('Scrolling must not force layout reads');}
});
assert(styles[0].includes('scrollbar-width:none'));
assert(!styles[0].includes('overflow:hidden'));
console.log('Native scrolling delegation: no wheel interception, timers or forced layouts.');
