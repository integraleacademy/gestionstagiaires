(() => {
  'use strict';
  const root = document.querySelector('[data-aps-lesson]');
  if (!root) return;
  const pages = [...root.querySelectorAll('[data-aps-lesson-page]')];
  const groups = [...root.querySelectorAll('[data-aps-lesson-group]')];
  const navigation = root.querySelector('[data-aps-lesson-navigation]');
  const progress = root.querySelector('[data-aps-lesson-progress]');
  const status = root.querySelector('[data-aps-lesson-status]');
  const count = root.querySelector('[data-aps-lesson-count]');
  const bar = root.querySelector('[data-aps-lesson-bar]');
  const previous = root.querySelector('[data-aps-lesson-previous]');
  const next = root.querySelector('[data-aps-lesson-next]');
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

  const storageKey = `apsLessonStep:v1:${location.pathname}:${root.dataset.lessonKey}`;
  let current = 0;

  function anchoredPage() {
    if (!location.hash) return -1;
    let id;
    try { id = decodeURIComponent(location.hash.slice(1)); } catch (_error) { return -1; }
    const target = document.getElementById(id);
    if (!target || !root.contains(target)) return -1;
    return pages.findIndex(page => page === target || page.contains(target) || target.contains(page));
  }

  function show(index, focus = false) {
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
    try { sessionStorage.setItem(storageKey, String(current)); } catch (_error) { /* Reading works without storage. */ }
    if (focus) {
      status.focus({ preventScroll: true });
      progress.scrollIntoView({ block: 'start', behavior: 'instant' });
    }
  }

  let initial = 0;
  try {
    const saved = Number(sessionStorage.getItem(storageKey));
    if (Number.isInteger(saved) && saved >= 0 && saved < pages.length) initial = saved;
  } catch (_error) { /* Reading works without storage. */ }
  const anchor = anchoredPage();
  show(anchor >= 0 ? anchor : initial, anchor >= 0);
  previous.addEventListener('click', () => show(current - 1, true));
  next.addEventListener('click', () => show(current + 1, true));
  window.addEventListener('hashchange', () => {
    const index = anchoredPage();
    if (index >= 0) show(index, true);
  });
})();
