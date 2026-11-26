"""Approved DESP Paris layout. Every printed paragraph comes from its personalized source."""

from .drawing import (
    Book,
    BW,
    CREAM,
    EMPH,
    INK,
    L,
    MUTED,
    ORANGE,
    R,
    WHITE,
    LayoutDoesNotFit,
    split_lines,
)


def cover_left(p):
    p.emit(0, 34, 106, 350, "BarB", 10, EMPH)
    p.emit(1, 30, 135, 368, "Cond", 57, WHITE)
    p.emit(2, 30, 187, 365, "Cond", 66, EMPH)
    p.emit(3, 34, 267, 360, "Bar", 16, WHITE, 19)
    p.emit(4, 34, 306, 350, "BarB", 9.3, EMPH)
    p.emit(5, 34, 321, 360, "BarB", 15.5, WHITE)


def recipient(p, i, top=32):
    if i != p.next:
        raise LayoutDoesNotFit("Coordonnées du destinataire personnalisées")
    parts = p.items[i].splitlines()
    if len(parts) > 2:
        raise LayoutDoesNotFit("Adresse longue")
    parts = (parts + ["", ""])[:2]
    if any(
        len(split_lines(value, font, size, BW)) > 1
        for value, font, size in [(parts[0], "Cond", 22), (parts[1], "Bar", 10.6)]
    ):
        raise LayoutDoesNotFit("Coordonnées sur plusieurs lignes")
    p.next += 1
    p.paragraph(L, top, BW, parts[0], "Cond", 22, INK)
    p.paragraph(L, top + 32, BW, parts[1], "Bar", 10.6, MUTED)


def authority(p, first, y):
    p.emit(first, L, y, BW - 225, "Bar", 10.2, MUTED)
    p.emit(first + 1, L, y + 20, BW - 225, "BarB", 12.5)
    p.emit(first + 2, L, y + 38, BW - 225, "Bar", 10, INK)
    p.signature(R - 201, y - 1, 135)


def cover(p):
    p.begin(True)
    if len(p.items) < 6 or len(split_lines(p.items[5], "BarB", 15.5, 360)) > 1:
        raise LayoutDoesNotFit("Nom sur plusieurs lignes")
    cover_left(p)
    x = 456
    for label, value, y, size in [
        (6, 7, 32, 23.5),
        (8, 9, 111, 21.6),
        (10, 11, 219, 17.9),
    ]:
        p.emit(label, x, y, 351, "BarB", 9.8, ORANGE)
        p.emit(value, x, y + 18, 351, "Cond", size, INK, size * 1.13)
        if label != 10:
            pos = y + (61 if label == 6 else 90)
            p.line(x, pos, 808, pos)
    p.emit(12, x, 299, 352, "Bar", 10.6, MUTED, 13.6)
    p.link(x, 235, 348, 98, "#p7")
    p.line(34, 359, 808, 359)
    p.emit(13, 34, 386, 439, "BarB", 10, ORANGE)
    p.emit(14, 34, 412, 455, "BarB", 15.2)
    p.line(515, 385, 515, 480)
    p.emit(15, 539, 388, 268, "BarB", 14.6)
    p.printed_link(16, 539, 416, 268, p.ref.portal, 10.4)
    p.finish()


def columns(p, first, top, headings, w):
    pos = L + 9
    for i, width in enumerate(w):
        p.emit(
            first + i,
            pos,
            top,
            width - 15,
            "BarB" if headings else "Bar",
            10 if headings else 11.3,
            ORANGE if headings else INK,
            13.3,
        )
        pos += width


def letter(p):
    p.begin()
    p.side("paper")
    recipient(p, 2, 25)
    p.line(L, 85, R, 85)
    p.emit(3, L, 96, BW, "BarB", 12.3)
    p.emit(4, L, 120, BW, "Bar", 12)
    p.emit(5, L, 150, BW, "Cond", 23)
    p.emit(6, L, 187, BW, "BarB", 12.4)
    p.emit(7, L, 212, BW, "Bar", 11.4, INK, 14.6)
    p.rect(L, 261, BW, 83, CREAM)
    widths = [158, 137, 83, 217]
    columns(p, 8, 270, True, widths)
    columns(p, 12, 292, False, widths)
    p.emit(16, L, 367, BW, "Bar", 11.4, INK, 14.7)
    p.emit(17, L, 411, BW, "Bar", 11.4, INK, 14.7)
    authority(p, 18, 465)
    p.finish()


