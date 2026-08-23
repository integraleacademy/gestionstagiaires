(function(root, factory){
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) {
    root.__responsiveV2 = api;
    api.init();
  }
})(typeof window !== 'undefined' ? window : null, function(){
  'use strict';

  const MOBILE_QUERY = '(max-width: 980px)';
  const CARD_QUERY = '(max-width: 720px)';
  const SIDEBAR_QUERY = '(max-width: 860px)';
  const CARD_MAX_COLUMNS = 8;
  const CARD_MAX_ROWS = 40;
  const TABLE_EXCLUSIONS = [
    '#traineesTable',
    '[data-responsive-scroll-only]',
    '.no-responsive-card',
    '.comparison-card table',
    '.docs-to-control-list table'
  ].join(',');

  function canCardifyShape(meta){
    if (!meta || meta.excluded || meta.hasEditable || meta.hasComplexSpan || meta.hasFooter) return false;
    if (!Number.isInteger(meta.headerCount) || meta.headerCount < 2 || meta.headerCount > CARD_MAX_COLUMNS) return false;
    if (!Number.isInteger(meta.rowCount) || meta.rowCount < 1 || meta.rowCount > CARD_MAX_ROWS) return false;
    if (!Array.isArray(meta.rowCellCounts) || meta.rowCellCounts.length !== meta.rowCount) return false;
    return meta.rowCellCounts.every((count) => count === meta.headerCount);
  }

  function computeScrollState(meta){
    const scrollWidth = Number(meta?.scrollWidth || 0);
    const clientWidth = Number(meta?.clientWidth || 0);
    const scrollLeft = Math.max(0, Number(meta?.scrollLeft || 0));
    const scrollable = scrollWidth > clientWidth + 2;
    const maxScroll = Math.max(0, scrollWidth - clientWidth);
    return {
      scrollable,
      atStart: !scrollable || scrollLeft <= 2,
      atEnd: !scrollable || scrollLeft >= maxScroll - 2
    };
  }

  function getHeaders(table){
    let headers = Array.from(table.querySelectorAll('thead th'));
    if (!headers.length) {
      const firstRow = table.querySelector('tr');
      if (firstRow) headers = Array.from(firstRow.querySelectorAll('th'));
    }
    return headers.map((cell) => (cell.textContent || '').replace(/\s+/g, ' ').trim());
  }

  function buildTableMeta(table){
    const headers = getHeaders(table);
    const rows = Array.from(table.tBodies || []).flatMap((tbody) => Array.from(tbody.rows || []));
    const excluded = table.matches(TABLE_EXCLUSIONS) || Boolean(table.closest('.comparison-card, .docs-to-control-list'));
    const hasEditable = Boolean(table.querySelector('input, select, textarea, [contenteditable="true"], form'));
    const hasComplexSpan = Boolean(table.querySelector('[rowspan]:not([rowspan="1"]), [colspan]:not([colspan="1"])'));
    return {
      headers,
      rows,
      meta: {
        excluded,
        hasEditable,
        hasComplexSpan,
        hasFooter: Boolean(table.tFoot),
        headerCount: headers.length,
        rowCount: rows.length,
        rowCellCounts: rows.map((row) => row.cells.length)
      }
    };
  }

  function canUseCardLayout(table){
    return canCardifyShape(buildTableMeta(table).meta);
  }

  function labelCardCells(table){
    const {headers, rows} = buildTableMeta(table);
    rows.forEach((row) => {
      Array.from(row.cells).forEach((cell, index) => {
        cell.dataset.label = headers[index] || '';
      });
    });
  }

  function enhanceCardTable(table){
    if (!canUseCardLayout(table)) {
      table.classList.remove('responsive-card-table');
      table.removeAttribute('data-responsive-card');
      return;
    }
    labelCardCells(table);
    table.classList.add('responsive-card-table');
    table.setAttribute('data-responsive-card', 'true');
  }

  function baseAriaLabel(wrapper){
    if (!wrapper.dataset.responsiveBaseLabel) {
      wrapper.dataset.responsiveBaseLabel = wrapper.getAttribute('aria-label') || 'Tableau';
    }
    return wrapper.dataset.responsiveBaseLabel;
  }

  function updateScrollState(wrapper){
    const state = computeScrollState(wrapper);
    wrapper.classList.toggle('is-scrollable', state.scrollable);
    wrapper.classList.toggle('is-at-start', state.atStart);
    wrapper.classList.toggle('is-at-end', state.atEnd);
    if (state.scrollable) {
      wrapper.setAttribute('role', wrapper.getAttribute('role') || 'region');
      wrapper.setAttribute('tabindex', wrapper.getAttribute('tabindex') || '0');
      wrapper.setAttribute('aria-label', `${baseAriaLabel(wrapper)} — défilement horizontal disponible`);
      wrapper.setAttribute('aria-description', 'Faites glisser horizontalement pour voir toutes les colonnes.');
    } else {
      const label = baseAriaLabel(wrapper);
      if (label) wrapper.setAttribute('aria-label', label);
      wrapper.removeAttribute('aria-description');
    }
  }

  function observeScrollableWrapper(wrapper){
    if (wrapper.dataset.responsiveScrollObserved === '1') {
      updateScrollState(wrapper);
      return;
    }
    wrapper.dataset.responsiveScrollObserved = '1';
    wrapper.addEventListener('scroll', () => updateScrollState(wrapper), {passive:true});
    updateScrollState(wrapper);
  }

  function tableWrapper(table){
    return table.closest('.table-wrap, .partners-table-wrap, .responsive-table-scroll');
  }

  function enhanceTables(scope){
    const rootNode = scope || document;
    rootNode.querySelectorAll('table').forEach((table) => {
      if (window.matchMedia(CARD_QUERY).matches) enhanceCardTable(table);
      else table.classList.remove('responsive-card-table');
      const wrapper = tableWrapper(table);
      if (wrapper) observeScrollableWrapper(wrapper);
    });
  }

  let sidebarLocked = false;
  let sidebarScrollY = 0;
  let sidebarOpener = null;

  function focusableElements(sidebar){
    return Array.from(sidebar.querySelectorAll(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )).filter((node) => node.offsetParent !== null || node === document.activeElement);
  }

  function lockPageForSidebar(sidebar){
    if (sidebarLocked) return;
    sidebarLocked = true;
    sidebarScrollY = window.scrollY || document.documentElement.scrollTop || 0;
    const active = document.activeElement;
    sidebarOpener = active?.matches?.('[data-sidebar-open]') ? active : document.querySelector('[data-sidebar-open]');
    document.body.classList.add('responsive-sidebar-lock');
    document.body.style.top = `-${sidebarScrollY}px`;
    document.body.style.width = '100%';
    window.requestAnimationFrame(() => {
      const focusables = focusableElements(sidebar);
      focusables[0]?.focus?.({preventScroll:true});
    });
  }

  function unlockPageFromSidebar(){
    if (!sidebarLocked) return;
    sidebarLocked = false;
    document.body.classList.remove('responsive-sidebar-lock');
    document.body.style.top = '';
    document.body.style.width = '';
    window.scrollTo(0, sidebarScrollY);
    const opener = sidebarOpener;
    sidebarOpener = null;
    window.requestAnimationFrame(() => opener?.focus?.({preventScroll:true}));
  }

  function syncSidebarState(){
    const sidebar = document.getElementById('partnerSidebar');
    if (!sidebar) return;
    const isMobile = window.matchMedia(SIDEBAR_QUERY).matches;
    const isOpen = isMobile && (sidebar.classList.contains('is-open') || document.body.classList.contains('partner-sidebar-open'));
    if (isOpen) lockPageForSidebar(sidebar);
    else unlockPageFromSidebar();
  }

  function trapSidebarFocus(event){
    if (event.key !== 'Tab' || !window.matchMedia(SIDEBAR_QUERY).matches) return;
    const sidebar = document.getElementById('partnerSidebar');
    if (!sidebar || !sidebar.classList.contains('is-open')) return;
    const focusables = focusableElements(sidebar);
    if (!focusables.length) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function installDynamicObservers(scope){
    let scheduled = false;
    const scheduleEnhance = () => {
      if (scheduled) return;
      scheduled = true;
      window.requestAnimationFrame(() => {
        scheduled = false;
        enhanceTables(scope);
        syncSidebarState();
      });
    };

    const mutationObserver = new MutationObserver(scheduleEnhance);
    mutationObserver.observe(scope, {childList:true, subtree:true});

    if (typeof ResizeObserver === 'function') {
      const resizeObserver = new ResizeObserver(() => {
        scope.querySelectorAll('.table-wrap, .partners-table-wrap, .responsive-table-scroll').forEach(updateScrollState);
      });
      resizeObserver.observe(document.documentElement);
    }

    const sidebar = document.getElementById('partnerSidebar');
    if (sidebar) {
      const sidebarObserver = new MutationObserver(syncSidebarState);
      sidebarObserver.observe(sidebar, {attributes:true, attributeFilter:['class']});
      sidebarObserver.observe(document.body, {attributes:true, attributeFilter:['class']});
    }
  }

  function init(){
    if (typeof document === 'undefined' || typeof window === 'undefined') return;
    const boot = () => {
      const scope = document.querySelector('.main-content') || document.body;
      document.body.classList.add('responsive-v2-ready');
      enhanceTables(scope);
      syncSidebarState();
      installDynamicObservers(scope);
      document.addEventListener('keydown', trapSidebarFocus);
      window.addEventListener('resize', () => {
        enhanceTables(scope);
        syncSidebarState();
      }, {passive:true});
      window.addEventListener('orientationchange', () => {
        window.setTimeout(() => {
          enhanceTables(scope);
          syncSidebarState();
        }, 120);
      });
    };

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, {once:true});
    else boot();
  }

  return {
    CARD_MAX_COLUMNS,
    CARD_MAX_ROWS,
    canCardifyShape,
    computeScrollState,
    canUseCardLayout,
    init
  };
});
