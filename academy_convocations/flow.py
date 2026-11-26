"""Lay out the course's existing paragraphs, tables, seals and access plans in format B."""

from functools import partial
from io import BytesIO
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Image, Paragraph, Spacer, Table, TableStyle
from .drawing import Book, BW, L, HAIR, INK, WHITE
from .source import Block, Cell
from . import accommodation, aps, letters


def icon_for(title):
    key = title.lower()
    for word, icon in [
        ("examen", "badge"),
        ("plan", "train"),
        ("centre de formation", "building"),
        ("parking", "parking"),
        ("modalit", "calendar"),
        ("calendrier", "calendar"),
        ("règles", "people"),
        ("hébergement", "bed"),
        ("formation", "building"),
        ("véhicule", "badge"),
    ]:
        if word in key:
            return icon
    return "paper"


def body_picture(pic):
    key = pic.description.lower()
    return not key or any(
        word in key
        for word in ["cachet", "signature", "trajet", "qr code", "photographie"]
    )


def par(text, book, size=11.3, font="Bar", color=INK, leading=1.25):
    value = escape(text).replace("\n", "<br/>")
    for caption, link in book.ref.links.items():
        if (
            caption
            and caption in text
            and link.startswith(("https://", "http://", "mailto:"))
        ):
            escaped = escape(caption)
            value = value.replace(
                escaped,
                '<link href="'
                + escape(link, {'"': "&quot;"})
                + '" color="'
                + book.accent
                + '"><u>'
                + escaped
                + "</u></link>",
                1,
            )
    if text == "[:AFs]":
        size, color = 1, WHITE
    return Paragraph(
        value,
        ParagraphStyle(
            "invitation",
            fontName=font,
            fontSize=size,
            leading=size * leading,
            textColor=colors.HexColor(color),
            spaceBefore=0,
            spaceAfter=0,
            splitLongWords=1,
            allowOrphans=1,
            allowWidows=1,
        ),
    )


def picture(pic, w, cap):
    scale = min(w / pic.width, cap / pic.height)
    return Image(
        BytesIO(pic.data),
        width=pic.width * scale,
        height=pic.height * scale,
        hAlign="LEFT",
    )


