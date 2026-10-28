/* Studio presentation migration. Existing model, validation and mutations remain owners. */
(() => {
  'use strict';
  const make=(tag,cls,text)=>{const node=document.createElement(tag);node.className=cls||'';if(text)node.textContent=text;return node;};
  const button=(text,action)=>{const node=make('button','outline',text);node.type='button';node.onclick=action;return node;};
  const work=studio.querySelector('.canvas-work'), inspector=studio.querySelector('.canvas-properties');
  studio.classList.add('creator-workspace');
  studio.querySelector('.canvas-toolbar strong').textContent='NEXUS Creator · Учебная страница';
  studio.querySelector('.canvas-toolbar').prepend(button('← Studio',()=>console.info('NEXUS_CREATOR_EVENT:'+JSON.stringify({type:'editor.back_requested'}))));
  const rail=make('nav','creator-rail');rail.setAttribute('aria-label','Компоненты и страница');work.prepend(rail);
  const add=button('+ Добавить',()=>openPicker());rail.append(add);
  const create=studio.querySelector('#create-item');create.textContent='Текст';create.className='outline';rail.append(create);
  const originalCreate=create.onclick;
  create.onclick=()=>{studio.querySelector('#create-type').value='text';originalCreate();};
  rail.append(button('Изображение',()=>createComponent('image')),button('Кнопка',()=>createComponent('button')),button('Форма',()=>createComponent('shape')));
  const pageButton=button('Страница',()=>{selectedID='';multiSelection.clear();renderStudio();});rail.append(pageButton);
  const layersButton=nav.querySelector('[data-category=layers]');layersButton.textContent='Слои';rail.append(layersButton);
  const grid=button('Сетка',()=>{board.classList.toggle('creator-no-grid');grid.setAttribute('aria-pressed',String(!board.classList.contains('creator-no-grid')));});grid.setAttribute('aria-pressed','true');rail.append(grid);
  board.addEventListener('click',event=>{if(event.target===board){selectedID='';multiSelection.clear();renderStudio();}});
  const viewport=button('Компактный',()=>{studio.classList.toggle('creator-compact');viewport.setAttribute('aria-pressed',String(studio.classList.contains('creator-compact')));});viewport.setAttribute('aria-pressed','false');rail.append(viewport);
  nav.hidden=true;studio.querySelector('.new-panel-box').hidden=true;emptyTools.hidden=true;
  selectionTitle.hidden=true;
  inspector.querySelectorAll(':scope>h2,:scope>h3,:scope>.help-square,:scope>.layer-caption').forEach(node=>node.hidden=true);
  const policyBox=make('details','creator-security'), policySummary=make('summary','', 'Ограничения контента');policyBox.append(policySummary,policy);inspector.append(policyBox);
  const picker=make('section','creator-picker');picker.hidden=true;picker.setAttribute('role','dialog');picker.setAttribute('aria-label','Добавить компонент');
  const pickerHead=make('header','');pickerHead.append(make('h3','','Добавить компонент'),button('Закрыть',()=>closePicker()));
  const search=make('input','');search.type='search';search.placeholder='Найти компонент';search.setAttribute('aria-label','Найти компонент');
  const clear=button('Очистить',()=>{search.value='';search.dispatchEvent(new Event('input'));search.focus();});clear.hidden=true;
  const catalogue=make('div','creator-component-grid'), noResults=make('p','canvas-help','Компоненты не найдены. Измени запрос.');noResults.hidden=true;
  const components=[['text','Текст','Заголовок или описание'],['image','Изображение','Локальный PNG'],['button','Кнопка','Действие по нажатию'],['shape','Форма','Декоративная панель'],['video','Видео','MP4, WebM или YouTube']];
  for(const [id,title,description] of components){const entry=button(title,()=>createComponent(id));entry.dataset.search=(title+' '+description).toLocaleLowerCase('ru');entry.append(make('small','',description));catalogue.append(entry);}
  search.oninput=()=>{clear.hidden=!search.value;let count=0;catalogue.querySelectorAll('button').forEach(entry=>{entry.hidden=!entry.dataset.search.includes(search.value.toLocaleLowerCase('ru'));if(!entry.hidden)count++;});noResults.hidden=!!count;};
  picker.append(pickerHead,search,clear,catalogue,noResults);studio.append(picker);
  picker.addEventListener('keydown',event=>{if(event.key!=='Tab')return;const controls=[...picker.querySelectorAll('button,input')].filter(node=>!node.disabled&&node.getClientRects().length);const first=controls[0],last=controls.at(-1);if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}});
  function openPicker(){picker.hidden=false;search.focus();}
  function closePicker(){picker.hidden=true;add.focus();}
  function createComponent(kind){
    const old=studioDraft.length;studio.querySelector('#create-type').value=kind==='image'?'png':kind==='video'?'video':'text';
    // Reuse the original creation handler, including its element limit.
    originalCreate();if(studioDraft.length===old)return;
    const patch={name:{text:'Текст',image:'Изображение',button:'Кнопка',shape:'Форма',video:'Видео'}[kind],componentKind:kind};
    if(kind==='button')Object.assign(patch,{text:'Открыть',surface:true,align:'center'});
    if(kind==='shape')Object.assign(patch,{text:'',surface:true,shape:'rounded'});
    updateItem(patch);closePicker();properties.querySelector('textarea,input:not([type=file])')?.focus();
  }
  const bottom=make('section','creator-bottom');bottom.setAttribute('aria-label','Слои и ресурсы');
  const bottomHeader=make('header','creator-bottom-header'), layerBody=make('div','creator-layer-body'), assetBody=make('div','creator-asset-body');assetBody.hidden=true;
  const list=studio.querySelector('#studio-layers');layerBody.append(list);
  const groupActions=studio.querySelector('#group-items').parentElement;layerBody.prepend(groupActions);
  const layersTab=button('Слои',()=>showBottom('layers')), assetsTab=button('Ресурсы',()=>showBottom('assets'));
  const collapse=button('Свернуть',()=>{bottom.classList.toggle('creator-bottom-closed');collapse.textContent=bottom.classList.contains('creator-bottom-closed')?'Развернуть':'Свернуть';collapse.setAttribute('aria-expanded',String(!bottom.classList.contains('creator-bottom-closed')));});collapse.setAttribute('aria-expanded','true');
  bottomHeader.append(layersTab,assetsTab,collapse);bottom.append(bottomHeader,layerBody,assetBody);studio.append(bottom);
  function showBottom(mode){bottom.classList.remove('creator-bottom-closed');layerBody.hidden=mode!=='layers';assetBody.hidden=mode!=='assets';layersTab.setAttribute('aria-pressed',String(mode==='layers'));assetsTab.setAttribute('aria-pressed',String(mode==='assets'));collapse.textContent='Свернуть';collapse.setAttribute('aria-expanded','true');}
  layersButton.onclick=()=>showBottom('layers');showBottom('layers');
  const title=make('h2','creator-inspector-title');properties.before(title);
  const empty=make('section','creator-empty');empty.append(make('h3','','Страница пуста'),make('p','','Добавь компонент или начни с готовой страницы.'),button('Добавить компонент',openPicker),button('Выбрать шаблон',()=>window.NexusCreator.loadTemplate()),button('Academy',()=>window.NexusCreator.academy()));studio.querySelector('.canvas-area').append(empty);
  const sectionState=new Map();
  // Legacy category filtering is replaced by contextual disclosure; existing fields keep handlers.
  filterTools=()=>{nav.hidden=true;studio.querySelector('.new-panel-box').hidden=true;emptyTools.hidden=true;list.hidden=false;groupActions.hidden=false;};
  const oldInspector=renderInspector;
  renderInspector=()=>{
    oldInspector();filterTools();const item=currentItem();title.textContent=item?({png:'Изображение',video:'Видео',text:item.componentKind==='button'?'Кнопка':item.componentKind==='shape'?'Форма':'Текст'}[item.type]||'Компонент'):'Страница';
    selectionTitle.hidden=true;bgSettings.hidden=!!item;
    if(!item){properties.replaceChildren(make('p','canvas-help','Элемент не выбран. Настрой страницу или добавь компонент.'),button('Добавить компонент',openPicker));bgSettings.querySelectorAll('select').forEach(select=>{if(!select.nextElementSibling?.classList.contains('creator-choice'))dressSelect(select);});return;}
    const children=[...properties.children];const sections=new Map();
    for(const child of children){
      if(child.classList.contains('layer-caption')||child.classList.contains('font-option-sample')||child.classList.contains('color-wheel')){child.remove();continue;}
      child.hidden=false;child.querySelectorAll('.help-square').forEach(node=>node.remove());
      let category=child.dataset.toolCategory||'text';if(child.classList.contains('position-fields'))category='layout';
      if(child.querySelector('[data-creator-property=name]'))category='content';
      if(child.querySelector('[data-creator-property=text]'))category='content';
      if(category==='layers'){child.hidden=true;continue;}
      const key={layout:'Размер и положение',content:'Содержание',create:'Источник',text:'Типографика',shape:'Оформление',actions:'Действие',page:'Страница',left:'Колонка',sections:'Разделы'}[category]||'Дополнительно';
      if((item.type!=='text'||item.componentKind==='shape')&&category==='text'){child.hidden=true;continue;}
      let section=sections.get(key);if(!section){section=make('details','creator-inspector-section');section.open=sectionState.get(key)??['Содержание','Источник','Размер и положение'].includes(key);section.append(make('summary','',key));section.addEventListener('toggle',()=>sectionState.set(key,section.open));sections.set(key,section);properties.append(section);}section.append(child);
    }
    // Native popup geometry is replaced by one keyboard-operable Studio choice disclosure.
    properties.querySelectorAll('select').forEach(dressSelect);
    dressFileInputs(properties);
    if(item.type==='png'&&item.src){const sourceSection=sections.get('Источник');if(sourceSection){const preview=make('img','creator-source-preview');preview.src=item.src;preview.alt=item.name;sourceSection.querySelector('summary').after(preview);}}
    const elementActions=make('details','creator-inspector-section');elementActions.append(make('summary','','Действия элемента'));const actionBody=make('div','creator-element-actions');actions(actionBody,item);elementActions.append(actionBody);properties.append(elementActions);
  };
  function dressSelect(select){
    select.hidden=true;const disclosure=make('details','creator-choice'),summary=make('summary','',select.selectedOptions[0]?.textContent||'Выбрать');disclosure.append(summary);
    for(const option of select.options){const choice=button(option.textContent,()=>{select.value=option.value;disclosure.open=false;select.dispatchEvent(new Event('change',{bubbles:true}));});choice.disabled=option.disabled||select.disabled;choice.setAttribute('aria-pressed',String(option.selected));disclosure.append(choice);}select.after(disclosure);
  }
  const menu=make('section','creator-context');menu.hidden=true;menu.setAttribute('aria-label','Действия элемента');studio.append(menu);
  function actions(container,item){
    container.replaceChildren();container.append(button('Свойства',()=>{menu.hidden=true;properties.querySelector('input,textarea,summary')?.focus();}),button('Дублировать',()=>duplicate(item)),button(item.locked?'Разблокировать':'Заблокировать',()=>updateItem({locked:!item.locked})),button('Удалить',()=>{if(item.locked){errorStudio('Сначала разблокируй элемент.');return;}studioDraft=studioDraft.filter(x=>x.id!==item.id);selectedID=studioDraft.at(-1)?.id;multiSelection.delete(item.id);renderStudio();}));
    for(const [name,delta] of [['Ниже',-1],['Выше',1]])container.append(button(name,()=>{const i=studioDraft.indexOf(item),j=i+delta;if(j<0||j>=studioDraft.length)return;[studioDraft[i],studioDraft[j]]=[studioDraft[j],studioDraft[i]];renderStudio();}));
    container.append(button(item.hidden?'Показать':'Скрыть',()=>updateItem({hidden:!item.hidden})),button('Группировать',()=>studio.querySelector('#group-items').click()),button('Разгруппировать',()=>studio.querySelector('#ungroup-items').click()));
  }
  function duplicate(item){if(studioDraft.length>=30){errorStudio('Максимум 30 элементов.');return;}const copy=structuredClone(item);copy.id='element'+(++studioCounter);copy.name+=' · копия';copy.group='';copy.locked=false;copy.x=Math.min(100-copy.w,copy.x+2);copy.y=Math.min(100-copy.h,copy.y+2);if(!validStudio([...studioDraft,copy])){errorStudio('Копия превышает лимит ссылочных панелей.');return;}studioDraft.push(copy);selectedID=copy.id;renderStudio();}
  board.addEventListener('contextmenu',event=>{const node=event.target.closest('[data-item]');if(!node)return;event.preventDefault();selectedID=node.dataset.item;renderStudio();actions(menu,currentItem());menu.hidden=false;menu.style.left=Math.min(event.clientX,innerWidth-220)+'px';menu.style.top=Math.min(event.clientY,innerHeight-330)+'px';menu.querySelector('button').focus();});
  document.addEventListener('pointerdown',event=>{if(!menu.contains(event.target))menu.hidden=true;});
  document.addEventListener('keydown',event=>{if(event.isComposing)return;if(event.key==='Escape'){menu.hidden=true;if(!picker.hidden)closePicker();}if(event.target.closest('input,textarea,select,[contenteditable]'))return;const item=currentItem();if(!item)return;if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='d'){event.preventDefault();duplicate(item);}else if(event.key==='Delete'&&!item.locked){event.preventDefault();studioDraft=studioDraft.filter(x=>x.id!==item.id);selectedID=studioDraft.at(-1)?.id;renderStudio();}else if(['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)&&!item.locked){event.preventDefault();const d=event.shiftKey?2:1;updateItem({x:item.x+(event.key==='ArrowRight'?d:event.key==='ArrowLeft'?-d:0),y:item.y+(event.key==='ArrowDown'?d:event.key==='ArrowUp'?-d:0)});}});
  const oldRender=renderStudio;
  renderStudio=()=>{oldRender();menu.hidden=true;empty.hidden=!!studioDraft.length;
    list.querySelectorAll(':scope>button').forEach((row,index)=>{const item=[...studioDraft].reverse()[index];row.title=item.name;row.classList.toggle('creator-layer-hidden',!!item.hidden);const state=make('span','creator-layer-state',item.locked?'◆':item.hidden?'○':item.group?'▸':'');state.setAttribute('aria-label',item.locked?'Заблокирован':item.hidden?'Скрыт':item.group?'Группа':'');row.append(state);row.oncontextmenu=event=>{event.preventDefault();selectedID=item.id;renderStudio();actions(menu,item);menu.hidden=false;menu.style.left=Math.min(event.clientX,innerWidth-220)+'px';menu.style.top=Math.min(event.clientY,innerHeight-330)+'px';};});
    assetBody.replaceChildren();const assets=studioDraft.filter(x=>x.src);if(!assets.length)assetBody.append(make('p','canvas-help','Ресурсов пока нет. Добавь изображение или видео и выбери файл в свойствах.'));for(const item of assets){const entry=button(item.name,()=>{selectedID=item.id;renderStudio();showBottom('assets');});if(item.type==='png'){const image=make('img','');image.src=item.src;image.alt='';entry.prepend(image);}assetBody.append(entry);}assetBody.append(make('p','canvas-help','Используемые ресурсы страницы. Локальные файлы доступны в текущем сеансе.'));
  };
  const oldCanvas=renderCanvas;renderCanvas=(target,items,editing)=>{oldCanvas(target,items,editing);for(const item of items){const node=target.querySelector(`[data-item="${CSS.escape(item.id)}"]`);if(node)node.hidden=!!item.hidden;}};
  window.NexusStudioUI=Object.freeze({openPicker,showBottom});
})();
