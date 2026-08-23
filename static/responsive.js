(() => {
  'use strict';

  const MOBILE_QUERY = '(max-width: 980px)';
  const SIDEBAR_QUERY = '(max-width: 860px)';

  function isMobile(){
    return window.matchMedia(MOBILE_QUERY).matches;
  }

  function closeMobileSidebar(){
    const sidebar = document.getElementById('partnerSidebar');
    const overlay = document.querySelector('.partner-sidebar-overlay');
    if (!sidebar) return;

    sidebar.classList.remove('is-open');
    overlay?.classList.remove('is-open');
    if (overlay) overlay.style.pointerEvents = 'none';
    document.body.classList.remove('partner-sidebar-open');
    document.querySelectorAll('[data-sidebar-open]').forEach((button) => {
      button.setAttribute('aria-expanded', 'false');
    });
  }

  function wrapResponsiveTables(){
    const scope = document.querySelector('.main-content') || document.querySelector('body > .container') || document.body;
    scope.querySelectorAll('table').forEach((table) => {
      if (table.closest('.table-wrap, .partners-table-wrap, .comparison-card, .responsive-table-scroll, .docs-to-control-list')) return;
      const wrapper = document.createElement('div');
      wrapper.className = 'responsive-table-scroll';
      wrapper.setAttribute('role', 'region');
      wrapper.setAttribute('aria-label', table.getAttribute('aria-label') || 'Tableau défilable horizontalement');
      wrapper.tabIndex = 0;
      table.parentNode?.insertBefore(wrapper, table);
      wrapper.appendChild(table);
    });
  }

  function normalizeViewportState(){
    if (!window.matchMedia(SIDEBAR_QUERY).matches) {
      closeMobileSidebar();
    }
  }

  function init(){
    document.body.classList.add('responsive-runtime-ready');
    wrapResponsiveTables();
    normalizeViewportState();

    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && window.matchMedia(SIDEBAR_QUERY).matches) {
        closeMobileSidebar();
      }
    });

    window.addEventListener('orientationchange', () => {
      window.setTimeout(normalizeViewportState, 100);
    });

    window.addEventListener('resize', normalizeViewportState, {passive:true});

    if (isMobile()) {
      document.querySelectorAll('.table-wrap, .partners-table-wrap, .responsive-table-scroll').forEach((wrapper) => {
        wrapper.setAttribute('tabindex', wrapper.getAttribute('tabindex') || '0');
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, {once:true});
  } else {
    init();
  }
})();
