/* Local artwork studies and review wishes; never placement authority. */
(() => {
  'use strict';
  const formats={home_hero:['Обзор · обложка','Широкое окно первого экрана'],home_card:['Обзор · карточка','Подборка миров на главной'],catalog_card:['Каталог','Карточка среди других серверов'],top_banner:['Топ · баннер','Только после отдельного одобрения NEXUS']};
  const copy=v=>JSON.parse(JSON.stringify(v));
  const defaults=()=>({version:1,title:'Мой сервер',summary:'Мир, который хочется исследовать.',requested:['catalog_card'],formats:Object.fromEntries(Object.keys(formats).map(k=>[k,{imageId:'',x:50,y:50,zoom:100}]))});
  let state=defaults(),active='home_hero';
  const node=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text)n.textContent=text;return n;};
  const root=node('section','placement-workspace');root.hidden=true;root.setAttribute('aria-label','Предпросмотр размещений сервера');
  const head=node('header','placement-heading');const heading=node('div');heading.append(node('small','','NEXUS / PRESENTATION STUDIO'),node('h2','','Твой мир. В разных окнах.'),node('p','','Настрой обложку для каждого формата. Размещения — пожелания для проверки, а не назначение в топ.'));head.append(heading);
  const close=node('button','','Вернуться на холст');close.type='button';head.append(close);root.append(head);
  const body=node('div','placement-body'), stage=node('div','placement-stage'),aside=node('aside','placement-inspector');body.append(stage,aside);root.append(body);
  const tabs=node('div','placement-tabs');tabs.setAttribute('role','group');tabs.setAttribute('aria-label','Формат предпросмотра');
  Object.entries(formats).forEach(([key,[label]])=>{const b=node('button','',label);b.type='button';b.dataset.format=key;b.onclick=()=>{active=key;refresh();};tabs.append(b);});stage.append(tabs);
  const viewport=node('div','placement-viewport'), frame=node('article','placement-frame'),image=node('img','placement-image');image.alt='';image.draggable=false;
  const overlay=node('div','placement-caption'),badge=node('span','placement-badge','ПРЕДПРОСМОТР'),title=node('h3'),summary=node('p'),cta=node('span','placement-cta','Подробнее о мире →');overlay.append(badge,title,summary,cta);frame.append(image,overlay);viewport.append(frame);stage.append(viewport);
  const note=node('p','placement-note');stage.append(note);
  image.onerror=()=>{image.hidden=true;note.textContent='Изображение недоступно. Локальные загрузки прошлой сессии нужно добавить на холст заново.';};
  const status=node('p','placement-save-state','Изменения сохраняются локально в документе Academy.');status.setAttribute('role','status');
  const field=(label,element)=>{const wrap=node('label','placement-field',label);wrap.append(element);aside.append(wrap);return element;};
  const name=field('Название сервера',node('input'));name.maxLength=80;
  const description=field('Короткое описание',node('textarea'));description.maxLength=220;description.rows=3;
  const source=field('Изображение из слоёв холста',node('select'));source.setAttribute('aria-label','Изображение обложки');
  const ranges={};for(const [key,label,min,max] of [['x','Фокус по горизонтали',0,100],['y','Фокус по вертикали',0,100],['zoom','Масштаб',100,160]]){const wrap=node('label','placement-field',label),out=node('output'),input=node('input');input.type='range';input.min=min;input.max=max;input.step=1;input.dataset.crop=key;input.setAttribute('aria-label',label);wrap.append(out,input);aside.append(wrap);ranges[key]={input,out};input.oninput=()=>{state.formats[active][key]=Number(input.value);paint();};input.onchange=commit;}
  const reset=node('button','','Сбросить кадрирование');reset.type='button';reset.onclick=()=>{Object.assign(state.formats[active],{x:50,y:50,zoom:100});refresh();commit();};aside.append(reset);
  const wishes=node('fieldset','placement-wishes');wishes.append(node('legend','','Где я хочу представить сервер'));
  for(const [key,[label]] of Object.entries(formats)){const wrap=node('label'),input=node('input');input.type='checkbox';input.value=key;input.onchange=()=>{state.requested=[...wishes.querySelectorAll('input:checked')].map(n=>n.value);commit();};wrap.append(input,document.createTextNode(label));wishes.append(wrap);}aside.append(wishes,node('p','placement-safety','Топ и главная требуют проверки команды. Выбор не меняет доступ, рейтинг или статус публикации.'));
  const save=node('button','placement-save','Сохранить настройки');save.type='button';save.onclick=()=>document.querySelector('#studio-save').click();aside.append(save,status);
  name.oninput=()=>{state.title=name.value;paint();};name.onchange=commit;description.oninput=()=>{state.summary=description.value;paint();};description.onchange=commit;source.onchange=()=>{state.formats[active].imageId=source.value;paint();commit();};
  function commit(){status.textContent='Сохранено локально · не отправлено на публикацию';console.info('NEXUS_CREATOR_EVENT:'+JSON.stringify({type:'placements.changed',snapshot:NexusCreator.snapshot()}));}
  function paint(){const crop=state.formats[active],item=studioDraft.find(i=>i.id===crop.imageId&&i.type==='png');const src=item?.src||'';const safe=src==='/gearmorph-official.png'||src.startsWith('blob:'+location.origin+'/');image.hidden=!safe;if(safe)image.src=src;else image.removeAttribute('src');image.style.objectPosition=crop.x+'% '+crop.y+'%';image.style.transform='scale('+crop.zoom/100+')';image.style.transformOrigin=crop.x+'% '+crop.y+'%';title.textContent=state.title||'Название сервера';summary.textContent=state.summary;frame.dataset.format=active;note.textContent=formats[active][1]+(safe?' · Демонстрация оформления, не опубликованная карточка.':' · Добавь PNG на холст и выбери его здесь.');for(const [key,{input,out}] of Object.entries(ranges)){input.value=crop[key];out.textContent=crop[key]+'%';}tabs.querySelectorAll('button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.format===active)));}
  function refresh(){name.value=state.title;description.value=state.summary;source.replaceChildren();const empty=node('option','','Без изображения');empty.value='';source.append(empty);studioDraft.filter(i=>i.type==='png').forEach(i=>{const opt=node('option','',i.name||i.id);opt.value=i.id;source.append(opt);});source.value=state.formats[active].imageId;if(source.selectedIndex<0){const opt=node('option','','Источник недоступен · выбери другой');opt.value=state.formats[active].imageId;source.append(opt);source.value=opt.value;}wishes.querySelectorAll('input').forEach(i=>i.checked=state.requested.includes(i.value));paint();}
  const tab=node('button','','Размещения');tab.type='button';tab.setAttribute('aria-pressed','false');document.querySelector('.creator-workspace-modes').append(tab);
  function open(){refresh();root.hidden=false;studio.classList.add('placement-open');tab.setAttribute('aria-pressed','true');close.focus();}
  function hide(){root.hidden=true;studio.classList.remove('placement-open');tab.setAttribute('aria-pressed','false');}
  tab.onclick=()=>root.hidden?open():hide();close.onclick=()=>{hide();tab.focus();};
  root.addEventListener('keydown',e=>{e.stopPropagation();if(e.key==='Escape'){hide();tab.focus();}});
  document.querySelector('.creator-workspace-modes').addEventListener('click',e=>{if(e.target.closest('button')!==tab)hide();});
  studio.append(root);
  window.NexusPlacementUI=Object.freeze({snapshot:()=>copy(state),load:value=>{state=value?copy(value):defaults();hide();},saved:()=>{status.textContent='Сохранено в документе Academy · публикации нет';},open});
})();