def calendar(p):
    p.begin()
    p.side("calendar")
    p.emit(2, L, 17, BW, "Cond", 24)
    p.emit(3, L, 54, BW, "Bar", 11.1, INK, 13.6)
    for i in range(3):
        x = L + 198 * i
        if i:
            p.line(x - 8, 96, x - 8, 148)
        p.emit(4 + i * 2, x, 91, 184, "Cond", 26, ORANGE)
        p.emit(5 + i * 2, x, 123, 184, "BarB", 9.8, INK, 11.1)
    p.line(L, 157, R, 157)
    p.emit(10, L, 166, BW, "BarB", 14.2)
    p.emit(11, L, 189, BW, "Bar", 10.9, INK, 13.2)
    p.rect(L, 230, BW, 46, CREAM)
    p.emit(12, L + 9, 237, BW - 19, "BarB", 10.9, INK, 13)
    p.emit(13, L, 289, BW, "Cond", 20.4)
    col = [(L + 3, 132), (L + 147, 157), (L + 314, 279)]
    for i, (x, w) in enumerate(col):
        p.emit(14 + i, x, 323, w, "BarB", 9.6, ORANGE)
    for j, (top, bottom) in enumerate([(344, 378), (387, 418), (426, 469), (478, 498)]):
        for i, (x, w) in enumerate(col):
            p.emit(
                17 + j * 3 + i, x, top, w, "BarB" if i == 0 else "Bar", 10.2, INK, 11
            )
        if j != 3:
            p.line(L, bottom + 2, R, bottom + 2)
    p.emit(29, L, 508, BW, "BarB", 10.1, ORANGE, 11.8)
    p.finish()


def exam(p):
    p.begin()
    p.side("badge")
    p.emit(2, L, 22, BW, "Cond", 21.2)
    recipient(p, 3, 65)
    p.line(L, 124, R, 124)
    p.emit(4, L, 138, BW, "BarB", 12.3)
    p.emit(5, L, 163, BW, "Bar", 12, INK, 15)
    p.rect(L, 217, BW, 83, CREAM)
    widths = [147, 118, 97, 233]
    columns(p, 6, 228, True, widths)
    columns(p, 10, 250, False, widths)
    p.emit(14, L, 323, BW, "BarB", 14.7, ORANGE)
    p.emit(15, L, 349, BW, "Bar", 11.6, INK, 14.7)
    p.emit(16, L, 401, BW, "Bar", 11.6, INK, 14.7)
    authority(p, 17, 461)
    p.finish()


def admin(p):
    p.begin()
    p.side("paper")
    p.emit(2, L, 24, BW, "Cond", 21.9)
    p.emit(3, L, 65, BW, "Bar", 11.4, INK, 14.4)
    p.printed_link(4, L, 99, BW, p.ref.portal, 11.7)
    p.emit(5, L, 132, BW, "Bar", 11.2, INK, 14.3)
    p.rect(L, 203, BW, 82, CREAM)
    p.emit(6, L + 12, 212, BW - 25, "BarB", 12.4, ORANGE, 15.1)
    p.emit(7, L + 12, 248, BW - 25, "Bar", 11.1, INK, 14.1)
    p.emit(8, L, 298, BW, "Bar", 11.2, INK, 14.2)
    p.emit(9, L, 354, BW, "Bar", 11.2, INK, 14.2)
    p.rect(L, 414, BW, 105, INK)
    p.emit(10, L + 12, 422, BW - 24, "BarB", 11.1, EMPH, 14)
    p.emit(11, L + 12, 460, BW - 24, "Bar", 11, WHITE, 13.6)
    p.finish()


def rules(p):
    p.begin()
    p.side("people")
    p.emit(2, L, 22, BW, "Cond", 24.1)
    p.emit(3, L, 61, BW, "Bar", 11.3, INK, 14.5)
    for i, ic in enumerate(["people", "badge", "paper"]):
        x = L + i * 201
        w = 187
        p.line(x, 135, x + w, 135, ORANGE)
        p.icon(ic, x, 147, 19)
        p.emit(4 + i * 2, x, 174, w, "BarB", 10.4, ORANGE)
        p.emit(5 + i * 2, x, 198, w, "Bar", 10.9, INK, 14.1)
    p.emit(10, L, 321, BW, "Cond", 20.8)
    for i in range(4):
        p.emit(11 + i, L, 355 + i * 19.2, BW, "Bar", 11, INK, 14)
    p.rect(L, 445, BW, 68, INK)
    p.emit(15, L + 12, 456, BW - 24, "BarB", 11.1, WHITE, 14.2)
    p.finish()


def access(p):
    p.begin()
    p.side("train")
    p.emit(2, L, 25, BW, "Cond", 26.7)
    p.emit(3, L, 66, BW, "BarB", 13.3, ORANGE)
    p.img("plan-paris.png", L, 106, 357)
    x = L + 375
    w = R - x
    p.emit(4, x, 108, w, "Cond", 19, INK, 21)
    p.emit(5, x, 160, w, "BarB", 11.1, INK, 14.2)
    p.emit(6, x, 213, w, "Bar", 11.1, INK, 14.2)
    p.line(L, 311, R, 311)
    p.emit(7, L, 329, 347, "Cond", 18.8)
    for i, y in enumerate([363, 402, 428, 455]):
        p.emit(8 + i, L, y, 355, "Bar", 10.7, INK, 13.3)
    p.line(x - 11, 330, x - 11, 508)
    p.qr(x, 331, 61)
    p.emit(12, x, 399, w, "BarB", 13.3)
    p.printed_link(13, x, 425, w, p.ref.maps, 11.1)
    p.emit(14, x, 450, w, "Bar", 10.8, MUTED, 13.2)
    p.emit(15, L, 500, BW, "BarB", 10.8, ORANGE)
    p.finish()


def make(ref, out):
    p = Book(ref, out)
    for page in [cover, letter, calendar, exam, admin, rules, access]:
        page(p)
    p.save()
