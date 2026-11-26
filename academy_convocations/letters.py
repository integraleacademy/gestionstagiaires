"""Use the APS letter's date and venue cards and signed footer across training courses."""

from functools import partial

from reportlab.platypus import Flowable, Spacer

from .aps import BLUE, MUTED, RULE, TEXT, WASH
from .drawing import BW, L, R


class Fields(Flowable):
    """A row of labelled fields with readable values and the course's pictograms."""

    def __init__(self, book, cells, scale):
        from .flow import par

        super().__init__()
        self.book = book
        self.width = BW
        self.cell_width = (BW - 10 * (len(cells) - 1)) / len(cells)
        self.parts = []
        self.height = 0
        for label, *values in cells:
            key = label.casefold()
            icon = "paper"
            if "lieu" in key:
                icon = "pin"
            elif "durée" in key or "horaires" in key and "date" not in key:
                icon = "clock"
            elif any(word in key for word in ("date", "début", "fin de formation")):
                icon = "calendar"
            elif "examen" in key or "épreuve" in key:
                icon = "badge"
            caption = par(label, book, 10.5 * scale, "BarB", book.accent)
            value = par("\n".join(values), book, 14 * scale, "Cond", TEXT, 1.12)
            ch = caption.wrap(self.cell_width - 43, 10000)[1]
            vh = value.wrap(self.cell_width - 24, 10000)[1]
            self.parts.append((icon, caption, value, ch, vh))
            self.height = max(self.height, 10 + ch + 5 + vh + 9)

    def draw(self):
        p = self.book
        top = p.H - self.height  # drawOn translated the canvas origin to this row
        wash = WASH if p.accent == BLUE else p.light
        for i, (icon, caption, value, ch, vh) in enumerate(self.parts):
            x = i * (self.cell_width + 10)
            p.rect(x, top, self.cell_width, self.height, wash)
            p.icon(icon, x + 10, top + 8, 17, p.accent)
            caption.drawOn(self.canv, x + 35, self.height - 9 - ch)
            value.drawOn(self.canv, x + 12, self.height - 15 - ch - vh)


def body(book, blocks, scale, exam):
    from .flow import elements, par

    story = []
    pending = []

    def flush():
        if pending:
            story.extend([Fields(book, pending, scale), Spacer(1, 6 * scale)])
            pending.clear()

    first_letters = [b.text[0] if b.text else "" for b in blocks]
    recipient = int(exam and len(blocks) > 1 and not first_letters[1].endswith(","))
    for i, b in enumerate(blocks):
        row = [c.paragraphs for c in b.rows[0] if c.paragraphs]
        if len(b.rows) == 1 and row and all(len(c) >= 2 for c in row):
            if len(row) == 2:
                flush()
                story.extend([Fields(book, row, scale), Spacer(1, 6 * scale)])
                continue
            if len(row) == 1 and row[0][0] in ("Lieu de formation", "Date de l’examen"):
                pending.extend(row)
                if len(pending) == 2:
                    flush()
                continue
        flush()
        if len(b.text) != 1 or len(b.rows) > 1:
            story.extend(elements(b, book, scale))
            story.append(Spacer(1, 6 * scale))
            continue
        line = b.text[0]
        # Exam letters put the qualification first, followed by the personal address.
        if i == recipient:
            name, *address = line.splitlines()
            story.append(par(name, book, 23 * scale, "Cond", TEXT, 1.1))
            if address:
                story.append(par("\n".join(address), book, 10.5 * scale, "Bar", MUTED))
        elif line == "[:AFs]":
            story.append(par(line, book))
            continue
        elif (exam and i == 0) or line.startswith("Tenue "):
            story.append(par(line, book, 12 * scale, "BarB", book.accent))
        elif i > 0 and first_letters[i - 1].endswith("inscription en formation :"):
            story.append(par(line, book, 19 * scale, "Cond", TEXT, 1.12))
        else:
            story.append(
                par(
                    line,
                    book,
                    11.6 * scale,
                    "BarB" if line.endswith(",") and i < 3 else "Bar",
                    TEXT,
                    1.23,
                )
            )
        story.append(Spacer(1, 6 * scale))
    flush()
    return story


def plan(book, titles, blocks):
    """Preflight the signed letter so unusual personal fields can still paginate."""
    from .flow import height

    if (
        not blocks
        or not blocks[-1].pictures
        or not any("Directeur général" in s for s in blocks[-1].text)
    ):
        return None
    signature = blocks[-1]
    body_blocks = blocks[:-1]
    date = ""
    if body_blocks and body_blocks[-1].text[0].startswith("Fait à "):
        date = body_blocks[-1].text[0]
        body_blocks = body_blocks[:-1]
    exam = "examen" in titles[1].casefold()
    for scale in (1, 0.96, 0.92, 0.88, 0.84):
        story = body(book, body_blocks, scale, exam)
        if height(story) <= 398:
            return partial(
                draw,
                titles=titles,
                story=story,
                signature=signature,
                date=date,
                exam=exam,
            )
    return None


def draw(p, titles, story, signature, date, exam):
    from .flow import draw_story

    p.begin(items=titles, outline=titles[1])
    p.side("badge" if exam else "building")
    draw_story(p, story, 19)
    p.line(L, 423, R, 423, RULE)
    y = 433
    if date:
        p.paragraph(L, y, BW, date, "Bar", 10.3, MUTED)
        y += 19
    for i, line in enumerate(signature.text):
        y = (
            p.paragraph(
                L,
                y,
                BW,
                line,
                "BarB" if i == 0 else "Bar",
                13 if i == 0 else 10.8,
                TEXT,
            )
            + 4
        )
    pics = list(signature.pictures)
    if len(pics) == 1 and p.ref.venue_stamp:
        pics.append(p.ref.venue_stamp)
    for x, width, pic in zip((L, L + 92), (77, 137), pics):
        p.bitmap(pic, x, y + 1, width)
    p.finish()
