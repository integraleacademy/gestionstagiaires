"""Editable-calendar geometry shared by DESP PowerPoints and session PDFs."""
import calendar
from datetime import date

import aps_kickoff as shared

BLUE, GREEN, GOLD = '#2251D9', '#087B68', '#E1B447'
NAVY, MUTED, PALE, BACKGROUND = '#14223D', '#556581', '#EDF2FA', '#FFFDF8'


def phase(day, dates):
    if day == dates['exam_date']:
        return 'exam'
    if dates['dirigeant_remote_start'] <= day <= dates['dirigeant_remote_end']:
        return 'remote'
    if dates['dirigeant_in_person_start'] <= day <= dates['dirigeant_in_person_end']:
        return 'onsite'
    return 'outside'


def layout(dates, city):
    """Return named native shapes in the source 1280 x 720 slide coordinates."""
    import pymupdf as fitz
    fonts = {bold: fitz.Font(fontfile=str(shared.ASSETS / ('Rubik-Bold.ttf' if bold else 'Rubik-Regular.ttf')))
             for bold in (False, True)}
    result = []

    def add(name, text, x, y, w, h, size=22, color=NAVY, bold=False,
            fill='none', align='left', middle=False, **extra):
        if text:
            size = min(size, (w-2)/max(fonts[bold].text_length(line, fontsize=1)
                                      for line in text.split('\n')))
        result.append(dict(name=name, text=text, x=x, y=y, width=w, height=h,
                           size=size, color=color, bold=bold, fill=fill,
                           align=align, middle=middle, **extra))

    start, exam = dates['dirigeant_remote_start'], dates['exam_date']
    end, onsite = dates['dirigeant_in_person_end'], dates['dirigeant_in_person_start']
    remote_end = dates['dirigeant_remote_end']
    add('calendar-title', 'Votre calendrier de formation', 58, 48, 1164, 66, 46, bold=True)
    add('calendar-range', 'Du '+shared.period(start, exam), 60, 126, 1154, 40, 22, MUTED)
    months = shared.months_between(start, exam)
    if len(months) <= 3:
        gap = 32
        width = (1160-gap*(len(months)-1))/len(months)
        for index, (year, month) in enumerate(months):
            left = 60+index*(width+gap)
            add(f'month-{year}-{month}', f'{shared.MONTHS[month].upper()} {year}',
                left, 188, width, 38, 28, bold=True)
            cw = width/7
            for col, label in enumerate(('Lun.', 'Mar.', 'Mer.', 'Jeu.', 'Ven.', 'Sam.', 'Dim.')):
                add(f'weekday-{year}-{month}-{col}', label, left+col*cw, 234,
                    cw-3, 32, min(19, cw*.33), '#FFFFFF', fill=NAVY, align='center', middle=True)
            for row, week in enumerate(calendar.Calendar(firstweekday=0).monthdayscalendar(year, month)):
                for col, number in enumerate(week):
                    if not number:
                        continue
                    day = date(year, month, number)
                    state = phase(day, dates)
                    fill = {'remote': BLUE, 'onsite': GREEN, 'exam': GOLD, 'outside': PALE}[state]
                    add('day-'+day.isoformat(), str(number), left+col*cw, 270+row*38,
                        cw-3, 35, min(25, cw*.47), '#FFFFFF' if state in ('remote', 'onsite') else NAVY,
                        bold=state == 'exam', fill=fill, align='center', middle=True,
                        day=day.isoformat(), phase=state)
    else:
        # Preserve readability for unusually long sessions rather than shrinking many month grids.
        total = max(1, (exam-start).days+1)
        for index, (label, first, last, color) in enumerate((
            ('Distanciel', start, remote_end, BLUE),
            ('Présentiel au centre de formation', onsite, end, GREEN),
            ('Examen', exam, exam, GOLD))):
            top = 196+index*100
            add(f'timeline-label-{index}', label+' : '+shared.period(first, last),
                60, top, 1160, 34, 25, color, True)
            add(f'timeline-track-{index}', '', 60, top+44, 1160, 24, fill=PALE)
            left = 60+1160*(first-start).days/total
            width = min(1220-left, max(8, 1160*((last-first).days+1)/total))
            add(f'timeline-bar-{index}', '', left, top+44, width, 24, fill=color)

    for index, (label, detail, first, last, color) in enumerate((
        ('Distanciel', '174 h en e-learning', start, remote_end, BLUE),
        ('Présentiel', '70 h au centre de formation', onsite, end, GREEN),
        ('Examen', city, exam, exam, '#A57411'))):
        left, width = 60+index*400, 360
        add(f'legend-title-{index}', label, left, 524, width, 32, 25, color, True)
        add(f'legend-dates-{index}', shared.period(first, last), left, 561, width, 31, 22, NAVY, True)
        add(f'legend-detail-{index}', detail, left, 596, width, 30, 21, MUTED)
    add('calendar-note', 'Les couleurs indiquent les périodes. Les jours et horaires de présence figurent sur votre convocation.',
        60, 642, 1160, 28, 18, MUTED)
    return result


def draw_pdf(page, dates, city):
    import pymupdf as fitz
    for item in layout(dates, city):
        x, y, w, h = (item[key]*.75 for key in ('x', 'y', 'width', 'height'))
        if item['fill'] != 'none':
            page.draw_rect(fitz.Rect(x, y, x+w, y+h), color=None, fill=shared._rgb(item['fill']))
        if not item['text']:
            continue
        size = item['size']*.75
        font = fitz.Font(fontfile=str(shared.ASSETS / ('Rubik-Bold.ttf' if item['bold'] else 'Rubik-Regular.ttf')))
        baseline = y+h/2+size*(font.ascender+font.descender)/2 if item['middle'] else y+size*font.ascender
        shared._text(page, item['text'], x, baseline, size, item['color'], item['bold'],
                     width=w if item['align'] == 'center' else None, align=item['align'])
