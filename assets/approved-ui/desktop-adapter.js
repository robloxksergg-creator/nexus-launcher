/* Desktop host additions; the original prototype stays byte-identical. */
(() => {
  let playBorderEnabled = true;
  const applyPlayBorder = () => document.querySelector('.app')?.classList.toggle('play-border-enabled', playBorderEnabled);
  applyPlayBorder();
  const previousSettingsRenderer = renderSettingsSection;
  renderSettingsSection = () => {
    previousSettingsRenderer();
    if (activeSettingsSection !== 'general') return;
    const row = document.createElement('label');
    row.className = 'settings-row';
    const label = document.createElement('span');
    label.textContent = 'Обводка кнопки «Играть»';
    const hint = document.createElement('small');
    hint.textContent = 'Выделяет кнопку запуска. В тестовой сборке сохраняется до закрытия.';
    label.append(hint);
    const input = document.createElement('input');
    input.type = 'checkbox';
    input.id = 'desktop-play-border';
    input.checked = playBorderEnabled;
    input.onchange = () => { playBorderEnabled = input.checked; applyPlayBorder(); };
    row.append(label, input);
    const target = document.querySelector('.settings-main');
    target.querySelector('.launcher-palette')?.before(row);
    if (!row.isConnected) target.append(row);
  };
  const bar = document.createElement('div');
  bar.className = 'tools';
  bar.setAttribute('aria-label', 'Рабочие функции лаунчера');
  for (const [label, command] of [['Рабочие функции', 'services']]) {
    const button = document.createElement('button');
    button.className = 'outline';
    button.textContent = label;
    button.onclick = () => { location.href = '/desktop-command/' + command; };
    bar.append(button);
  }
  document.querySelector('.topbar')?.append(bar);
  const entry = document.createElement('button');
  entry.className = 'outline desktop-account-login';
  entry.id = 'desktop-account-login';
  entry.textContent = 'Войти';
  document.querySelector('.sidebar-account-row')?.after(entry);
  const auth = document.createElement('dialog');
  auth.className = 'desktop-auth-choice';
  auth.setAttribute('aria-labelledby', 'desktop-auth-title');
  const close = document.createElement('button');
  close.className = 'outline desktop-auth-close';
  close.textContent = '×';
  close.setAttribute('aria-label', 'Закрыть экран входа');
  close.onclick = () => auth.close();
  const eyebrow = document.createElement('p');
  eyebrow.className = 'eyebrow';
  eyebrow.textContent = 'NEXUS / АККАУНТ';
  const title = document.createElement('h2');
  title.id = 'desktop-auth-title';
  title.textContent = 'Твоё место в NEXUS.';
  const intro = document.createElement('p');
  intro.textContent = 'Один аккаунт для сайта и лаунчера.';
  auth.append(close, eyebrow, title, intro);
  const options = document.createElement('div');
  options.className = 'desktop-auth-options';
  for (const [question, label, command] of [
    ['У вас уже есть аккаунт?', 'Войти', 'login'],
    ['У вас ещё нет аккаунта?', 'Зарегистрироваться', 'register']
  ]) {
    const card = document.createElement('section');
    const heading = document.createElement('h3');
    heading.textContent = question;
    const button = document.createElement('button');
    button.className = command === 'login' ? 'launch' : 'outline';
    button.dataset.authCommand = command;
    button.textContent = label;
    button.onclick = () => { auth.close(); location.href = '/desktop-command/' + command; };
    card.append(heading, button);
    options.append(card);
  }
  auth.append(options);
  const disclaimer = document.createElement('p');
  disclaimer.className = 'desktop-auth-disclaimer';
  disclaimer.textContent = 'Аккаунт NEXUS. Подключение Microsoft пока недоступно.';
  auth.append(disclaimer);
  document.body.append(auth);
  entry.onclick = () => { if (!auth.open) auth.showModal(); };
  auth.addEventListener('close', () => entry.focus());
  document.addEventListener('keydown', event => {
    if (auth.open && event.key === 'Escape') {
      event.preventDefault();
      event.stopImmediatePropagation();
      auth.close();
    }
  }, true);

  // Keep source pixels intact: do not enlarge low-resolution preview artwork.
  // New high-resolution sources automatically release this limit.
  function sizeArtwork() {
    document.querySelectorAll('.canvas-preview .artboard').forEach(board => {
      const image = board.querySelector('[data-item="background"] img');
      if (!image) { board.style.maxWidth = ''; return; }
      const apply = () => {
        if (image.naturalWidth) board.style.maxWidth = image.naturalWidth / devicePixelRatio + 'px';
      };
      if (image.complete) apply();
      else image.addEventListener('load', apply, {once:true});
    });
  }
  new MutationObserver(sizeArtwork).observe(document.querySelector('.canvas-preview'), {childList:true, subtree:true});
  window.addEventListener('resize', sizeArtwork);
  sizeArtwork();
  const note = document.createElement('p');
  note.className = 'settings-status';
  note.textContent = 'Перенос функций: этот интерфейс пока сохраняет тестовые операции прототипа. Реальный запуск и установка доступны через «Рабочие функции». Вход и регистрация — настоящие.';
  document.querySelector('.content')?.prepend(note);
})();
