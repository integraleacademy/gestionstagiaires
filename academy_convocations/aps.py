"""APS layout for the personalized Puget training invitation."""

from reportlab.pdfbase.pdfmetrics import stringWidth

from . import aps_calendar
from .drawing import Book, BW, L, R, WHITE, split_lines

TEXT = "#19283A"
MUTED = "#425469"
RULE = "#CDD8E2"
WASH = "#EEF4FB"
BLUE = "#1D4ED8"
NAVY = "#18283D"


def fitted(p, index, x, y, width, height, face, size, color=TEXT):
    """Fit personal names and dates inside their reserved area, including long words."""
    value = p.items[index]
    while size >= 7:
        lines = split_lines(value, face, size, width)
        if (len(lines) - 1) * size * 1.12 + size <= height and all(
            stringWidth(line, face, size) <= width for line in lines
        ):
            return p.emit(index, x, y, width, face, size, color, size * 1.12)
        size -= 0.5
    # Long unbroken words must wrap rather than spill over the column.
    from .flow import par

    flow = par(value, p, size, face, color, 1.12)
    _, used = flow.wrap(width, height)
    flow.drawOn(p.c, x, p.H - y - used)
    p.next += 1
    return y + used


def cover(p):
    p.begin(True)
    p.emit(0, 34, 101, 355, "BarB", 10, p.bright)
    p.emit(1, 29, 122, 370, "Cond", 59, WHITE)
    p.emit(2, 29, 178, 370, "Cond", 74, p.bright)
    p.emit(3, 34, 258, 368, "Bar", 16, WHITE)
    p.emit(4, 34, 283, 365, "Bar", 10.5, "#DAE8F8")
    p.emit(5, 34, 310, 353, "BarB", 9, p.bright)
    fitted(p, 6, 34, 325, 368, 30, "BarB", 16.3, WHITE)

    x = 455
    p.emit(7, x, 22, 340, "BarB", 9, BLUE)
    p.emit(8, x, 37, 350, "Bar", 11.4, MUTED)
    p.emit(9, x, 55, 305, "Cond", 31)
    p.icon("calendar", R - 26, 58, 24, BLUE)
    p.link(x, 52, R - x, 39, "#p4")
    p.line(x, 98, R, 98, "#BBCBE0", 0.9)
    for index, icon, y in [
        (10, "laptop", 113),
        (12, "building", 194),
        (14, "badge", 275),
    ]:
        p.icon(icon, x + 1, y + 10, 26, BLUE)
        p.emit(index, x + 44, y, 302, "BarB", 12, BLUE)
        fitted(p, index + 1, x + 44, y + 20, 304, 37, "Cond", 25)
        if index != 14:
            p.line(x, y + 66, R, y + 66, RULE)

    p.line(34, 359, R, 359, RULE)
    p.line(397, 389, 397, 483, RULE)
    p.icon("clock", 34, 386, 21, BLUE)
    p.emit(16, 65, 389, 314, "BarB", 10, BLUE)
    fitted(p, 17, 34, 413, 350, 37, "Cond", 27.5)
    p.emit(18, 34, 458, 350, "Bar", 12, MUTED)
    p.icon("pin", 427, 386, 21, BLUE)
    p.emit(19, 459, 389, 340, "BarB", 10, BLUE)
    p.emit(20, 427, 415, 372, "BarB", 15, TEXT, 19)
    p.emit(21, 34, 490, 340, "BarB", 10.5, MUTED)
    p.printed_link(22, 34, 506, 355, p.ref.portal, 10.6)
    p.printed_link(23, 427, 502, 376, f"#p{p.total}", 11.5)
    p.finish()


def name_and_city(p, idx, top):
    name, _, city = p.items[idx].partition("\n")
    p.items = list(p.items)
    p.items[idx] = name
    fitted(p, idx, L, top, BW, 30, "Cond", 24)
    p.paragraph(L, top + 31, BW, city, "Bar", 10, MUTED)


def field(p, label, x, y, width, height, count, icon, size=16):
    p.rect(x, y, width, height, WASH)
    p.icon(icon, x + 11, y + 10, 17, BLUE)
    p.emit(label, x + 36, y + 11, width - 43, "BarB", 10, BLUE)
    for n in range(count):
        top = y + 31 + n * 12
        fitted(
            p,
            label + 1 + n,
            x + 12,
            top,
            width - 23,
            height - (top - y) - 3,
            "Cond" if count == 1 else "BarB" if n == 0 else "Bar",
            size if count == 1 else 10.8,
        )


