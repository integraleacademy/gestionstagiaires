"""Browser regression check using an isolated synthetic admin session."""
import json,threading,time
from pathlib import Path
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright
from tests.test_native_elearning_web import NativeElearningWebTests,gestion_app
case=NativeElearningWebTests(methodName='runTest');case.setUp();case._admin_login()
server=make_server('127.0.0.1',0,gestion_app.app,threaded=True);port=server.server_port
thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
out=Path('/tmp/vtc-final-audit');out.mkdir(exist_ok=True)
try:
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True);ctx=browser.new_context(viewport={'width':1440,'height':1050})
  cookie=case.client.get_cookie(gestion_app.app.config.get('SESSION_COOKIE_NAME','session'))
  ctx.add_cookies([{'name':cookie.key,'value':cookie.value,'domain':'127.0.0.1','path':'/'}])
  page=ctx.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto(f'http://127.0.0.1:{port}/admin/elearning/courses/academy-vtc-a/preview?activity=vtc-a-02-cours',wait_until='networkidle')
  page.wait_for_function("document.querySelector('video')?.readyState >= 2")
  assert page.locator('[data-playback-rate]').count()==0
  assert page.get_by_text('Texte de la voix',exact=True).count()==0
  assert page.locator('[data-video-caption-toggle]').count()==0
  assert page.locator('[data-video-companion]').is_visible()
  for rate in [.85,2,1.25]:
   page.locator('video').evaluate('(v,r)=>{v.playbackRate=r}',rate)
   page.wait_for_function("document.querySelector('video').playbackRate === 1")
  page.locator('video').evaluate('(v)=>{v.currentTime=64}')
  page.wait_for_function("!document.querySelector('video').seeking")
  assert page.locator('[data-video-scene-title]').inner_text()=='Séparer les quatre dossiers professionnels'
  page.locator('video').evaluate('(v)=>{v.muted=true; return v.play()}')
  page.mouse.move(0,0)
  page.wait_for_function("document.querySelector('video').readyState >= 3 && document.querySelector('video').currentTime >= 67")
  page.locator('.native-video-shell').screenshot(path=str(out/'player-desktop.png'))
  for width in [390,320]:
   page.set_viewport_size({'width':width,'height':900})
   page.locator('.native-video-shell').screenshot(path=str(out/f'player-{width}.png'))
   assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
  page.set_viewport_size({'width':1440,'height':1050})
  page.get_by_role('button',name='Agrandir la lecture').click()
  assert page.locator('video').count()==1
  assert page.get_by_role('button',name='Réduire la lecture').is_visible()
  page.keyboard.press('Escape')
  assert page.get_by_role('button',name='Agrandir la lecture').is_visible()
  assert not errors,errors
  browser.close()
 (out/'browser.json').write_text(json.dumps({'viewports':[1440,390,320],'fixed_rate':1,'caption_duplicate':False,'scene_at_64_seconds':'Séparer les quatre dossiers professionnels','javascript_errors':errors},ensure_ascii=False,indent=2))
finally:server.shutdown();case.tearDown()
