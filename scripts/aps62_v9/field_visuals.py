"""Readable demonstrations of source evidence, briefings and changing decisions."""
from PIL import ImageDraw, ImageFont
from scripts.render_aps62_v5 import FONT, TITLE_FONT

INK = '#173350'


def fit_text(draw, text, box, size=25, bold=False, color=INK):
    x, y, width, height = box
    for actual in range(size, 17, -1):
        font = ImageFont.truetype(str(TITLE_FONT if bold else FONT), actual)
        lines, line = [], ''
        for word in text.split():
            trial = (line+' '+word).strip()
            if line and font.getlength(trial) > width:
                lines.append(line)
                line = word
            else:
                line = trial
        if line:
            lines.append(line)
        spacing = actual*1.3
        if len(lines)*spacing <= height:
            for line in lines:
                draw.text((x, y), line, font=font, fill=color)
                y += spacing
            return y
    raise ValueError('Case visual overflows: '+text)


def card(draw, label, body, box, accent='#245bdc', fill='#e4ecfa', size=25):
    x, y, width, height = box
    draw.rounded_rectangle((x, y, x+width, y+height), 16, fill=fill)
    draw.rounded_rectangle((x, y, x+7, y+height), 3, fill=accent)
    fit_text(draw, label, (x+20, y+15, width-40, 38), 19, True, accent)
    fit_text(draw, body, (x+20, y+61, width-40, height-77), size)


def document(draw, text, box, valid):
    x, y, width, height = box
    accent = '#176b55' if valid else '#9b551f'
    draw.rounded_rectangle((x, y, x+width, y+height), 12, fill='white', outline='#b8c6d8', width=2)
    # A paper sheet, heading, source strip and highlighted excerpt make the
    # inspection tangible. The narration compares the exact authored fragments.
    draw.rectangle((x+22, y+22, x+45, y+52), fill='#dae4f1', outline=accent, width=2)
    fit_text(draw, 'CONSIGNE VÉRIFIÉE' if valid else 'DOCUMENT À EXAMINER',
             (x+65, y+25, width-83, 36), 20, True, accent)
    draw.line((x+22, y+78, x+width-22, y+78), fill='#dbe3ef', width=2)
    draw.rounded_rectangle((x+20, y+96, x+width-20, y+height-50), 7,
                          fill='#e5f2ed' if valid else '#fff0d3')
    fit_text(draw, text, (x+35, y+112, width-70, height-170), 27)
    fit_text(draw, 'Support fictif de mise en situation', (x+24, y+height-35, width-48, 25), 20,
             color='#536880')


def draw_field_scene(image, scene, phase=1.0):
    """Draw a demonstration; phase reveals evidence in narrative order."""
    draw = ImageDraw.Draw(image)
    kind = scene['kind']
    if kind == 'field_observation':
        # The observation sheet distinguishes the complete context from the
        # established fact. A magnifier tracks evidence rather than decoration.
        card(draw, 'LA SITUATION', scene['situation'], (48, 220, 754, 332), size=27)
        draw.ellipse((858, 220, 932, 294), fill='#e4ecfa', outline='#245bdc', width=5)
        draw.line((921, 282, 951, 310), fill='#245bdc', width=8)
        fit_text(draw, 'CE QUI EST ÉTABLI', (968, 239, 264, 48), 20, True)
        if phase >= .35:
            card(draw, 'LE FAIT À RETENIR', scene['fact'], (824, 321, 408, 231),
                 accent='#176b55', fill='#e5f2ed', size=24)
    elif kind == 'field_documents':
        document(draw, scene['unverified'], (48, 220, 570, 332), False)
        if phase >= .36:
            document(draw, scene['verified'], (662, 220, 570, 332), True)
            draw.polygon([(626, 369), (648, 386), (626, 403)], fill='#245bdc')
    elif kind == 'field_dialogue':
        for index, turn in enumerate(scene['dialogue']):
            if phase < (0, .3, .56)[index]:
                continue
            x = 48 if index != 1 else 192
            y = 211 + index*115
            accent = '#245bdc' if index != 1 else '#176b55'
            draw.rounded_rectangle((x, y, x+1040, y+105), 17,
                                  fill='#e4ecfa' if index != 1 else '#e5f2ed')
            fit_text(draw, turn['speaker'].upper(), (x+20, y+15, 240, 72), 21, True, accent)
            fit_text(draw, turn['text'], (x+271, y+15, 746, 83), 24)
            if scene['radio']:
                # Simple radio carrier indicator, no invented emergency signal.
                for k, bar in enumerate((9, 18, 28, 18, 9)):
                    draw.line((x+214+k*7, y+70-bar/2, x+214+k*7, y+70+bar/2),
                              fill=accent, width=3)
    elif kind == 'field_consequence':
        card(draw, 'OPTION À ÉCARTER', scene['wrong'], (48, 218, 570, 155),
             accent='#9b551f', fill='#fff0d3', size=24)
        if phase >= .3:
            card(draw, 'DÉCISION ADAPTÉE', scene['decision'], (662, 218, 570, 155),
                 accent='#176b55', fill='#e5f2ed', size=24)
        if phase >= .57:
            draw.line((333, 373, 333, 390), fill='#9b551f', width=3)
            draw.line((947, 373, 947, 390), fill='#176b55', width=3)
            card(draw, 'POURQUOI CE CHOIX CHANGE LA SITUATION', scene['reason'],
                 (48, 390, 1184, 162), size=24)
    elif kind == 'field_evolution':
        card(draw, '1 · LE NOUVEAU FAIT', scene['evolution'], (48, 220, 570, 182), size=25)
        if phase >= .3:
            card(draw, '2 · L’ACTION EST RÉÉVALUÉE', scene['decision'], (662, 220, 570, 182),
                 accent='#176b55', fill='#e5f2ed', size=25)
            draw.polygon([(626, 294), (649, 311), (626, 328)], fill='#245bdc')
        if phase >= .57:
            card(draw, '3 · LE RAISONNEMENT', scene['reason'], (48, 417, 1184, 135), size=24)
    else:
        raise ValueError(kind)
