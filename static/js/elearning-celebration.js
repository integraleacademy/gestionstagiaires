(() => {
  'use strict';
  // This element is rendered only by the authenticated, server-verified route.
  const dialog = document.querySelector('[data-el-celebration]');
  if (!dialog) return;
  const key = 'el-celebration:' + dialog.dataset.elCelebration;
  try { if (sessionStorage.getItem(key)) return; } catch (_) {}
  const previousFocus = document.activeElement;
  const confetti = dialog.querySelector('[data-confetti]');
  let timer;
  function clear() { clearTimeout(timer); confetti.replaceChildren(); }
  dialog.querySelectorAll('[data-celebration-close]').forEach(button => button.addEventListener('click', () => dialog.close()));
  dialog.addEventListener('close', () => {
    clear(); window.elCelebrationInProgress = false;
    const heading = document.querySelector('.el-hero h1');
    if (heading) { heading.setAttribute('tabindex', '-1'); heading.focus({preventScroll: true}); }
    else previousFocus?.focus();
  });
  dialog.showModal();
  window.elCelebrationInProgress = true;
  try { sessionStorage.setItem(key, 'shown'); } catch (_) {}
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const colors = ['#ff8a2b', '#2b6bea', '#ffc94f', '#27bd9b', '#a78bfa', '#ff72ac'];
  for (let i = 0; i < 110; i++) {
    const piece = document.createElement('i');
    piece.className = 'el-confetti-piece';
    piece.style.setProperty('--x', (Math.random() * 100).toFixed(2) + 'vw');
    piece.style.setProperty('--drift', (Math.random() * 36 - 18).toFixed(2) + 'vw');
    piece.style.setProperty('--delay', (Math.random() * 1.5).toFixed(2) + 's');
    piece.style.setProperty('--duration', (3 + Math.random() * 2).toFixed(2) + 's');
    piece.style.setProperty('--rotation', (Math.random() * 1440 - 720).toFixed(0) + 'deg');
    piece.style.backgroundColor = colors[i % colors.length];
    if (i % 3 === 0) piece.style.borderRadius = '50%';
    confetti.append(piece);
  }
  timer = setTimeout(clear, 7000);
})();
