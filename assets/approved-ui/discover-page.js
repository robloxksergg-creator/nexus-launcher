/* Discovery and public server presentation. No account identity is trusted in JS. */
(() => {
  // Public projects remain read-only until the native service supplies verified
  // ownership. Local private drafts are editable, but never confer server roles.
  const access=Object.freeze({
    canEdit:()=>packLibrary.some(entry=>entry.id===activeProject),
    role:()=>packLibrary.some(entry=>entry.id===activeProject)?'local-draft':'viewer'
  });
  Object.defineProperty(window,'NexusProjectAccess',{value:access,writable:false,configurable:false});
  const home=document.createElement('section');home.className='discover-home';home.id='discover-home';
  document.querySelector('.content').append(home);
  const eyebrow=document.createElement('p');eyebrow.className='eyebrow';eyebrow.textContent='NEXUS / ОТКРОЙ СВОЙ МИР';
  const heading=document.createElement('h1');heading.textContent='Каждый мир — новая история.';
  const intro=document.createElement('p');intro.className='discover-intro';intro.textContent='Постройки, технологии и исследование. Выбирай атмосферу — находи серверы в каталоге.';
  home.append(eyebrow,heading,intro);
  const scenes=[
    {title:'Исследуй свой мир',description:'Minecraft · сцена, предоставленная автором',image:'/minecraft-meadow.png',query:''},
    {title:'Технологии и экспедиции',description:'Постройка Minecraft · Gearmorph',image:'/gearmorph-official.png',query:'Gearmorph'},
    {title:'Истории пустыни',description:'Minecraft · сцена, предоставленная автором',image:'/minecraft-desert.png',query:''},
    {title:'Городские приключения',description:'Minecraft · сцена, предоставленная автором',image:'/minecraft-city.png',query:''},
    {title:'На вершине мира',description:'Minecraft · сцена, предоставленная автором',image:'/minecraft-mountain.png',query:''}
  ];
  const stage=document.createElement('div');stage.className='discover-stage';
  const feature=document.createElement('article');feature.className='discover-feature';
  const picture=document.createElement('img');picture.alt='';
  const caption=document.createElement('div');caption.className='discover-caption';
  const title=document.createElement('h2'),description=document.createElement('p');
  const find=worldButton('Найти серверы',()=>openCatalogScene(selected));
  caption.append(title,description,find);feature.append(picture,caption);
  const playlist=document.createElement('div');playlist.className='discover-playlist';playlist.setAttribute('aria-label','Выбрать игровой мир');
  const strip=document.createElement('div');strip.className='discover-scenes';strip.setAttribute('aria-label','Подборки миров');
  let selected=0;
  function choose(index){selected=index;picture.src=scenes[index].image;title.textContent=scenes[index].title;description.textContent=scenes[index].description;playlist.querySelectorAll('button').forEach((b,i)=>b.setAttribute('aria-pressed',String(i===index)));}
  function sceneButton(scene,index,select){
    const button=document.createElement('button');button.className='discover-scene';
    const image=document.createElement('img');image.src=scene.image;image.alt='';
    const label=document.createElement('span');label.textContent=scene.title;
    button.append(image,label);button.onclick=()=>select?choose(index):openCatalogScene(index);return button;
  }
  scenes.forEach((scene,i)=>{playlist.append(sceneButton(scene,i,true));strip.append(sceneButton(scene,i,false));});
  stage.append(feature,playlist);home.append(stage,strip);choose(0);
  function hideOther(){worldsSpace.hidden=true;profileSpace.hidden=true;settingsSpace.hidden=true;packTutorial.hidden=true;document.querySelector('#other').hidden=true;}
  function showHome(push=true){
    hideOther();overview.hidden=true;home.hidden=false;app.classList.remove('pack-private','fixed-page');
    document.querySelectorAll('.nav button').forEach(b=>b.classList.toggle('active',b.dataset.view==='overview'));
    document.title='NEXUS · Обзор';if(push)history.pushState({nexusView:'discover-home'},'','#overview');window.scrollTo(0,0);
  }
  function openCatalogScene(index){home.hidden=true;serverSearch=scenes[index].query;worldView='discover';showWorldsSpace();}
  function openServer(push=true){
    home.hidden=true;hideOther();activateProject('gearmorph');overview.hidden=false;applyPageStructure(backgroundSaved);
    document.querySelector('#overview .heading h1').textContent='Gearmorph';
    document.querySelectorAll('.nav button').forEach(b=>b.classList.toggle('active',b.dataset.view==='catalog'));
    document.title='NEXUS · Gearmorph';if(push)history.pushState({nexusView:'server-page'},'','#server-gearmorph');window.scrollTo(0,0);
  }
  const originalServerPreview=showServerExample;
  showServerExample=server=>server.id==='gearmorph-demo'?openServer():originalServerPreview(server);
  // Existing navigation owns all other flows. Hide discovery before those handlers.
  document.querySelectorAll('[data-view]').forEach(button=>button.addEventListener('click',()=>{home.hidden=true;},true));
  document.querySelector('.nav [data-view=overview]').onclick=()=>showHome();
  document.querySelector('.sidebar .server').onclick=()=>openServer();
  const originalPacks=showPacks;showPacks=()=>{home.hidden=true;originalPacks();};
  const originalPackPage=openPackPage;openPackPage=entry=>{home.hidden=true;originalPackPage(entry);};
  const originalWorlds=showWorldsSpace;showWorldsSpace=()=>{home.hidden=true;originalWorlds();
    document.title=worldView==='discover'?'NEXUS · Каталог серверов':'NEXUS · Мои миры';
    if(worldView==='discover'&&!restoringNavigation&&history.state?.nexusView!=='server-catalog')history.pushState({nexusView:'server-catalog'},'','#catalog');
    const search=worldsSpace.querySelector('input[type=search]');
    if(search){const clear=worldButton('Очистить поиск',()=>{search.value='';search.dispatchEvent(new Event('input'));search.focus();});clear.hidden=!search.value;search.addEventListener('input',()=>clear.hidden=!search.value);search.after(clear);}
  };
  const originalProfile=showProfileSpace;showProfileSpace=tab=>{home.hidden=true;originalProfile(tab);};
  const originalSettings=openSettingsWorkspace;openSettingsWorkspace=()=>{home.hidden=true;originalSettings();};
  const ownerDialog=document.createElement('dialog');ownerDialog.className='server-owner-dialog';ownerDialog.setAttribute('aria-labelledby','server-owner-title');document.body.append(ownerDialog);
  const ownerTitle=document.createElement('h2');ownerTitle.id='server-owner-title';ownerTitle.textContent='Изменить профиль проекта';
  const ownerNote=document.createElement('p');ownerNote.textContent='Настройки локального черновика. Права на опубликованный сервер подтверждаются только сервисом NEXUS.';
  const actions=document.createElement('div');actions.className='block-actions';
  actions.append(worldButton('Оформление и колонка',()=>{ownerDialog.close();openCanvasStudio();}),worldButton('Макет страницы',()=>{ownerDialog.close();document.querySelector('#server-layout-settings').click();}),worldButton('Закрыть',()=>ownerDialog.close()));
  ownerDialog.append(ownerTitle,ownerNote,actions);
  editButton.onclick=()=>{if(access.canEdit())ownerDialog.showModal();};
  ownerDialog.addEventListener('close',()=>editButton.focus());
  const originalStudio=openCanvasStudio;openCanvasStudio=()=>{if(access.canEdit())originalStudio();else info('Изменять страницу может только подтверждённый создатель проекта.');};
  const originalStructure=applyPageStructure;
  applyPageStructure=settings=>{originalStructure(settings);editButton.hidden=!access.canEdit();editColumnShortcut.remove();editSectionsShortcut.remove();
    // Tabs and lower page sections share the same center background.
    const center=document.querySelector('.server-central-zone');
    serverMain.querySelectorAll(':scope > .layout-level').forEach(level=>center.append(level));
  };
  // Replace prototype Back handling only for the new route group.
  window.addEventListener('popstate',event=>{
    if(!['discover-home','server-catalog','server-page'].includes(event.state?.nexusView))return;
    event.stopImmediatePropagation();
    if(!studio.hidden)closeCanvasStudio(false);
    if(!catalogModal.hidden)closeModal(catalogModal);
    restoringNavigation=true;
    try{
      if(event.state.nexusView==='server-page')openServer(false);
      else if(event.state.nexusView==='server-catalog'){home.hidden=true;worldView='discover';showWorldsSpace();}
      else showHome(false);
    }finally{restoringNavigation=false;}
  },true);
  window.NexusDiscovery=Object.freeze({openServer,showHome});
  applyPageStructure(backgroundSaved);showHome(false);history.replaceState({nexusView:'discover-home'},'','#overview');
})();
