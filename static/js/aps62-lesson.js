(() => {
  'use strict';
  const root = document.querySelector('[data-aps-lesson]');
  if (!root) return;

  // VTC text is a stream of headings and paragraphs. Keep their order and
  // existing DOM nodes, grouping complete paragraphs into short reading steps.
  root.querySelectorAll('[data-native-lesson-split]').forEach(container => {
    const children = [...container.children];
    if (!children.length) { container.hidden = true; return; }
    container.setAttribute('data-aps-lesson-group', '');
    let chunk = [], words = 0, hasBody = false;
    function flush() {
      if (!chunk.length) return;
      const page = document.createElement('div');
      page.setAttribute('data-aps-lesson-page', '');
      page.append(...chunk);
      container.append(page);
      chunk = []; words = 0; hasBody = false;
    }
    children.forEach(child => {
      const heading = /^H[1-6]$/.test(child.tagName);
      const size = child.textContent.trim().split(/\s+/).filter(Boolean).length;
      if (hasBody && (heading || words + size > 260)) flush();
      chunk.push(child); words += size;
      if (!heading && !child.matches('.vtc-eyebrow, .aps-label')) hasBody = true;
    });
    flush();
  });
  const pages = [...root.querySelectorAll('[data-aps-lesson-page]')];
  const groups = [...root.querySelectorAll('[data-aps-lesson-group]')];
  const navigation = root.querySelector('[data-aps-lesson-navigation]');
  const progress = root.querySelector('[data-aps-lesson-progress]');
  const status = root.querySelector('[data-aps-lesson-status]');
  const count = root.querySelector('[data-aps-lesson-count]');
  const bar = root.querySelector('[data-aps-lesson-bar]');
  const previous = root.querySelector('[data-aps-lesson-previous]');
  const next = root.querySelector('[data-aps-lesson-next]');
  const timing = window.nativeLessonTiming || null;
  const completion = root.querySelector('[data-aps-lesson-completion]');
  const activityNavigation = document.querySelector('.native-navigation-actions');
  const activityAction = document.getElementById('nativeActionButton')
    || activityNavigation?.querySelector('.native-preview-actions');
  if (pages.length < 2 || !navigation || !progress || !status || !count || !bar
      || !previous || !next || !completion || !activityAction) return;

  // Reuse the existing completion control and its tracking/validation handlers.
  // Turning a reading page never completes an activity or sends a request.
  completion.append(activityAction);
  activityNavigation.hidden = true;
  activityNavigation.classList.add('aps-lesson-original-navigation');
  root.classList.add('is-paginated');
  navigation.hidden = false;
  progress.hidden = false;

  const timingNotice = timing ? document.createElement('p') : null;
  if (timingNotice) {
    timingNotice.className = 'aps-lesson-timing';
    timingNotice.setAttribute('data-aps-lesson-timing', '');
    progress.append(timingNotice);
  }

  const videoPage = pages.findIndex(page => page.querySelector('video'));
  let videoShortcut = null;
  if (videoPage >= 0) {
    videoShortcut = document.createElement('button');
    videoShortcut.type = 'button';
    videoShortcut.className = 'aps-small-button';
    videoShortcut.textContent = 'Revenir à la vidéo';
    videoShortcut.setAttribute('data-lesson-video-shortcut', '');
    progress.insertBefore(videoShortcut, bar.parentElement);
    videoShortcut.addEventListener('click', () => show(videoPage, true));
  }
  root.querySelectorAll('audio, video').forEach(media => {
    // A timed learning pause must not restart playback on a hidden step.
    media.addEventListener('play', () => {
      if (media.closest('[data-aps-lesson-page][hidden], [data-aps-lesson-group][hidden]')) media.pause();
    });
  });

  const storageKey = `apsLessonStep:v1:${location.pathname}:${root.dataset.lessonKey}`;
  let current = 0;

  function anchoredPage(hash = location.hash) {
    if (!hash) return -1;
    let id;
    try { id = decodeURIComponent(hash.slice(1)); } catch (_error) { return -1; }
    const target = document.getElementById(id);
    if (!target || !root.contains(target)) return -1;
    return pages.findIndex(page => page === target || page.contains(target) || target.contains(page));
  }

  function show(index, focus = false) {
    if (timing) index = Math.min(index, timing.firstPending());
    current = Math.max(0, Math.min(pages.length - 1, index));
    const selected = pages[current];
    pages.forEach(page => {
      page.hidden = page !== selected;
      if (page.hidden) page.querySelectorAll('audio, video').forEach(media => {
        if (!media.paused) media.pause();
      });
    });
    groups.forEach(group => {
      group.hidden = !group.contains(selected);
      if (group.hidden) group.querySelectorAll('audio, video').forEach(media => {
        if (!media.paused) media.pause();
      });
      if (!group.hidden && group.tagName === 'DETAILS') group.open = true;
    });
    const label = `Étape ${current + 1} sur ${pages.length}`;
    status.textContent = label;
    count.textContent = label;
    bar.style.width = `${((current + 1) / pages.length) * 100}%`;
    previous.disabled = current === 0;
    const last = current === pages.length - 1;
    next.hidden = last;
    completion.hidden = !last;
    if (timing) { timing.select(current); renderTiming(); }
    if (videoShortcut) videoShortcut.hidden = current === videoPage;
    try { sessionStorage.setItem(storageKey, String(current)); } catch (_error) { /* Reading works without storage. */ }
    if (focus) {
      status.focus({ preventScroll: true });
      progress.scrollIntoView({ block: 'start', behavior: 'instant' });
    }
  }

  function renderTiming() {
    if (!timing || !timingNotice) return;
    if (timing.pages.length !== pages.length) {
      next.disabled = true;
      completion.hidden = true;
      timingNotice.textContent = 'Le cours a été mis à jour. Rechargez la page pour poursuivre.';
      return;
    }
    const ready = timing.ready(current);
    const seconds = timing.remaining(current);
    const clock = `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
    next.disabled = !ready;
    next.textContent = ready ? 'Suivant →' : seconds ? `Suivant dans ${clock}` : 'Enregistrement…';
    timingNotice.dataset.ready = String(ready);
    timingNotice.textContent = ready ? 'Temps de lecture validé · Vous pouvez poursuivre ou relire cette page.'
      : `Temps de lecture : ${timing.pages[current].required_seconds / 60} min minimum · ${clock} restantes${document.visibilityState !== 'visible' || !document.hasFocus() ? ' · En pause' : ''}`;
  }
  document.addEventListener('native-lesson-timing', renderTiming);

  let initial = timing ? Math.min(timing.firstPending(), pages.length - 1) : 0;
  try {
    const raw = sessionStorage.getItem(storageKey);
    const saved = Number(raw);
    if (raw !== null && Number.isInteger(saved) && saved >= 0 && saved < pages.length) initial = saved;
  } catch (_error) { /* Reading works without storage. */ }
  const anchor = anchoredPage();
  show(anchor >= 0 ? anchor : initial, anchor >= 0);
  previous.addEventListener('click', () => show(current - 1, true));
  next.addEventListener('click', () => { if (!timing || timing.ready(current)) show(current + 1, true); });
  root.addEventListener('click', event => {
    if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    const link = event.target.closest('a[href^="#"]');
    if (!link || link.target === '_blank') return;
    const index = anchoredPage(link.hash);
    if (index < 0) return;
    event.preventDefault();
    show(index, true);
  });
  window.addEventListener('hashchange', () => {
    const index = anchoredPage();
    if (index >= 0) show(index, true);
  });
})();