def sign(p, idx, y):
    p.line(L, y - 8, R, y - 8, RULE)
    p.emit(idx, L, y, BW, "Bar", 10.2, MUTED)
    p.emit(idx + 1, L, y + 19, BW, "BarB", 13, TEXT)
    p.emit(idx + 2, L, y + 37, BW, "Bar", 10.8, MUTED)
    signature, seal = p.ref.blocks[p.n - 1][-1].pictures
    p.bitmap(signature, L, y + 62, 57)
    p.bitmap(seal, L + 71, y + 56, 137)


def letters(p, exam=False):
    p.begin()
    p.side("badge" if exam else "building")
    half = (BW - 10) / 2
    if exam:
        p.emit(2, L, 18, BW, "BarB", 11.5, BLUE)
        name_and_city(p, 3, 39)
        fitted(p, 4, L, 88, BW, 18, "BarB", 11.5)
        p.emit(5, L, 109, BW, "Bar", 11.5, TEXT, 14)
        first, y, rows = 6, 151, 2
    else:
        name_and_city(p, 2, 17)
        fitted(p, 3, L, 64, BW, 17, "BarB", 11.5)
        p.emit(4, L, 83, BW, "Bar", 11.4)
        fitted(p, 5, L, 101, BW, 34, "Cond", 21)
        p.emit(6, L, 138, BW, "Bar", 11.6)
        p.emit(7, L, 159, BW, "Bar", 11.3)
        first, y, rows = 8, 186, 3

    field(p, first, L, y, half, 57, 1, "badge" if exam else "paper", 17.5)
    field(p, first + 2, L + half + 10, y, half, 57, 1, "calendar", 20)
    field(p, first + 4, L, y + 63, half, 71, 1, "clock", 18)
    field(p, first + 6, L + half + 10, y + 63, half, 71, rows, "pin")

    if exam:
        p.icon("shirt", L, 301, 21, BLUE)
        p.emit(15, L + 33, 302, BW - 33, "BarB", 13, TEXT)
        p.emit(16, L, 326, BW, "Bar", 11.3, TEXT, 14)
        p.emit(17, L, 374, BW, "Bar", 11, MUTED, 13.5)
        sign(p, 18, 420)
    else:
        p.emit(18, L, 320, BW, "Bar", 1, WHITE)
        p.emit(19, L, 331, BW, "Bar", 11.1, TEXT, 14.0)
        p.emit(20, L, 375, BW, "Bar", 11.0, MUTED, 13.5)
        sign(p, 21, 420)
    p.finish()


def schedule(p):
    p.begin()
    p.side("calendar")
    p.emit(2, L, 16, BW, "Cond", 26, TEXT)
    p.emit(3, L, 55, BW, "Bar", 11.3, TEXT, 14)
    for n, icon in enumerate(["laptop", "building", "clock"]):
        x = L + BW * n / 3
        if n:
            p.line(x - 7, 99, x - 7, 159, RULE)
        p.icon(icon, x, 110, 22, BLUE)
        p.emit(4 + n * 2, x + 31, 94, 150, "Cond", 28, BLUE)
        p.emit(5 + n * 2, x + 31, 129, 151, "BarB", 10.3, TEXT, 12)
    p.emit(10, L, 170, BW, "Cond", 20)
    p.emit(11, L, 199, BW, "Bar", 11.0, TEXT, 13.5)
    p.rect(L, 234, BW, 49, WASH)
    p.icon("laptop", L + 12, 249, 20, BLUE)
    p.emit(12, L + 47, 242, BW - 59, "BarB", 10.6, TEXT, 13)
    p.emit(13, L, 288, BW, "Cond", 21)
    p.printed_link(14, R - 166, 298, 166, "#p4", 10.4)
    p.rect(L, 319, BW, 24, WASH)
    cols = [(L + 31, 109), (L + 153, 164), (L + 327, 264)]
    for n, (x, w) in enumerate(cols):
        p.emit(15 + n, x, 325, w, "BarB", 9.8, BLUE)
    for n, icon in enumerate(["building", "laptop", "building", "badge"]):
        y = 349 + n * 38
        p.icon(icon, L + 4, y + 5, 17, BLUE)
        for k, (x, w) in enumerate(cols):
            fitted(p, 18 + n * 3 + k, x, y, w, 32, "BarB" if k == 0 else "Bar", 10.7)
        if n < 3:
            p.line(L, y + 33, R, y + 33, RULE)
    p.rect(L, 500, BW, 29, NAVY)
    p.emit(30, L + 11, 507, BW - 22, "BarB", 10.6, WHITE)
    p.finish()


