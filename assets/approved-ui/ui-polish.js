(() => {
  soundEnabled=window.NexusInitialSound!==false;
  const priorSettings=renderSettingsSection;
  renderSettingsSection=()=>{
    priorSettings();if(activeSettingsSection!=='general')return;
    const row=[...settingsSpace.querySelectorAll('.settings-row')].find(row=>row.querySelector('span')?.firstChild?.textContent==='Звуки интерфейса');
    if(!row)return;
    const input=row.querySelector('input');input.id='persistent-interface-sound';input.checked=soundEnabled;
    const hint=document.createElement('small');hint.className='sound-persistence';hint.textContent='Включены при первом запуске. Ваш выбор сохраняется между запусками.';row.querySelector('span').append(hint);
    input.onchange=()=>{soundEnabled=input.checked;location.href='/desktop-command/'+(soundEnabled?'sound-on':'sound-off');};
  };

  function dressWorldCards(){
    worldsSpace.querySelectorAll('.world-server-card').forEach(card=>{
      const old=[...card.querySelectorAll('button')].find(button=>button.textContent==='Посмотреть');
      if(!old)return;
      const open=document.createElement('button');open.className='world-card-open';
      open.setAttribute('aria-label','Открыть '+card.querySelector('h2').textContent);
      open.onclick=old.onclick;old.remove();card.prepend(open);
    });
  }
  new MutationObserver(dressWorldCards).observe(worldsSpace,{childList:true,subtree:true});
  const oldWorlds=showWorldsSpace;showWorldsSpace=()=>{oldWorlds();dressWorldCards();};

  const oldProfile=showProfileSpace;
  showProfileSpace=tab=>{
    const switching=!profileSpace.hidden&&['overview','projects','about','workspace'].includes(tab);
    const x=scrollX,y=scrollY;
    // Rebuilding a short tab must not clamp the document before restoring scroll.
    if(!switching)profileSpace.style.minHeight='';
    if(switching)profileSpace.style.minHeight=profileSpace.offsetHeight+'px';
    oldProfile(tab);
    const identity=profileSpace.querySelector('.profile-identity'),tabs=profileSpace.querySelector('.profile-nav');
    if(identity&&tabs)identity.append(tabs);
    if(switching){scrollTo({left:x,top:y,behavior:'instant'});requestAnimationFrame(()=>scrollTo({left:x,top:y,behavior:'instant'}));}
    profileSpace.querySelector('.profile-panel')?.classList.add('profile-enter');
  };
  const oldHeader=renderPackHeader;
  renderPackHeader=entry=>{oldHeader(entry);const edit=worldButton('Изменить профиль сборки',()=>editButton.click());packHeader.querySelector('.pack-header-actions')?.append(edit);};
})();
