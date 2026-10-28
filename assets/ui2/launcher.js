/* Presentation-only routes/components. Existing Python owners perform every mutation. */
(() => {
  'use strict';
  const app=document.querySelector('.app'), content=document.querySelector('#content');
  const {icon,esc,eattr}=window.NexusComponents;
  const names={home:'Главная',library:'Мои сборки',saved:'Мои миры',catalog:'Каталог миров',server:'Мир NEXUS',profile:'Профиль',settings:'Настройки',downloads:'Загрузки',logs:'Логи',mods:'Моды сервера',studio:'Студия',tech:'Control Center'};
  let state=null, route='home', serverId='', nativeRoute='library', notificationTimer=0;
  const queries={catalog:''}, filters={catalog:'all'}, scrolls=new Map(), trail=[];
  document.querySelectorAll('[data-icon]').forEach(node=>node.innerHTML=icon(node.dataset.icon));
  function action(name,id='') { location.href='/ui-action/'+name+(id?'?id='+encodeURIComponent(id):''); }
  function navSync() {
    document.querySelectorAll('.sidebar [data-route]').forEach(button=>{const selected=!button.classList.contains('subtle')&&(button.dataset.route===route&&route!=='server'||route==='server'&&button.dataset.id===serverId);button.classList.toggle('active',selected);if(selected)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');});
    document.querySelector('#route-name').textContent=names[route]||'NEXUS';
    document.title='NEXUS · '+(names[route]||'Мир');
  }
  function render(focus=false) {
    if(!state)return;
    const oldScroll=content.scrollTop;
    const {home,catalog,profile,server}=window.NexusScreens.create(state,queries,filters,serverId);
    const markup=route==='home'?home():route==='catalog'?catalog():route==='saved'?catalog(true):route==='profile'?profile():route==='server'?server():'';
    if(markup){content.innerHTML=`<div class="page">${markup}</div>`;if(route==='profile')window.NexusSkin?.mount(document.querySelector('#skin-panel'));}
    content.scrollTop=focus?(scrolls.get(route+serverId)||0):oldScroll;
    navSync();
    if(focus)content.focus({preventScroll:true});
  }
  function navigate(next,id='',remember=true) {
    if(next===route&&id===serverId&&next!=='catalog')return;
    scrolls.set(route+serverId,content.scrollTop);
    if(remember)trail.push({route,id:serverId});
    route=next;serverId=id;
    navSync();
    if(['support','library','settings','downloads','logs','studio'].includes(route))action(route);
    else {app.classList.remove('desktop-native-library');render(true);if(route==='server')action('select-server',id);else action('leave');}
    document.querySelector('#history-back').disabled=!trail.length;
  }
  function notify(message) {const node=document.querySelector('#notification');node.textContent=message;node.hidden=false;clearTimeout(notificationTimer);notificationTimer=setTimeout(()=>node.hidden=true,5000);}
  document.addEventListener('click',event=>{
    const button=event.target.closest('button');if(!button||button.disabled)return;
    if(button.dataset.route){if(button.dataset.route==='catalog'&&button.closest('.empty')){queries.catalog='';filters.catalog='all';}navigate(button.dataset.route,button.dataset.id||'');}
    else if(button.dataset.action)action(button.dataset.action,button.dataset.id||'');
    else if(button.dataset.filter){filters.catalog=button.dataset.filter;render();}
    else if(button.id==='clear-search'){queries.catalog='';render();document.querySelector('#world-search')?.focus();}
  });
  document.addEventListener('input',event=>{if(event.target.id==='world-search'){queries.catalog=event.target.value;const query=queries.catalog.toLocaleLowerCase('ru');const worlds=state.worlds.filter(world=>(world.name+' '+world.description+' '+world.category).toLocaleLowerCase('ru').includes(query)&&(filters.catalog==='all'||(filters.catalog==='local'?world.local:!world.local)));document.querySelector('#world-results').innerHTML=window.NexusScreens.create(state,queries,filters,serverId).worldResults(worlds,false);document.querySelector('#clear-search').hidden=!query;}});
  document.querySelector('.navigation-toggle').onclick=()=>{const collapsed=app.classList.toggle('collapsed');const button=document.querySelector('.navigation-toggle');button.setAttribute('aria-expanded',String(!collapsed));button.setAttribute('aria-label',collapsed?'Развернуть навигацию':'Свернуть навигацию');button.title=button.getAttribute('aria-label');};
  document.querySelector('#history-back').disabled=true;
  document.querySelector('#history-back').onclick=()=>{const previous=trail.pop();if(previous)navigate(previous.route,previous.id,false);};
  window.NexusNativeLibrary={enter(value){if(value){nativeRoute=value;route=value;serverId='';}app.classList.add('desktop-native-library');navSync();},leave(){app.classList.remove('desktop-native-library');},geometry(){const workspace=document.querySelector('.workspace').getBoundingClientRect(),bar=document.querySelector('.topbar').getBoundingClientRect();return{x:workspace.left,y:bar.bottom,width:workspace.width,height:Math.max(0,innerHeight-bar.bottom),reducedMotion:matchMedia('(prefers-reduced-motion:reduce)').matches||app.classList.contains('profile-low-motion')};}};
  window.NexusUI=Object.freeze({navigate,notify,setState(value){state=value;document.querySelector('#game-stop').hidden=!value.gameRunning;app.classList.toggle('profile-low-motion',!!value.reducedMotion);document.querySelector('#account-name').textContent=value.profile.nickname||value.profile.pendingNickname||'Гость NEXUS';document.querySelector('#account-caption').textContent=value.profile.username?'@'+value.profile.username:value.profile.nickname?'Мой профиль':value.profile.pendingNickname?(value.profile.demo?'Демо-профиль · offline':'Подключите аккаунт'):'Войти в свой мир';const pinned=value.worlds.filter(world=>world.pinned);const section=document.querySelector('#pinned-worlds');section.innerHTML=pinned.map(world=>`<button data-route="server" data-id="${eattr(world.id)}" title="${eattr(world.name)}"><span class="world-mark" aria-hidden="true">${esc(world.name.slice(0,2))}</span><span class="rail-label">${esc(world.name)}</span></button>`).join('');section.previousElementSibling.hidden=!pinned.length;render();}});
  document.addEventListener('contextmenu',event=>event.preventDefault());
})();
