"""A3P residential pages. All instructions are read from the trainee's Word model."""

from .aps import MUTED, NAVY, RULE, TEXT
from .drawing import BW, WHITE, L, R, split_lines


def begin(p, items, title, icon):
    p.begin(items=[items[0], title, *items[2:]], outline=title)
    p.side(icon)


def bunk(p, x, y, w, h):
    """An elevation of two stacked berths, drawn as line art at print resolution."""
    p.rect(x, y, w, h, "#EDF6EE")
    p.rect(x + 11, y + 11, w - 22, h - 22, None, "#D6E8D9", 0.6)
    bx, by = x + (w - 128) / 2, y + (h - 97) / 2
    for level in (19, 67):
        p.rect(bx + 5, by + level, 117, 9, "#FFFFFF", "#49785C", 1.1)
        p.rect(bx + 10, by + level - 5, 22, 5, "#BDD8C1", "#49785C", 0.9)
        p.line(bx + 37, by + level, bx + 37, by + level + 9, "#86A88F", 0.9)
        p.line(bx + 1, by + level + 30, bx + 1, by + level + 5, "#244F3B", 2.4)
    p.line(bx, by, bx, by + 91, "#244F3B", 3.1)
    p.line(bx + 124, by + 2, bx + 124, by + 91, "#244F3B", 3.1)
    p.line(bx, by + 5, bx + 89, by + 5, "#49785C", 1.5)
    p.line(bx + 89, by + 5, bx + 89, by + 19, "#49785C", 1.5)
    for side in (92, 111):
        p.line(bx + side, by + 28, bx + side, by + 91, "#49785C", 1.8)
    for step in (39, 51, 63, 75, 87):
        p.line(bx + 92, by + step, bx + 111, by + step, "#49785C", 1.5)
    p.line(bx - 8, by + 92, bx + 135, by + 92, "#B0C8B5", 1.1)


def labelled_row(p, y, icon):
    """A label and its original explanation, separated at the source punctuation."""
    original = p.items[p.next]
    label, sep, body = original.partition(" : ")
    p.icon(icon, L + 2, y + 6, 22, p.accent)
    if not sep:
        return p.emit(p.next, L + 39, y + 2, BW - 45, "Bar", 11.8, TEXT, 14.7)
    p.next += 1
    p.paragraph(L + 39, y, BW - 45, label + " :", "BarB", 12.4, p.accent)
    return p.paragraph(L + 39, y + 20, BW - 48, body, "Bar", 11.6, TEXT, 14.2)


def stay(p, items):
    begin(p, items, "Hébergement sur place", "bed")
    p.emit(2, L, 18, BW, "BarB", 12.6, TEXT)
    p.line(L, 49, R, 49, RULE)
    right = 178
    bunk(p, R - right, 62, right, 113)
    p.emit(3, L, 64, BW - right - 24, "Bar", 12.4, TEXT, 16.2)
    p.emit(4, L, 176, BW, "BarB", 11.8, TEXT, 15.4)
    for y, icon in [(225, "kitchen"), (285, "bag"), (345, "roll")]:
        p.line(L, y - 7, R, y - 7, RULE)
        labelled_row(p, y, icon)
    p.rect(L, 412, BW, 116, NAVY)
    p.icon("clean", L + 13, 432, 24, p.bright)
    end = p.emit(8, L + 52, 422, BW - 66, "BarB", 11.8, WHITE, 15)
    p.emit(9, L + 52, end + 10, BW - 66, "Bar", 11.6, WHITE, 14.6)
    p.finish()


def list_column(p, x, width, top, bottom, stop, icon, *, compact=False):
    """Fit each original list in its own column, reserving space before the next band."""
    p.line(x, top, x + width, top, RULE, 0.9)
    p.icon(icon, x, top + 12, 21 if compact else 24, p.accent)
    p.emit(
        p.next,
        x + 33,
        top + 15,
        width - 35,
        "BarB",
        11.6 if compact else 12.1,
        p.accent,
    )
    y = top + (41 if compact else 56)
    size, leading = (11.1, 13.2) if compact else (12.3, 15.6)
    while True:
        heights = [
            size + (len(split_lines(line, "Bar", size, width - 10)) - 1) * leading
            for line in p.items[p.next : stop]
        ]
        gap = min(
            17 if not compact else 7,
            (bottom - y - sum(heights)) / max(len(heights) - 1, 1),
        )
        if gap >= 3 or size <= 9.5:
            break
        size -= 0.25
        leading -= 0.3
    for idx in range(p.next, stop):
        y = p.emit(idx, x + 2, y, width - 10, "Bar", size, TEXT, leading) + gap


def group(p, label):
    return p.items.index(label, p.next)


def house_rules(p, items):
    begin(p, items, "Règles à respecter", "bed")
    p.emit(2, L, 26, BW, "Cond", 20.5, TEXT)
    col = (BW - 28) / 2
    list_column(p, L, col, 83, 384, group(p, "SÉCURITÉ & RESPECT"), "people")
    list_column(p, L + col + 28, col, 83, 384, len(items) - 2, "badge")
    p.rect(L, 403, BW, 125, NAVY)
    p.icon("people", L + 12, 422, 24, p.bright)
    y = p.emit(p.next, L + 52, 416, BW - 69, "BarB", 12.1, WHITE, 15.4)
    p.emit(p.next, L + 52, y + 13, BW - 69, "Bar", 11.6, WHITE, 14.7)
    p.finish()


def services(p, items):
    begin(p, items, "Services sur place & à proximité", "pin")
    p.emit(2, L, 21, BW, "Cond", 26, TEXT)
    col = (BW - 28) / 2
    list_column(p, L, col, 83, 340, group(p, "À MOINS DE 5 MINUTES"), "building")
    list_column(p, L + col + 28, col, 83, 340, len(items) - 2, "pin")
    p.line(L, 364, R, 364, RULE)
    p.emit(p.next, L, 384, BW - 18, "Bar", 12.1, MUTED, 15.3)
    p.rect(L, 444, BW, 84, NAVY)
    p.icon("bag", L + 13, 464, 24, p.bright)
    p.emit(p.next, L + 52, 458, BW - 70, "BarB", 12.1, WHITE, 15.4)
    p.finish()


def packing(p, items):
    begin(p, items, "À prévoir pour votre formation", "bag")
    p.emit(2, L, 15, BW, "BarB", 12.4, TEXT)
    col = (BW - 28) / 2
    list_column(p, L, col, 48, 329, group(p, "MISSIONS & EXAMEN"), "bag", compact=True)
    end = next(
        i
        for i in range(p.next, len(items))
        if items[i].startswith("Pour celles et ceux")
    )
    list_column(p, L + col + 28, col, 48, 329, end, "badge", compact=True)
    p.rect(L, 348, BW, 36, NAVY)
    p.icon("bed", L + 10, 356, 19, p.bright)
    p.emit(p.next, L + 41, 357, BW - 50, "BarB", 12.1, WHITE)
    list_column(p, L, col, 397, 524, group(p, "ENTRETIEN"), "bed", compact=True)
    list_column(p, L + col + 28, col, 397, 524, len(items), "clean", compact=True)
    p.finish()
