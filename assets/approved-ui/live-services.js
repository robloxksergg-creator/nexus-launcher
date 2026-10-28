/* Replace mock pack/mod actions with canonical native services. */
(() => {
  document.addEventListener('contextmenu',event=>event.preventDefault());
  const live=command=>{catalogModal.hidden=true;location.href='/desktop-command/'+command;};
  openCatalog=()=>live('mods');
  showPacks=()=>live('packs');
  document.querySelectorAll('[data-view="packs"]').forEach(button=>button.onclick=showPacks);
  catalogHere.onclick=openCatalog;
  // The native library occupies only the existing workspace. The approved
  // sidebar/topbar continue to own navigation and their original animations.
  window.NexusNativeLibrary = {
    enter() {
      app.classList.add('desktop-native-library');
      document.querySelectorAll('.nav [data-view]').forEach(button =>
        button.classList.toggle('active', button.dataset.view === 'packs'));
    },
    leave() { app.classList.remove('desktop-native-library'); },
    geometry() {
      const workspace = document.querySelector('.workspace').getBoundingClientRect();
      const topbar = document.querySelector('.topbar').getBoundingClientRect();
      return {x:workspace.left, y:topbar.bottom, width:workspace.width,
        height:Math.max(0, innerHeight-topbar.bottom),
        reducedMotion:matchMedia('(prefers-reduced-motion: reduce)').matches || app.classList.contains('profile-low-motion')};
    }
  };
  document.addEventListener('click', event => {
    const route = event.target.closest('[data-view], .profile, .global-settings-button');
    if (app.classList.contains('desktop-native-library') && route && route.dataset.view !== 'packs') {
      window.NexusNativeLibrary.leave();
      location.href='/desktop-command/library-leave';
    }
  }, true);
  const note=document.querySelector('.content > .settings-status');
  if(note)note.textContent='Сборки и моды используют реальные службы лаунчера. Редактор оформления и публичные миры ещё не подключены к публикации.';
})();
