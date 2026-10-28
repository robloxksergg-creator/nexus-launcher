/* Shared presentation primitives; no IO or application mutations. */
(() => {
  const paths={home:'M3 10 12 3l9 7v10H3z M9 20v-7h6v7',build:'m12 3 9 5v9l-9 5-9-5V8z M3 8l9 5 9-5 M12 13v9',world:'M3 6h18v14H3z M3 6l4-3h10l4 3 M3 14l5-5 5 5 3-3 5 5',compass:'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20 M16 8l-3 5-5 3 3-5z',plus:'M12 5v14 M5 12h14',download:'M12 3v12 m-5-5 5 5 5-5 M4 16v5h16v-5',settings:'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M12 2v3 M12 19v3 M2 12h3 M19 12h3 M5 5l2 2 M17 17l2 2 M5 19l2-2 M17 7l2-2',rail:'M3 4h18v16H3z M8 4v16',back:'m14 5-7 7 7 7',expand:'M8 3H3v5 M16 3h5v5 M21 16v5h-5 M8 21H3v-5',play:'m8 4 12 8-12 8z',arrow:'M4 12h16 m-6-6 6 6-6 6',close:'m6 6 12 12 M6 18 18 6',star:'m12 3 3 6 6 1-4 5 1 6-6-3-6 3 1-6-4-5 6-1z'};
  const icon=name=>`<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[name]||paths.world}"/></svg>`;
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const eattr=value=>esc(value);
  window.NexusComponents=Object.freeze({icon,esc,eattr,create(state){
  function commandButton(label,name,id='',primary=false,extra='') {
    const glyph=primary?(name.startsWith('play-')?icon('play'):name==='create'?icon('plus'):''):'';
    return `<button class="button ${primary?'primary':''}" data-action="${name}" ${id?`data-id="${eattr(id)}"`:''} ${extra}>${glyph}${esc(label)}</button>`;
  }
  function routeButton(label,target,extra='') {return `<button class="text-link" data-route="${target}" ${extra}>${esc(label)}${icon('arrow')}</button>`;}
  function fallback(seed) {
    let hash=0;for(const char of String(seed))hash=(hash*31+char.charCodeAt(0))>>>0;
    const hue=195+hash%35, paths=[];
    for(let layer=0;layer<4;layer++){
      let d='M0 400';for(let i=0;i<21;i++){const y=Math.round(400*(.46+layer*.10+Math.sin(i*.55+(hash%255)/20+layer)*.09));d+=` L${i*40} ${y} L${i*40+40} ${y}`;}d+=' L800 400Z';
      paths.push(`<path d="${d}" fill="hsl(${hue+layer*3},35%,${22-layer*4}%)"/>`);
    }
    const svg=`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 400"><defs><linearGradient id="sky"><stop stop-color="hsl(${hue},40%,26%)"/><stop offset="1" stop-color="#0a0e14"/></linearGradient></defs><path fill="url(#sky)" d="M0 0h800v400H0z"/><circle cx="584" cy="100" r="36" fill="#c3daed" opacity=".45"/>${paths.join('')}</svg>`;
    return 'data:image/svg+xml;charset=utf-8,'+encodeURIComponent(svg);
  }
  function image(src,cls='hero-art') { return `<img class="${cls}" src="${eattr(src)}" alt="" loading="${cls==='hero-art'?'eager':'lazy'}" draggable="false">`; }
  function date(value) {if(!value)return 'Ещё не запускалась';const d=new Date(value);return Number.isNaN(d.valueOf())?'Дата недоступна':d.toLocaleDateString('ru-RU',{day:'numeric',month:'short',year:'numeric'});}
  const statuses={online:'В сети',unknown:'Статус не получен',unavailable:'Связь недоступна',local:'Локальный мир',development:'В разработке',maintenance:'Обслуживание',closed:'Доступ закрыт',offline:'Не в сети'};
  function status(world) {return `<span class="status ${world.status==='online'?'online':['closed','maintenance','development'].includes(world.status)?'warning':''}"><span class="status-dot"></span>${esc(statuses[world.status]||'Статус недоступен')}${world.players?` · ${esc(world.players)}`:''}</span>`;}
  function playLabel(world) {
    if(!world.allowed)return 'Недоступно';
    if(!state.profile.nickname)return 'Войти и играть';
    const delivery=String(world.delivery).toLowerCase();
    const labels={ready:'Играть',running:'Игра запущена',failed:'Повторить',repair_required:'Восстановить',update_available:'Обновить',not_installed:'Установить',checking:'Проверка…',preparing:'Подготовка…',downloading:'Загрузка…',verifying:'Проверка…',applying:'Установка…',finalizing:'Завершение…'};
    return labels[delivery]||'Установить';
  }
  const loaderName=value=>({neoforge:'NeoForge',forge:'Forge',fabric:'Fabric',vanilla:'Vanilla',quilt:'Quilt'}[value]||value);
  function playButton(world) {
    const busy=/checking|preparing|downloading|verifying|applying|finalizing|running/i.test(world.delivery);
    return commandButton(playLabel(world),'play-server',world.id,true,(!world.allowed||busy||state.gameRunning)?'disabled':'');
  }
  function empty(title,copy,label,target,{error=false,actionName='',art='minecraft-meadow.png'}={}) {
    return `<section class="empty ${error?'error':''}">${image('/'+art,'empty-art')}<div><h3>${esc(title)}</h3><p>${esc(copy)}</p>${actionName?commandButton(label,actionName,'',true):routeButton(label,target)}</div></section>`;
  }
  function worldCard(world) {
    return `<article class="world-card">${image(world.artwork,'card-art')}<div class="card-top">${status(world)}</div><button class="card-open" data-route="server" data-id="${eattr(world.id)}" aria-label="Открыть ${eattr(world.name)}"></button><div class="card-copy"><span class="eyebrow">${esc(world.category)}</span><h3>${esc(world.name)}</h3><p class="meta">${esc(world.version)} · ${esc(loaderName(world.loader))}</p></div><div class="card-actions">${playButton(world)}<button class="icon-button" data-action="save-server" data-id="${eattr(world.id)}" aria-label="${world.saved?'Убрать из':'Сохранить в'} мои миры: ${eattr(world.name)}" title="${world.saved?'Убрать из моих миров':'Сохранить мир'}" aria-pressed="${world.saved}">${icon('star')}</button></div></article>`;
  }
  function buildRow(build) {return `<article class="build-row">${image(fallback(build.id),'build-thumb')}<div class="build-row-copy"><h3>${esc(build.name)}</h3><p class="meta">Minecraft ${esc(build.version)} · ${esc(loaderName(build.loader))} · ${build.mods} модов</p><p class="meta">${build.lastPlayed?'Последний запуск: '+date(build.lastPlayed):'Ещё не запускалась'}</p></div>${commandButton('Открыть','open-build',build.id)}${commandButton('Играть','play-build',build.id,true)}</article>`;}
  function hero(world,eyebrow='МИР NEXUS',detail=false) {
    return `<section class="hero" style="--world-accent:${eattr(world.accent)}">${image(world.artwork)}<div class="hero-topline">${status(world)}</div><div class="hero-content"><p class="eyebrow">${eyebrow}</p><h2>${esc(world.name)}</h2><p class="hero-description">${esc(world.description)}</p><div class="hero-actions">${playButton(world)}${detail?commandButton(world.saved?'Мир сохранён':'Сохранить мир','save-server',world.id):`<button class="button ghost" data-route="server" data-id="${eattr(world.id)}">Об этом мире</button>`}<span class="meta">Minecraft ${esc(world.version)} · ${esc(loaderName(world.loader))}</span></div></div></section>`;
  }

return {commandButton,routeButton,fallback,image,date,status,statuses,playLabel,playButton,empty,worldCard,buildRow,hero,loaderName};
}});
})();