def elements(block, book, scale):
    rows = block.rows
    active = [
        i
        for i in range(max(map(len, rows)))
        if any(
            i < len(row)
            and (row[i].paragraphs or any(body_picture(p) for p in row[i].pictures))
            for row in rows
        )
    ]
    if not active:
        return []
    gap = 4 * scale
    stamps = [pic for pic in block.pictures if body_picture(pic)]
    if stamps and any("irecteur" in line for line in block.text):
        if len(stamps) == 1 and book.ref.venue_stamp:
            stamps.append(book.ref.venue_stamp)
        writer = [
            par(line, book, 11.8 * scale, "BarB" if i == 0 else "Bar")
            for i, line in enumerate(block.text)
        ]
        images = [picture(stamps[0], 77, 44)]
        if len(stamps) > 1:
            images.append(picture(stamps[1], 137, 49))
        signature = Table(
            [[writer] + [""] * (len(images) - 1), images],
            colWidths=[90, BW - 90] if len(images) > 1 else [BW],
            hAlign="LEFT",
        )
        signature.setStyle(
            TableStyle(
                [
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("SPAN", (0, 0), (-1, 0)),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
                    ("VALIGN", (0, 1), (-1, -1), "MIDDLE"),
                ]
            )
        )
        return [signature]
    if len(rows) == 1 and len(active) == 1:
        cell = rows[0][active[0]]
        result = []
        for i, s in enumerate(cell.paragraphs):
            short = len(s) < 72 and not s.endswith((".", ",", ":"))
            accented = s.isupper() and len(s) < 73
            size = 13.2 if short else 11.35
            result.extend(
                [
                    par(
                        s,
                        book,
                        size * scale,
                        "BarB" if short or accented else "Bar",
                        book.accent if accented else INK,
                    ),
                    Spacer(1, gap),
                ]
            )
        for pic in cell.pictures:
            if body_picture(pic):
                result.append(picture(pic, BW - 8, 310 * scale))
        return result
    nr, nc = len(rows), len(active)
    widths = [BW / nc] * nc
    if nr > 1 and nc == 3:
        widths = [137, 155, BW - 292]
    if nr > 1 and nc == 4:
        widths = [147, 123, 83, BW - 353]
    data = []
    for j, row in enumerate(rows):
        cells = []
        for col, idx in enumerate(active):
            cell = row[idx] if idx < len(row) else Cell([], [])
            content = []
            for k, s in enumerate(cell.paragraphs):
                title = (
                    k == 0 and nr == 1 and len(cell.paragraphs) > 1 and len(s) < 70
                ) or (j == 0 and nr > 1)
                content.append(
                    par(
                        s,
                        book,
                        (10.2 if title else 11.1) * scale,
                        "BarB" if title else "Bar",
                        book.accent if title else INK,
                        1.2,
                    )
                )
                if k + 1 < len(cell.paragraphs):
                    content.append(Spacer(1, 2 * scale))
            pics = [p for p in cell.pictures if body_picture(p)]
            if len(pics) > 1 and all(p.width > p.height for p in pics):
                stampw = widths[col] - 13
                fractions = [
                    stampw * (0.3 if i == 0 else 0.7 / max(1, len(pics) - 1))
                    for i in range(len(pics))
                ]
                inner = Table(
                    [[picture(pic, wi - 5, 43) for pic, wi in zip(pics, fractions)]],
                    colWidths=fractions,
                )
                inner.setStyle(
                    TableStyle(
                        [
                            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                            ("LEFTPADDING", (0, 0), (-1, -1), 0),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                        ]
                    )
                )
                content.append(inner)
            else:
                content.extend(
                    picture(pic, widths[col] - 13, 125 * scale) for pic in pics
                )
            cells.append(content or "")
        data.append(cells)
    tab = Table(
        data,
        colWidths=widths,
        repeatRows=1 if nr > 1 else 0,
        hAlign="LEFT",
        splitByRow=1,
        splitInRow=1,
    )
    rules = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6 * scale),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6 * scale),
        ("TOPPADDING", (0, 0), (-1, -1), 4 * scale),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4 * scale),
    ]
    if nr > 1:
        rules += [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(book.light)),
            ("LINEBELOW", (0, 0), (-1, -1), 0.45, colors.HexColor(HAIR)),
        ]
    elif not block.pictures or not any(body_picture(p) for p in block.pictures):
        rules.append(("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(book.light)))
    tab.setStyle(TableStyle(rules))
    return [tab]


def height(flow):
    return sum(x.wrap(BW, 10000)[1] for x in flow)


def form_flow(blocks, book, scale):
    story = []
    for block in blocks:
        values = elements(block, book, scale)
        if values:
            story.extend([*values, Spacer(1, 6 * scale)])
    return story


def paginate(story, available):
    pages = []
    current = []
    used = 0
    queue = list(story)
    while queue:
        item = queue.pop(0)
        _, h = item.wrap(BW, 10000)
        if used + h <= available + 0.02:
            current.append(item)
            used += h
            continue
        if isinstance(item, Spacer):
            continue
        if current:
            pages.append(current)
            current = []
            used = 0
            queue.insert(0, item)
            continue
        parts = item.split(BW, available)
        if len(parts) < 2:
            raise ValueError("Le bloc de la convocation dépasse la page")
        pages.append([parts[0]])
        queue[:0] = parts[1:]
    if current:
        pages.append(current)
    return pages


def interior(section, book):
    items = [text for block in section for text in block.text]
    designs = {
        "règles de vie en formation": aps.rules,
        "documents administratifs": aps.documents,
        "hébergement sur place": accommodation.stay,
        "règles à respecter": accommodation.house_rules,
        "services sur place & à proximité": accommodation.services,
        "à prévoir pour votre formation": accommodation.packing,
    }
    if len(items) >= 2 and (design := designs.get(items[1].casefold())):
        return [partial(design, items=items)]
    titleblock = section[0]
    if len(titleblock.text) == 1 and len(section) > 1 and len(section[1].text) == 1:
        # Some models keep their kicker and title in two separate Word paragraphs.
        titleblock = Block([[Cell(titleblock.text + section[1].text, [])]])
        section = [titleblock, *section[2:]]
    titles = titleblock.text[:2]
    if not titles:
        titles = [""]
    if len(titles) == 1:
        titles = ["", titles[0]]
    blocks = section[1:]
    remainder = titleblock.text[len([x for x in titles if x]) :]
    if remainder:
        blocks = [Block([[Cell(remainder, [])]]), *blocks]
    if "convocation officielle" in titles[1].casefold():
        signed = letters.plan(book, titles, blocks)
        if signed:
            return [signed]
    for scale in (1.05, 1, 0.94, 0.88, 0.82):
        flow = form_flow(blocks, book, scale)
        if height(flow) <= 489:
            break
    return [
        partial(draw_flow, titles=titles, story=page)
        for page in (paginate(flow, 489) or [[]])
    ]


def draw_flow(p, titles, story):
    p.begin(items=titles, outline=titles[-1] or "Convocation")
    p.side(icon_for(titles[-1]))
    draw_story(p, story, 29)
    p.finish()


def draw_story(p, story, top):
    for item in story:
        _, h = item.wrap(BW, 10000)
        item.drawOn(p.c, L, p.H - top - h)
        top += h


def fitted(p, x, y, w, h, text, font, size, color):
    while size > 8 and par(text, p, size, font, color).wrap(w, 10000)[1] > h:
        size -= 0.5
    flow = par(text, p, size, font, color, 1.14)
    _, ht = flow.wrap(w, 10000)
    flow.drawOn(p.c, x, p.H - y - ht)


def cover(p, blocks, calendar_number=None):
    p.begin(True, items=[], outline="Convocation")
    hero = blocks[0].text
    if len(hero) < 3:
        return False
    values = [
        (34, 104, 358, 26, hero[0], "BarB", 10, p.bright),
        (30, 133, 363, 54, hero[1], "Cond", 52, WHITE),
        (30, 190, 363, 77, hero[2], "Cond", 59, p.bright),
    ]
    if len(hero) > 3:
        values.append((34, 268, 359, 44, "\n".join(hero[3:]), "Bar", 15.5, WHITE))
    for args in values:
        fitted(p, *args)
    text = [b.text for b in blocks[1:] if b.text]
    if len(text) >= 2:
        fitted(p, 34, 313, 360, 13, " ".join(text[0]), "BarB", 9.5, p.bright)
        fitted(p, 34, 329, 365, 26, " ".join(text[1]), "BarB", 15.5, WHITE)
    groups = []
    for block in blocks[3:]:
        for row in block.rows:
            groups.extend(c.paragraphs for c in row if c.paragraphs)
    # Icon and text are sometimes in separate cells; keep each original label with its value.
    linked = next(
        (i for i, g in enumerate(groups) if any(p.ref.portal in s for s in g)),
        len(groups),
    )
    if (
        linked
        and linked < len(groups)
        and len(groups[linked]) == 1
        and len(groups[linked - 1]) == 1
    ):
        groups[linked - 1 : linked + 1] = [groups[linked - 1] + groups[linked]]
    practical = groups[-2:] if len(groups) > 2 else groups[-1:]
    top = groups[: -len(practical)] if practical else groups
    step = 310 / max(1, len(top))
    for i, group in enumerate(top):
        y = 30 + i * step
        icon = icon_for(group[0])
        if "formation" in group[0].lower() or "période" in group[0].lower():
            icon = "calendar"
        if "horaire" in group[0].lower():
            icon = "clock"
        p.icon(icon, 456, y + 1, 18, p.accent)
        fitted(p, 482, y, 326, 32, group[0], "BarB", 10.1, p.accent)
        if len(group) > 1:
            fitted(
                p, 456, y + 24, 352, step - 31, "\n".join(group[1:]), "Cond", 22, p.ink
            )
        if i < len(top) - 1:
            p.line(456, y + step - 12, 808, y + step - 12)
    p.line(34, 359, 808, 359)
    for i, group in enumerate(practical):
        x, w = (34, 445) if i == 0 else (536, 270)
        if i:
            p.line(512, 385, 512, 493)
        fitted(p, x, 387, w, 32, group[0], "BarB", 11.6, p.accent)
        if len(group) > 1:
            url_group = any(p.ref.portal in s for s in group)
            fitted(
                p,
                x,
                420,
                w,
                49,
                "\n".join(group[1:]),
                "BarB",
                10.6 if url_group else 14,
                p.ink,
            )
    if calendar_number:
        p.ref.agenda.cover(p, calendar_number)
    p.c.showPage()
    return True


def render(ref, out, family):
    p = Book(ref, out, family)
    standard = len(ref.blocks[0][0].text) >= 3 and len(ref.blocks[0]) >= 4
    sections = list(enumerate(ref.blocks))[int(standard) :]
    if ref.puget_parking:
        sections = sections[:-1]
    after_section = 2 if family == "desp" and standard else int(standard)
    before, after = [], []
    for i, section in sections:
        (before if i <= after_section else after).extend(interior(section, p))
    plans = before + after
    agenda_pages = ref.agenda.groups if ref.agenda else []
    p.total = len(plans) + int(standard) + len(agenda_pages) + int(ref.puget_parking)
    if standard:
        cover(p, ref.blocks[0], len(before) + 2 if agenda_pages else None)
    for index in range(len(plans) + 1):
        if index == len(before):
            for months in agenda_pages:
                ref.agenda.page(p, months, ref.course_label)
        if index == len(plans):
            break
        plans[index](p)
    if ref.puget_parking:
        from .aps import parking

        parking(p, ref.pages[-1])
    p.save()
