/* Shared by learner and preview pages; no tracking or course-state changes. */
(() => {
  'use strict';
  const button=document.getElementById('nativeMenuButton');
  const sidebar=document.getElementById('nativeSidebar');
  if(!button||!sidebar)return;
  const overlay=document.getElementById('nativeSidebarOverlay');
  const close=document.getElementById('nativeMenuClose');
  const mobile=window.matchMedia('(max-width: 900px)');
  let opened=false,previousOverflow='',background=[];
  function focusable(){
    return [...sidebar.querySelectorAll('a[href],button,input,select,textarea,[tabindex]')].filter(node=>
      !node.disabled&&node.tabIndex>=0&&!node.closest('[hidden],[inert]')&&
      getComputedStyle(node).display!=='none'&&getComputedStyle(node).visibility!=='hidden');
  }
  function focusFirst(){(focusable()[0]||sidebar).focus();}
  function restoreBackground(){
    background.forEach(({node,inert,hidden})=>{
      node.toggleAttribute('inert',inert);
      if(hidden===null)node.removeAttribute('aria-hidden');else node.setAttribute('aria-hidden',hidden);
    });
    background=[];
  }
  function setMenu(requested,{returnFocus=true}={}){
    const wasOpen=opened;
    opened=Boolean(requested&&mobile.matches);
    sidebar.classList.toggle('is-open',opened);
    overlay?.classList.toggle('is-open',opened);
    button.setAttribute('aria-expanded',String(opened));
    sidebar.toggleAttribute('inert',mobile.matches&&!opened);
    if(mobile.matches&&!opened)sidebar.setAttribute('aria-hidden','true');else sidebar.removeAttribute('aria-hidden');
    if(opened){
      sidebar.setAttribute('role','dialog');
      sidebar.setAttribute('aria-modal','true');
      if(!wasOpen){
        previousOverflow=document.body.style.overflow;
        document.body.style.overflow='hidden';
        focusFirst();
        background=[...document.querySelectorAll('.native-topbar,.native-main')].map(node=>({node,inert:node.hasAttribute('inert'),hidden:node.getAttribute('aria-hidden')}));
        background.forEach(({node})=>{node.setAttribute('inert','');node.setAttribute('aria-hidden','true');});
      }
    }else{
      sidebar.removeAttribute('role');sidebar.removeAttribute('aria-modal');
      restoreBackground();
      if(wasOpen)document.body.style.overflow=previousOverflow;
      if(returnFocus&&mobile.matches&&(wasOpen||sidebar.contains(document.activeElement)))button.focus();
      if(!mobile.matches&&(document.activeElement===button||document.activeElement===close)){
        (sidebar.querySelector('a[aria-current="page"]')||sidebar.querySelector('a[href]')||sidebar).focus();
      }
    }
  }
  button.addEventListener('click',()=>setMenu(!opened));
  close?.addEventListener('click',()=>setMenu(false));
  overlay?.addEventListener('click',()=>setMenu(false));
  window.addEventListener('keydown',event=>{
    if(!opened)return;
    if(event.key==='Escape'){event.preventDefault();setMenu(false);return;}
    if(event.key!=='Tab')return;
    const items=focusable(),first=items[0],last=items.at(-1),active=document.activeElement;
    if(!items.length){event.preventDefault();sidebar.focus();}
    else if(event.shiftKey&&(active===first||!sidebar.contains(active))){event.preventDefault();last.focus();}
    else if(!event.shiftKey&&(active===last||!sidebar.contains(active))){event.preventDefault();first.focus();}
  });
  document.addEventListener('focusin',event=>{if(opened&&!sidebar.contains(event.target))focusFirst();});
  const changed=()=>setMenu(false);
  if(mobile.addEventListener)mobile.addEventListener('change',changed);else mobile.addListener(changed);
  setMenu(false,{returnFocus:false});
})();
