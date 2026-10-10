"""Render the real templates against isolated synthetic test data, never a live account."""
import base64
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from tests.test_native_elearning_a3p import A3PWebTests
from PIL import Image, ImageOps, ImageDraw

root=Path('/tmp/a3p-ui')
root.mkdir(exist_ok=True)
fixture=A3PWebTests(methodName='test_catalog_and_all_lesson_pages_render_without_tracking')
fixture.setUp()
fixture._admin_login()
try:
    with sync_playwright() as p:
        browser=p.chromium.launch()
        for label,width,height in [('desktop',1440,1040),('mobile',390,844)]:
            page=browser.new_page(viewport={'width':width,'height':height},device_scale_factor=1)
            errors=[]
            page.on('pageerror',lambda error: errors.append(str(error)))
            def handle(route):
                parsed=urlsplit(route.request.url)
                if parsed.netloc!='a3p.test':
                    route.abort()
                    return
                target=parsed.path+('?' + parsed.query if parsed.query else '')
                data=route.request.post_data
                headers={k:v for k,v in route.request.headers.items() if k.lower() not in {'host','cookie','content-length'}}
                response=fixture.client.open(target,method=route.request.method,data=data,headers=headers)
                route.fulfill(status=response.status_code,headers={k:v for k,v in response.headers.items() if k.lower() not in {'set-cookie','content-length','content-encoding'}},body=response.data)
            page.route('**/*',handle)
            page.goto('http://a3p.test/admin/elearning/a3p')
            page.locator('#a3p-title').wait_for()
            page.screenshot(path=str(root/f'{label}-catalog.png'),full_page=False)
            assert page.locator('.a3p-module').count()==8
            assert page.locator('.a3p-module').first.locator('summary').is_visible()
            page.locator('.a3p-module').first.locator('summary').click()
            assert page.locator('.a3p-module').first.locator('.a3p-syllabus ol').is_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2'), label+' catalogue overflow'
            page.goto('http://a3p.test/admin/elearning/courses/academy-a3p-02/preview')
            page.locator('.a3p-reading').first.wait_for()
            page.screenshot(path=str(root/f'{label}-lesson.png'),full_page=False)
            assert page.locator('.a3p-reading').count()>=3
            assert page.locator('.a3p-nav-chapter[open]').count()==1
            assert 'Vérifier mes connaissances' not in page.locator('.native-course-nav').inner_text()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2'), label+' lesson overflow'
            page.goto('http://a3p.test/admin/elearning/courses/academy-a3p-06/preview?activity=a3p-06-cas')
            for step in page.locator('.a3p-decision-step').all():
                correct=step.get_attribute('data-answer')
                wrong=str((int(correct)+1)%3)
                step.locator('[data-choice="'+wrong+'"]').click()
                assert 'À reprendre' in step.locator('.a3p-decision-feedback').inner_text()
                step.locator('[data-choice="'+correct+'"]').click()
                step.locator('[data-next]').click()
            assert page.locator('.a3p-case-feedback h3').first.is_visible()
            page.screenshot(path=str(root/f'{label}-case.png'),full_page=False)
            page.goto('http://a3p.test/admin/elearning/courses/academy-a3p-02/preview?activity=a3p-02-01-quiz')
            for field in page.locator('select[data-group-id]').all():
                field.select_option(index=1)
            page.locator('#nativePreviewAnswerButton').click()
            page.wait_for_function("document.querySelector('#nativeAnswerFeedback').textContent.trim().length > 0")
            assert page.locator('#nativeAnswerFeedback').inner_text().strip()
            page.screenshot(path=str(root/f'{label}-quiz.png'),full_page=False)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2'), label+' quiz overflow'
            page.goto('http://a3p.test/admin/elearning/exams/a3p-final')
            page.wait_for_load_state('networkidle')
            page.screenshot(path=str(root/f'{label}-exam.png'),full_page=False)
            assert not errors, errors
            page.close()
        browser.close()
    # Small contact sheets in the job log make visual review possible even when
    # the connected client cannot download ZIP artifacts. No personal data.
    for label in ('desktop','mobile'):
        names=['catalog','lesson','case','quiz']
        tiles=[]
        for name in names:
            src=Image.open(root/f'{label}-{name}.png').convert('RGB')
            tile=ImageOps.contain(src,(720,520) if label=='desktop' else (390,844))
            tiles.append(tile)
        width=1440 if label=='desktop' else 780
        height=1080 if label=='desktop' else 1728
        sheet=Image.new('RGB',(width,height),'#dce6df')
        draw=ImageDraw.Draw(sheet)
        for i,(name,tile) in enumerate(zip(names,tiles)):
            x=(i%2)*(width//2);y=(i//2)*(height//2)
            draw.text((x+10,y+5),name,fill='#173b31')
            sheet.paste(tile,(x,y+20))
        path=root/f'{label}-review.jpg';sheet.save(path,quality=82)
        print('A3P_VISUAL_'+label.upper()+'='+base64.b64encode(path.read_bytes()).decode())
    print('A3P UI verified: desktop/mobile, syllabus, lesson, case, quiz and exam.')
finally:
    fixture.tearDown()
