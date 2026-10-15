"""Real desktop/mobile previews and click workflows against synthetic account data."""
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from tests.test_native_elearning_a3p import A3PWebTests
from tests.shared_reader_fixtures import published_media_inventory
from elearning_native import a3p

root=Path('/tmp/a3p157-ui');root.mkdir(exist_ok=True)
fixture=A3PWebTests(methodName='runTest');fixture.setUp();fixture._admin_login()
course=a3p.load_bundled_course('academy-a3p-02')
film,lesson,workshop,quiz,recap=course['sections'][0]['activities']
try:
 with published_media_inventory(),sync_playwright() as p:
  browser=p.chromium.launch()
  for label,width,height in [('desktop',1440,1040),('mobile',390,844)]:
   page=browser.new_page(viewport={'width':width,'height':height},device_scale_factor=1)
   errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
   def handle(route):
    parsed=urlsplit(route.request.url)
    if parsed.netloc!='a3p.test':route.abort();return
    target=parsed.path+('?' +parsed.query if parsed.query else '')
    headers={k:v for k,v in route.request.headers.items() if k.lower() not in {'host','cookie','content-length'}}
    response=fixture.client.open(target,method=route.request.method,data=route.request.post_data,headers=headers)
    route.fulfill(status=response.status_code,headers={k:v for k,v in response.headers.items() if k.lower() not in {'set-cookie','content-length','content-encoding'}},body=response.data)
   page.route('**/*',handle)
   base='http://a3p.test/admin/elearning/courses/academy-a3p-02/preview?version='+a3p.VERSION+'&activity='
   page.goto('http://a3p.test/admin/elearning/a3p');page.locator('#a3p-title').wait_for()
   assert page.locator('.a3p-module').count()==8
   assert '168' in page.locator('.a3p-stats').inner_text()
   page.screenshot(path=str(root/f'{label}-catalog.png'))
   assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2')
   page.goto(base+film['id']);page.locator('video').wait_for()
   page.wait_for_function('document.querySelector("video").duration > 300')
   page.locator('video').evaluate('(v)=>{v.currentTime=98}')
   page.wait_for_timeout(700);page.screenshot(path=str(root/f'{label}-video.png'))
   page.goto(base+lesson['id'])
   page.locator('[data-aps-lesson-next]').click()
   page.locator('.a3p-reading').first.wait_for()
   page.screenshot(path=str(root/f'{label}-course.png'))
   assert page.locator('.a3p-nav-chapter[open]').count()==1
   assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2')
   page.goto(base+workshop['id']);page.locator('#apsPracticeForm').wait_for()
   assert page.locator('.aps-evidence').count()==4
   assert page.locator('textarea').count()==0
   for i,ex in enumerate(workshop['practice']['exercises']):
    field=page.locator('[data-exercise-id="'+ex['id']+'"]');field.wait_for(state='visible')
    if ex['kind']=='single':field.locator('input[value="'+ex['answer']+'"]').check()
    else:
     for row in ex['rows']:field.locator('[data-row-id="'+row['id']+'"]').select_option(row['answer'])
    page.locator('.aps-practice-check').click()
    page.wait_for_function('document.querySelector(".aps-practice-result").textContent.trim().length > 0')
    if i==0:page.screenshot(path=str(root/f'{label}-workshop.png'))
    if i+1<len(workshop['practice']['exercises']):
     page.locator('.aps-guided-next').wait_for(state='visible');page.locator('.aps-guided-next').click()
   assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2')
   page.goto(base+quiz['id'])
   for group in quiz['answer_groups']:
    page.locator('select[data-group-id="'+group['id']+'"]').select_option(next(o['id'] for o in group['answers'] if o['is_correct']))
   page.locator('#nativePreviewAnswerButton').click()
   page.wait_for_function('document.querySelector("#nativeAnswerFeedback").textContent.trim().length > 0')
   page.screenshot(path=str(root/f'{label}-quiz.png'))
   assert not errors,errors
   page.close()
  browser.close()
 print('A3P157 UI: video decoded, 4 documents, 6 guided steps, quiz, desktop/mobile, no JS errors or horizontal overflow.')
finally:fixture.tearDown()