def documents(p):
    p.begin()
    p.side("paper")
    p.emit(2, L, 27, BW, "Bar", 12, TEXT, 15)
    p.rect(L, 75, BW, 62, WASH)
    p.icon("paper", L + 14, 93, 24, BLUE)
    p.emit(3, L + 53, 82, BW - 65, "Cond", 18, TEXT)
    p.printed_link(4, L + 53, 109, BW - 65, p.ref.portal, 11.2)
    p.emit(5, L, 151, BW, "Bar", 11.5, TEXT, 14.4)
    p.rect(L, 219, BW, 79, NAVY)
    p.icon("clock", L + 12, 238, 25, p.bright)
    p.emit(6, L + 51, 228, BW - 63, "BarB", 12, WHITE, 14)
    p.emit(7, L + 51, 262, BW - 63, "Bar", 10.8, WHITE, 13)
    p.emit(8, L, 311, BW, "Bar", 11.3, TEXT, 14.2)
    p.icon("mail", L, 376, 22, BLUE)
    p.emit(9, L + 35, 364, BW - 35, "Bar", 11.4, TEXT, 14.2)
    p.rect(L, 417, BW, 112, WASH)
    p.emit(10, L + 14, 427, BW - 28, "BarB", 11.1, TEXT, 13.7)
    p.emit(11, L + 14, 469, BW - 28, "Bar", 10.9, TEXT, 13.4)
    p.finish()


def rules(p):
    p.begin()
    p.side("people")
    p.emit(2, L, 25, BW, "Bar", 12, TEXT, 14.8)
    col = (BW - 30) / 2
    for index, x, y, icon in [
        (3, L, 103, "people"),
        (5, L + col + 30, 103, "shirt"),
        (7, L, 243, "building"),
        (9, L + col + 30, 243, "list"),
    ]:
        p.line(x, y - 10, x + col, y - 10, RULE, 0.9)
        p.icon(icon, x, y, 19, BLUE)
        p.emit(index, x + 29, y + 1, col - 29, "BarB", 11.6, BLUE)
        if index == 9:
            next_y = y + 31
            for i in range(10, 14):
                next_y = p.emit(i, x, next_y, col, "Bar", 10.9, TEXT, 13.5) + 6
        else:
            p.emit(index + 1, x, y + 31, col, "Bar", 11.3, TEXT, 14.1)
    p.rect(L, 448, BW, 80, NAVY)
    p.emit(14, L + 14, 460, BW - 28, "BarB", 11.2, WHITE, 14.2)
    p.finish()


def parking(p):
    p.begin()
    p.side("parking")
    p.emit(2, L, 14, BW, "Cond", 27, TEXT)
    p.emit(3, L, 53, BW, "BarB", 12, TEXT)
    diagram = next(
        pic
        for b in p.ref.blocks[-1]
        for pic in b.pictures
        if pic.description.startswith("Schéma des parkings")
    )
    p.bitmap(diagram, L, 83, BW)
    p.rect(L, 83, BW, BW * diagram.height / diagram.width, None, "#C2CFD5")
    for n in range(5):
        p.rect(L + 1 + 4 * n, 367, 2.2, 2.2, "#3564AC")
    p.emit(4, L + 27, 360, 308, "BarB", 10, MUTED)
    p.emit(5, R - 188, 360, 188, "Bar", 10, MUTED)
    p.line(L, 387, R, 387, RULE)
    for i, (x, y, accent) in enumerate(
        [
            (L, 404, "#755008"),
            (L + 186, 404, "#985019"),
            (L, 463, "#12624F"),
            (L + 186, 463, "#A43B5A"),
        ]
    ):
        p.rect(x, y, 34, 26, accent)
        p.emit(6 + 2 * i, x + 6, y + 2.5, 26, "Cond", 16.5, WHITE)
        p.emit(7 + 2 * i, x + 44, y + 2, 139, "BarB", 12, TEXT, 14.3)
    p.line(L + 386, 401, L + 386, 516, RULE)
    p.qr(L + 402, 399, 62)
    p.printed_link(14, L + 402, 469, 186, p.ref.links[p.items[14]], 11)
    p.printed_link(15, L + 402, 496, 186, p.ref.maps, 11)
    p.finish()


def make(source, path):
    calendar_page = 3  # The visual calendar follows the detailed timetable.
    session = aps_calendar.Schedule.from_page(source.pages[calendar_page])
    groups = session.month_groups()
    # Long sessions may span several calendar pages, keeping the original letters intact.
    source.pages[calendar_page : calendar_page + 1] = [
        source.pages[calendar_page]
    ] * len(groups)
    source.blocks[calendar_page : calendar_page + 1] = [
        source.blocks[calendar_page]
    ] * len(groups)
    source.pages[0][-1] = f"Voir le plan des parkings en page {len(source.pages)}"
    p = Book(source, path, "aps")
    cover(p)
    letters(p)
    schedule(p)
    for months in groups:
        aps_calendar.page(p, session, months)
    letters(p, exam=True)
    documents(p)
    rules(p)
    parking(p)
    p.save()
