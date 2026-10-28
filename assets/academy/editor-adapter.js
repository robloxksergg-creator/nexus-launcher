/* One semantic adapter around the existing Studio renderer. No lesson rules here. */
(() => {
  'use strict';
  const emit=(type,data={})=>console.info('NEXUS_CREATOR_EVENT:'+JSON.stringify({type,...data}));
  const clone=value=>JSON.parse(JSON.stringify(value));
  let previous={components:[],selected:''}, loading=false, model=null, highlighted=null;
  const snapshot=()=>({components:clone(studioDraft),selected:selectedID||''});
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const command=(action,data={})=>emit('learning.'+action,data);
  const savedRender=renderStudio;
  renderStudio=()=>{
    savedRender();
    annotate();
    if(loading)return;
    const current=snapshot(), old=new Map(previous.components.map(item=>[item.id,item]));
    for(const item of current.components){
      const before=old.get(item.id), data={componentId:item.id,componentType:item.type,snapshot:current};
      if(!before){emit('component.created',data);continue;}
      if(before.x!==item.x||before.y!==item.y)emit('component.moved',data);
      if(before.w!==item.w||before.h!==item.h)emit('component.resized',data);
      if(before.text!==item.text)emit('text.updated',data);
      if(before.group!==item.group)emit(item.group?'component.grouped':'component.ungrouped',data);
      if(before.fontFamily!==item.fontFamily)emit('font.changed',data);
      if(before.src!==item.src)emit('asset.added',data);
      if(before.align!==item.align||before.shape!==item.shape||before.textColor!==item.textColor)emit('style.updated',data);
    }
    for(const item of previous.components)if(!current.components.some(x=>x.id===item.id))emit('component.deleted',{componentId:item.id,snapshot:current});
    if(previous.components.map(x=>x.id).join('|')!==current.components.map(x=>x.id).join('|')&&previous.components.length===current.components.length)emit('layer.reordered',{snapshot:current});
    if(previous.selected!==current.selected)emit('component.selected',{componentId:current.selected,snapshot:current});
    // Generic commit covers all properties, including names/actions without dedicated validators.
    if(JSON.stringify(previous)!==JSON.stringify(current))emit('document.changed',{snapshot:current});
    previous=current;
    highlight();
  };
  const propertyNames={'Название слоя':'name','Текст':'text','Выравнивание':'align','Форма панели':'shape','Цвет текста':'textColor','Каталог дизайнерских шрифтов':'fontFamily','Действие':'action'};
  const savedField=inspectorField;
  inspectorField=(label,control)=>{control.dataset.creatorProperty=propertyNames[label]||label;return savedField(label,control);};
  function annotate(){
    studio.querySelectorAll('.position-fields input').forEach((input,index)=>input.dataset.creatorProperty=['x','y','w','h'][index]);
    studio.querySelectorAll('#studio-layers>button').forEach((button,index)=>button.dataset.creatorLayer=[...studioDraft].reverse()[index]?.id||'');
  }
  let lastReveal='';
  const targets={
    canvas:()=>board,
    'toolbar-action':target=>target.id==='add-component'?studio.querySelector('#create-item'):target.id==='layers'?studio.querySelector('[data-category=layers]'):target.id==='save'?studio.querySelector('#studio-save'):null,
    'inspector-property':target=>studio.querySelector(`[data-creator-property="${CSS.escape(target.property)}"]`),
    component:target=>{const item=studioDraft.find(x=>x.id===selectedID&&(!target.componentType||x.type===target.componentType))||studioDraft.find(x=>x.type===target.componentType);return item?board.querySelector(`[data-item="${CSS.escape(item.id)}"]`):null;},
    layer:target=>studio.querySelector(`[data-creator-layer="${CSS.escape(target.id)}"]`)
  };
  function resolve(target){return targets[target?.type]?.(target)||null;}
  function highlight(){
    highlighted?.classList.remove('academy-highlight');highlighted=null;
    if(!model?.target||!['ACTIVE','WAITING_FOR_ACTION','SHOWING_HINT','INTRO'].includes(model.state))return;
    const element=resolve(model.target);
    if(element){let parent=element.parentElement;while(parent&&parent!==studio){if(parent.tagName==='DETAILS')parent.open=true;parent=parent.parentElement;}}
    if(element&&element.getClientRects().length){element.classList.add('academy-highlight');highlighted=element;const key=JSON.stringify(model.target)+model.index;if(key!==lastReveal){element.scrollIntoView({block:'nearest',inline:'nearest',behavior:'instant'});lastReveal=key;}}
    const warning=card.querySelector('.target-warning');if(warning){warning.hidden=!!highlighted;warning.textContent=model.ui.unavailable;}
  }
  window.addEventListener('resize',()=>{lastReveal='';highlight();});
  const savedFilter=filterTools;
  filterTools=()=>{savedFilter();highlight();};
  board.addEventListener('click',event=>{if(event.target===board)emit('canvas.selected',{snapshot:snapshot()});});
  const card=document.createElement('section');card.className='academy-card';card.setAttribute('aria-label','Academy');card.hidden=true;
  const pill=document.createElement('button');pill.className='academy-minimized';pill.hidden=true;
  const panel=document.createElement('aside');panel.className='academy-panel';panel.hidden=true;panel.setAttribute('aria-label','NEXUS Creator Academy');
  const help=document.createElement('section');help.className='academy-help';help.hidden=true;help.setAttribute('role','dialog');help.tabIndex=-1;
  const welcome=document.createElement('section');welcome.className='academy-welcome';welcome.hidden=true;welcome.setAttribute('role','dialog');welcome.tabIndex=-1;
  studio.append(card,pill,panel,help,welcome);
  const button=(action,label,disabled=false)=>`<button data-learning="${action}" aria-label="${esc(model?.ui[action]||label)}" ${disabled?'disabled':''}>${esc(label)}</button>`;
  function showLearning(){
    if(!model)return;
    const u=model.ui, state=model.state;
    const activeAction=card.contains(document.activeElement)?document.activeElement.dataset.learning:null;
    studio.classList.toggle('academy-active',['ACTIVE','WAITING_FOR_ACTION','SHOWING_HINT','INTRO'].includes(state));
    document.documentElement.classList.toggle('academy-reduced-motion',model.settings.reduced_motion);
    pill.hidden=!['MINIMIZED','PAUSED'].includes(state);
    pill.textContent=`Academy · ${model.index||0}/${model.count||0} · ${u.restore}`;
    card.hidden=state==='IDLE'||state==='MINIMIZED'||state==='PAUSED';
    if(state==='EXITING')card.innerHTML=`<h3>${esc(u.leave)}</h3><div class="academy-actions">${button('resume',u.resume)}${button('exit',u.exit)}</div>`;
    else if(state==='COMPLETED')card.innerHTML=`<p class="academy-eyebrow">ACADEMY</p><h3>${esc(model.completed?u.complete:u.skipped)}</h3><div class="academy-actions">${button('academy',u.academy)}${button('restart',u.restart)}${button('pause',u.editor)}</div>`;
    else if(!card.hidden)card.innerHTML=`<div class="academy-card-top"><span class="academy-eyebrow">ACADEMY · ${model.index}/${model.count}</span>${button('minimize','−')}</div><h3>${esc(model.title)}</h3><p>${esc(model.instruction)}</p><p class="target-warning" hidden></p><p class="academy-feedback" role="status" aria-live="polite">${esc(model.validated?model.message:(model.hint||model.message||''))}</p><div class="academy-actions">${button('hint',u.hint,!model.settings.hints)}${button('help',u.help)}${button('pause',u.pause)}${button('exit-request',u.exit)}</div><div class="academy-actions">${button('back',u.back,model.index===1)}${button('skip',u.skip,!model.allowSkip)}${button('next',u.next,!model.validated)}</div>`;
    highlight();
    if(activeAction)card.querySelector(`[data-learning="${CSS.escape(activeAction)}"]:not(:disabled)`)?.focus({preventScroll:true});
  }
  function renderAcademy(){
    const u=model.ui,s=model.settings;
    const query=panel.querySelector('input[type=search]')?.value||'';
    const expanded=!!panel.querySelector('details')?.open;
    panel.innerHTML=`<header><h2>${esc(u.academy)}</h2>${button('close-panel','×')}</header><input type="search" placeholder="${esc(u.search)}" aria-label="${esc(u.search)}"><div class="academy-lessons">${model.lessons.filter(x=>s.show_completed||!x.completed).map(x=>`<article data-search="${esc((x.title+' '+x.description).toLocaleLowerCase())}"><h3>${x.completed?'✓ ':''}${esc(x.title)}</h3><p>${esc(x.description)}</p><button data-learning="start" data-lesson="${esc(x.id)}">${esc(u.start)}</button></article>`).join('')}</div><button data-learning="help">${esc(u.help)} · ${esc(u.practice)}</button><details><summary>${esc(u.settings)}</summary><p>${esc(u.mode)}</p><div class="academy-actions">${['guided','assisted','advanced'].map(value=>`<button data-learning="mode" data-value="${value}" aria-pressed="${s.mode===value}">${esc(u[value])}</button>`).join('')}</div><div class="academy-actions">${['ru','en','de','ky'].map(value=>`<button data-learning="locale" data-value="${value}" aria-pressed="${s.locale===value}">${value.toUpperCase()}${['de','ky'].includes(value)?' · EN':''}</button>`).join('')}</div>${['tips','hints','auto_start','show_completed'].map(key=>`<button class="academy-toggle" data-learning="preference" data-name="${key}" data-value="${!s[key]}" aria-pressed="${s[key]}">${s[key]?'✓ ':''}${esc(u[key])}</button>`).join('')}${button('reset-request',u.reset)}${button('onboarding',u.onboarding)}</details>`;
    panel.querySelector('input').value=query;
    panel.querySelector('details').open=expanded;
    filterLessons(query);
  }
  function filterLessons(query){panel.querySelectorAll('article').forEach(row=>row.hidden=!row.dataset.search.includes(query.toLocaleLowerCase()));}
  panel.addEventListener('input',event=>{if(event.target.type==='search')filterLessons(event.target.value);});
  function closeTransient(){panel.hidden=help.hidden=welcome.hidden=true;}
  document.addEventListener('click',event=>{
    const element=event.target.closest('[data-learning]');if(!element)return;
    const action=element.dataset.learning;
    if(action==='close-panel'){panel.hidden=true;return;}
    if(action==='close-help'){help.hidden=true;return;}
    if(action==='reset-request'){help.hidden=false;help.innerHTML=`<h3>${esc(model.ui.reset)}?</h3><p>${esc(model.ui.practice)}</p>${button('reset',model.ui.reset)}${button('close-help',model.ui.back)}`;help.focus();return;}
    if(action==='start')closeTransient();
    if(action==='reset')help.hidden=true;
    command(action,{lesson:element.dataset.lesson,name:element.dataset.name,value:element.dataset.value==='true'?true:element.dataset.value==='false'?false:element.dataset.value});
  });
  document.addEventListener('keydown',event=>{
    if(event.key==='Escape'){
      if(!help.hidden){help.hidden=true;event.preventDefault();}
      else if(!welcome.hidden){command('welcome-choice',{value:'explore'});event.preventDefault();}
      else if(!panel.hidden){panel.hidden=true;event.preventDefault();}
      else if(!card.hidden){command('pause');event.preventDefault();}
    }
  });
  pill.onclick=()=>command('resume');
  const toolbar=studio.querySelector('.canvas-toolbar');
  toolbar.querySelector('strong').textContent='NEXUS Creator / Studio';
  const academy=document.createElement('button');academy.className='outline';academy.textContent='Academy';academy.onclick=()=>command('academy');toolbar.append(academy);
  const helpButton=document.createElement('button');helpButton.className='outline';helpButton.textContent='?';helpButton.setAttribute('aria-label','Справка о холсте');helpButton.onclick=()=>command('help');toolbar.append(helpButton);
  studio.querySelector('#studio-save').onclick=()=>{if(validStudio(studioDraft))emit('project.save_requested',{snapshot:snapshot()});else errorStudio('Проверь действия и ссылки панелей.');};
  studio.querySelector('#studio-cancel').onclick=()=>{help.hidden=false;renderCanvas(help,studioDraft,false);const close=document.createElement('button');close.textContent=model?.ui.editor||'Studio';close.dataset.learning='close-help';help.prepend(close);emit('preview.opened',{snapshot:snapshot()});};
  const baseTemplate=clone(studioSaved);
  window.NexusCreator=Object.freeze({
    load(document){loading=true;studioSaved=document?clone(document.components):[{id:'practice-background',name:'Учебный баннер',type:'png',src:'/gearmorph-official.png',x:0,y:0,w:100,h:45,action:'none',locked:true,group:''}];studioDraft=clone(studioSaved);studioCounter=Math.max(0,...studioDraft.map(x=>Number(x.id.replace('element',''))||0));selectedID=document?.selected||studioDraft.at(-1)?.id;multiSelection.clear();studio.hidden=false;studioEditing=true;app.inert=true;activeToolCategory='create';renderStudio();loading=false;previous=snapshot();emit('editor.ready',{snapshot:previous});},
    loadTemplate(){this.load({components:baseTemplate});emit('document.changed',{snapshot:snapshot()});},
    learning(value){model=value;studio.querySelector('#studio-save').textContent=model.ui.save;helpButton.setAttribute('aria-label',model.ui.help);studio.querySelector('#studio-cancel').textContent=model.ui.preview;showLearning();if(!panel.hidden)renderAcademy();},
    academy(){if(!model)return;renderAcademy();panel.hidden=false;panel.querySelector('input').focus();},
    onboarding(){if(!model)return;const u=model.ui;welcome.innerHTML=`<p class="academy-eyebrow">NEXUS CREATOR</p><h2>${esc(u.welcome)}</h2>${['guided','template','explore','advanced'].map(value=>`<button data-learning="welcome-choice" data-value="${value}">${esc(u[value])}</button>`).join('')}`;welcome.hidden=false;welcome.focus();},
    closeWelcome(){welcome.hidden=true;},
    help(text){help.innerHTML=`<h3>${esc(model.ui.help)}</h3><p>${esc(text)}</p>${button('close-help',model.ui.back)}`;help.hidden=false;help.focus();},
    saved(){studio.querySelector('#studio-status').textContent=model?.ui.saved||'Saved';},
    resolve,
    snapshot,
  });
})();
