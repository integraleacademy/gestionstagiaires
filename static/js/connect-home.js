/* Accessible, independent tab groups; no network calls or account data. */
(() => {
  'use strict';
  const home = document.querySelector('.connect-home');
  if (!home) return;

  home.querySelectorAll('[data-home-tabs]').forEach(group => {
    const tabs = [...group.querySelectorAll('[role="tab"]')];
    const panels = tabs.map(tab => document.getElementById(tab.getAttribute('aria-controls')));
    if (!tabs.length || panels.some(panel => !panel)) return;
    const activate = (index, focus = false) => {
      tabs.forEach((tab, i) => {
        const selected = i === index;
        tab.setAttribute('aria-selected', String(selected));
        tab.tabIndex = selected ? 0 : -1;
        panels[i].hidden = !selected;
      });
      if (focus) tabs[index].focus();
    };
    tabs.forEach((tab, index) => {
      tab.addEventListener('click', () => activate(index));
      tab.addEventListener('keydown', event => {
        const vertical = tab.closest('[role="tablist"]').getAttribute('aria-orientation') === 'vertical';
        const next = vertical ? 'ArrowDown' : 'ArrowRight';
        const previous = vertical ? 'ArrowUp' : 'ArrowLeft';
        let target;
        if (event.key === next) target = (index + 1) % tabs.length;
        else if (event.key === previous) target = (index - 1 + tabs.length) % tabs.length;
        else if (event.key === 'Home') target = 0;
        else if (event.key === 'End') target = tabs.length - 1;
        if (target === undefined) return;
        event.preventDefault();
        activate(target, true);
      });
    });
  });

  if ('IntersectionObserver' in window && !window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    const observer = new IntersectionObserver(entries => {
      entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        entry.target.classList.remove('home-reveal--waiting');
        observer.unobserve(entry.target);
      });
    }, { rootMargin: '0px 0px 35px 0px', threshold: 0.04 });
    home.querySelectorAll('.home-reveal').forEach(section => {
      if (section.getBoundingClientRect().top > window.innerHeight) {
        section.classList.add('home-reveal--waiting');
        observer.observe(section);
      }
    });
    // Anchor/keyboard navigation must never land on visually hidden content.
    home.addEventListener('focusin', event => event.target.closest('.home-reveal')?.classList.remove('home-reveal--waiting'));
    window.addEventListener('hashchange', () => {
      const target = document.getElementById(window.location.hash.slice(1));
      target?.closest('.home-reveal')?.classList.remove('home-reveal--waiting');
    });
  }
})();
