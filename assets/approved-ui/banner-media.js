/* Local creator banner preview, shared by every project; no upload endpoint. */
(() => {
  const retained=new Set();
  const motion=matchMedia('(prefers-reduced-motion: reduce)');
  const imageTypes=['image/png','image/jpeg','image/webp'];
  const videoTypes=['video/mp4','video/webm'];
  function validate(file){
    const video=videoTypes.includes(file.type);
    if(!video&&!imageTypes.includes(file.type))return 'Выберите PNG, JPEG, WebP, MP4 или WebM.';
    if(!file.size)return 'Файл пуст.';
    if(file.size>(video?200:20)*1024*1024)return video?'Видео должно быть не больше 200 МБ.':'Изображение должно быть не больше 20 МБ.';
    return '';
  }
  function decode(url,video){
    return new Promise((resolve,reject)=>{
      const media=document.createElement(video?'video':'img');
      const timer=setTimeout(()=>finish(false),8000);
      function finish(ok){clearTimeout(timer);media.onload=null;media.onerror=null;media.onloadeddata=null;if(video){media.pause();media.removeAttribute('src');media.load();}ok?resolve():reject(new Error('decode'));}
      media.onerror=()=>finish(false);
      if(video){media.muted=true;media.preload='auto';media.onloadeddata=()=>finish(media.videoWidth>0&&media.videoHeight>0);}else media.onload=()=>finish(media.naturalWidth>0);
      media.src=url;
    });
  }
  function attach(dialog,draft){
    let generation=0,alive=true,pending=null,preview=null;
    const area=document.createElement('section');area.className='banner-media-tools';
    const title=document.createElement('h3');title.textContent='Баннер проекта';
    const hint=document.createElement('p');hint.textContent='Статичный PNG/JPEG/WebP — до 20 МБ. Анимированный MP4/WebM — до 200 МБ, без звука. Это локальный предпросмотр, не публикация. Видео можно развернуть на весь экран.';
    const status=document.createElement('p');status.setAttribute('role','status');status.textContent=draft.banner?'Выбран: '+draft.banner.name:'Используется исходный баннер.';
    const file=document.createElement('input');file.type='file';file.hidden=true;file.accept=imageTypes.concat(videoTypes).join(',');file.id='creator-banner-file';
    const choose=worldButton('Выбрать баннер',()=>{file.value='';file.click();});
    function clearPreview(){if(preview){if(preview.tagName==='VIDEO'){preview.pause();preview.removeAttribute('src');preview.load();}preview.remove();preview=null;}}
    const remove=worldButton('Вернуть исходный баннер',()=>{generation++;choose.disabled=false;draft.banner=null;if(pending){URL.revokeObjectURL(pending);pending=null;}clearPreview();status.textContent='Используется исходный баннер.';});
    file.onchange=async()=>{
      const selected=file.files[0];if(!selected)return;
      const error=validate(selected);if(error){status.textContent=error;return;}
      const current=++generation,url=URL.createObjectURL(selected),video=videoTypes.includes(selected.type);
      status.textContent='Проверяем файл…';choose.disabled=true;
      try{
        await decode(url,video);
        if(!alive||current!==generation){URL.revokeObjectURL(url);return;}
        if(pending)URL.revokeObjectURL(pending);pending=url;
        draft.banner={url,kind:video?'video':'image',name:selected.name};
        clearPreview();preview=document.createElement(video?'video':'img');preview.className='banner-media-preview';preview.src=url;
        if(video){preview.muted=true;preview.controls=true;preview.playsInline=true;}else preview.alt='Предпросмотр баннера';
        status.after(preview);status.textContent='Выбран: '+selected.name+' · '+(selected.size/1024/1024).toFixed(1)+' МБ';
      }catch{URL.revokeObjectURL(url);if(alive&&current===generation)status.textContent='Не удалось открыть файл. Для видео попробуйте другой кодек MP4/WebM.';}
      finally{if(alive&&current===generation)choose.disabled=false;}
    };
    const buttons=document.createElement('div');buttons.className='block-actions';buttons.append(choose,remove);
    area.append(title,hint,file,buttons,status);dialog.querySelector('.server-layout-fields').after(area);
    return {dispose(commit){alive=false;generation++;clearPreview();if(pending){if(commit&&draft.banner?.url===pending)retained.add(pending);else URL.revokeObjectURL(pending);pending=null;}}};
  }
  function render(board,banner){
    if(!banner)return;
    let background=board.querySelector('[data-item=background]');
    if(!background){background=document.createElement('div');background.className='canvas-node image-node';background.dataset.item='background';Object.assign(background.style,{left:'0',top:'0',width:'100%',height:'100%',zIndex:'0'});board.querySelector('.artboard')?.prepend(background);}
    if(background.firstElementChild?.src===banner.url)return;
    board.querySelectorAll('.banner-pause,.banner-fullscreen').forEach(button=>button.remove());
    const media=document.createElement(banner.kind==='video'?'video':'img');media.src=banner.url;
    if(banner.kind!=='video'){media.alt='Баннер проекта';background.replaceChildren(media);return;}
    media.className='banner-video';media.muted=true;media.loop=true;media.playsInline=true;media.preload='metadata';background.replaceChildren(media);
    const toggle=worldButton('Запустить анимацию',()=>{if(media.paused)media.play().catch(()=>toggle.textContent='Не удалось запустить видео');else media.pause();});toggle.classList.add('banner-pause');
    toggle.setAttribute('aria-label','Запустить или приостановить анимированный баннер');
    media.addEventListener('play',()=>{toggle.textContent='Пауза';toggle.setAttribute('aria-pressed','true');});
    media.addEventListener('pause',()=>{toggle.textContent='Запустить анимацию';toggle.setAttribute('aria-pressed','false');});
    const fullscreen=worldButton('Развернуть баннер',()=>media.requestFullscreen?.().catch(()=>info('Полноэкранный просмотр недоступен.')));fullscreen.classList.add('banner-fullscreen');
    (board.querySelector('.artboard')||board).append(toggle,fullscreen);
    if(!motion.matches&&!app.classList.contains('profile-low-motion'))media.play().catch(()=>{});
  }
  function pauseHidden(){document.querySelectorAll('.banner-video').forEach(video=>{if(document.hidden||!video.offsetHeight||motion.matches||app.classList.contains('profile-low-motion'))video.pause();});}
  document.addEventListener('visibilitychange',pauseHidden);motion.addEventListener('change',pauseHidden);
  new MutationObserver(pauseHidden).observe(app,{attributes:true,subtree:true,attributeFilter:['hidden','class']});
  window.addEventListener('beforeunload',()=>retained.forEach(url=>URL.revokeObjectURL(url)));
  window.NexusBannerMedia=Object.freeze({attach,render,validate});
})();
