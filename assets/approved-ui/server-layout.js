/* Shared server-page zones. No network, advertising scripts or service mutations. */
(() => {
  const defaults = {authors:true,ads:true,info:true,sideColor:'#10151e',mainColor:'#10151e',image:null,opacity:30,width:180,authorText:'Авторы пока не подключены.',adText:'Место для рекламного материала. Сейчас показан только тестовый блок.'};
  const root = document.querySelector('.server-presentation');
  const zone = document.createElement('div');
  zone.className = 'server-page-zones';
  const authors = document.createElement('aside');
  authors.className = 'server-zone-card server-author-zone';
  authors.setAttribute('aria-label','Авторы сервера');
  const ads = document.createElement('aside');
  ads.className = 'server-zone-card server-ad-zone';
  ads.setAttribute('aria-label','Рекламный блок');
  const center = document.createElement('div');
  center.className = 'server-central-zone';
  const board = document.querySelector('.canvas-preview');
  board.before(zone);
  center.append(board);
  zone.append(center,ads);
  const action = document.createElement('button');
  action.className = 'outline';
  action.id = 'server-layout-settings';
  action.textContent = 'Настроить макет';
  // All editing is reached through the owner-only profile editor.
  document.querySelector('.content').append(action);
  action.hidden=true;
  function value(){return {...defaults,authorText:backgroundSaved.infoText?.team||defaults.authorText,...backgroundSaved.desktopLayout};}
  function card(node,title,text){
    node.replaceChildren();
    const h=document.createElement('h3');h.textContent=title;
    const p=document.createElement('p');p.textContent=text;
    node.append(h,p);
  }
  function apply(){
    const state=value();
    card(authors,'Авторы',state.authorText);
    if(backgroundSaved.infoText?.showCreator){
      const creator=document.createElement('p');
      creator.textContent='Создатель: '+(backgroundSaved.infoText.creator||'Не указан');
      authors.append(creator);
    }
    card(ads,'Реклама · предпросмотр',state.adText);
    authors.hidden=!state.authors;ads.hidden=!state.ads;
    zone.classList.toggle('without-authors',!state.authors);
    zone.classList.toggle('without-ads',!state.ads);
    zone.style.setProperty('--zone-width',state.width+'px');
    zone.style.setProperty('--zone-bg',state.mainColor);
    zone.style.setProperty('--zone-image',state.image?'url("'+state.image+'")':'none');
    zone.style.setProperty('--zone-opacity',state.opacity/100);
    const side=root.querySelector('.server-information');
    side.style.background=state.sideColor;
    side.querySelectorAll('h3').forEach(heading=>{
      if(['Авторы','Создатель'].includes(heading.textContent)){
        if(heading.nextElementSibling?.tagName==='P')heading.nextElementSibling.remove();
        heading.remove();
      }
    });
    side.append(authors);
    editColumnShortcut.remove();
    editSectionsShortcut.remove();
    action.hidden=true;
    // Information is a named default panel, not an arbitrary studio layer.
    const info=board.querySelector('[data-item="information"]');
    if(info)info.hidden=!state.info;
    window.NexusBannerMedia?.render(board,state.banner);
  }
  const previousStructure=applyPageStructure;
  applyPageStructure=settings=>{previousStructure(settings);apply();};
  const previousRender=renderCanvas;
  renderCanvas=(target,items,editing)=>{previousRender(target,items,editing);if(!editing&&target.closest('.canvas-preview'))apply();};

  const dialog=document.createElement('dialog');
  dialog.className='server-layout-dialog';
  dialog.setAttribute('aria-labelledby','server-layout-title');
  document.body.append(dialog);
  let draft=null,selectedURL=null,request=0,bannerSession=null,bannerCommitted=false;
  function disposeDraft(){request++;bannerSession?.dispose(bannerCommitted);bannerSession=null;if(selectedURL){URL.revokeObjectURL(selectedURL);selectedURL=null;}}
  function finishDialog(){disposeDraft();dialog.close();}
  function field(label,type,key,min,max){
    const row=document.createElement('label');row.className='server-layout-field';
    const span=document.createElement('span');span.textContent=label;
    const input=document.createElement(type==='textarea'?'textarea':'input');
    if(type!=='textarea')input.type=type;
    input.id='zone-setting-'+key;
    if(type==='checkbox')input.checked=draft[key];else input.value=draft[key];
    if(min!==undefined)input.min=min;if(max!==undefined)input.max=max;
    if(type==='textarea')input.maxLength=1200;
    input.oninput=()=>draft[key]=type==='checkbox'?input.checked:type==='range'?Number(input.value):input.value;
    row.append(span,input);return row;
  }
  function button(label,callback){const b=document.createElement('button');b.className='outline';b.textContent=label;b.onclick=callback;return b;}
  action.onclick=()=>{
    if(!window.NexusProjectAccess?.canEdit())return;
    disposeDraft();
    request++;draft=value();selectedURL=null;bannerCommitted=false;dialog.replaceChildren();
    const title=document.createElement('h2');title.id='server-layout-title';title.textContent='Макет страницы сервера';
    const note=document.createElement('p');note.textContent='Оформление этой страницы. В тестовой сборке сохраняется до закрытия. Размеры перестраиваются автоматически на узком экране.';
    dialog.append(title,note);
    const fields=document.createElement('div');fields.className='server-layout-fields';
    fields.append(field('Фон центральной страницы','color','mainColor'),field('Показывать авторов в колонке проекта','checkbox','authors'),field('Показывать рекламную зону справа','checkbox','ads'),field('Показывать нижнюю информацию','checkbox','info'),field('Ширина боковых зон · 140–240 px','range','width',140,240),field('Непрозрачность фонового изображения · 0–100%','range','opacity',0,100),field('Текст авторов','textarea','authorText'),field('Текст рекламного предпросмотра','textarea','adText'));
    dialog.append(fields);
    const picker=document.createElement('input');picker.type='file';picker.accept='image/png,image/jpeg,image/webp';picker.hidden=true;
    const status=document.createElement('p');status.setAttribute('role','status');
    status.textContent=draft.image?'Фоновое изображение выбрано.':'Без фонового изображения.';
    picker.onchange=async()=>{
      const generation=++request;
      const file=picker.files[0];if(!file)return;
      if(!['image/png','image/jpeg','image/webp'].includes(file.type)||file.size===0||file.size>20*1024*1024){status.textContent='Выберите PNG, JPEG или WebP до 20 МБ.';return;}
      try{
        const decoded=await createImageBitmap(file);decoded.close();
        if(!dialog.open||generation!==request)return;
        if(selectedURL)URL.revokeObjectURL(selectedURL);
        selectedURL=URL.createObjectURL(file);draft.image=selectedURL;
        status.textContent='Выбрано: '+file.name;
      }catch{status.textContent='Не удалось прочитать изображение.';}
    };
    const media=document.createElement('div');media.className='block-actions';
    media.append(button('Выбрать фон · до 20 МБ',()=>picker.click()),button('Убрать изображение',()=>{draft.image=null;status.textContent='Без фонового изображения.';}));
    const actions=document.createElement('div');actions.className='block-actions';
    actions.append(button('Отмена',finishDialog),button('Применить',()=>{if(!window.NexusProjectAccess?.canEdit()){finishDialog();return;}backgroundSaved.desktopLayout=structuredClone(draft);storeProject();if(selectedURL&&draft.image!==selectedURL)URL.revokeObjectURL(selectedURL);selectedURL=null;bannerCommitted=true;renderCanvas(previewBoard,studioSaved,false);apply();finishDialog();}));
    dialog.append(picker,media,status,actions);bannerSession=window.NexusBannerMedia?.attach(dialog,draft);dialog.showModal();
  };
  dialog.addEventListener('close',()=>{if(!dialog.open){disposeDraft();action.focus();}});
  dialog.addEventListener('cancel',event=>{event.preventDefault();finishDialog();});
  document.addEventListener('keydown',event=>{if(dialog.open&&event.key==='Escape'){event.preventDefault();event.stopImmediatePropagation();finishDialog();}},true);
  apply();
})();
