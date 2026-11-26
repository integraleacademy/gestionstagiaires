"""Render the monthly APS grids from the personalized timetable in the Word model."""

import calendar
from dataclasses import dataclass
from datetime import date, datetime
import re

from reportlab.lib.colors import HexColor
from reportlab.pdfbase.pdfmetrics import stringWidth
from training_days import french_public_holidays, is_aps_working_day

from .drawing import BW, L, R, WHITE

MONTHS = (
    "",
    "janvier",
    "février",
    "mars",
    "avril",
    "mai",
    "juin",
    "juillet",
    "août",
    "septembre",
    "octobre",
    "novembre",
    "décembre",
)
WEEKDAYS = ("Lu", "Ma", "Me", "Je", "Ve", "Sa", "Di")
REMOTE = ("#8C2D64", WHITE)
CENTRE = ("#D8EBF6", "#124A68")
EXAM = ("#14283F", WHITE)
OFF = ("#EFF1F3", "#526273")
INK = "#19283A"
MUTED = "#495B6D"
LINE = "#CFD9E3"
GOLD = "#FFD166"
RUST = "#A73B29"
DATE_FIELD = re.compile(r"\b\d{2}/\d{2}/\d{4}\b")


def numeric_dates(field, count):
    """Only place a phase on the grid when its original dates are complete and valid."""
    values = DATE_FIELD.findall(field)
    if len(values) != count:
        return ()
    try:
        parsed = tuple(datetime.strptime(value, "%d/%m/%Y").date() for value in values)
    except ValueError:
        return ()
    return parsed if parsed[0] <= parsed[-1] else ()


@dataclass(frozen=True)
class Schedule:
    remote: tuple[date, ...]
    centre: tuple[date, ...]
    opening: date | None
    exam: date | None

    @classmethod
    def from_page(cls, items):
        return cls(
            numeric_dates(items[3], 2),
            numeric_dates(items[5], 2),
            next(iter(numeric_dates(items[7], 1)), None),
            next(iter(numeric_dates(items[9], 1)), None),
        )

    def month_groups(self):
        dates = [d for d in (*self.remote, *self.centre, self.opening, self.exam) if d]
        return month_groups(dates)

    def color(self, day):
        if day == self.exam:
            return EXAM
        if (
            self.centre
            and self.centre[0] <= day <= self.centre[1]
            and is_aps_working_day(day)
        ):
            return CENTRE
        if self.remote and self.remote[0] <= day <= self.remote[1]:
            return REMOTE
        if day == self.opening:
            return CENTRE
        return OFF


def month_groups(dates):
    if not dates:
        return [[]]
    start, end = min(dates), max(dates)
    first = start.year * 12 + start.month - 1
    last = end.year * 12 + end.month - 1
    months = [(n // 12, n % 12 + 1) for n in range(first, last + 1)]
    return [months[i : i + 4] for i in range(0, len(months), 4)]


def rounded(p, x, y, width, height, fill, radius=4):
    canvas = p.c
    canvas.saveState()
    canvas.setFillColor(HexColor(fill))
    canvas.roundRect(x, p.H - y - height, width, height, radius, stroke=0, fill=1)
    canvas.restoreState()


def opening_mark(p, x, y, size):
    # The gold corner is independent from the background of the first e-learning day.
    c = p.c
    c.saveState()
    c.setFillColor(HexColor(GOLD))
    c.setStrokeColor(HexColor("#765314"))
    c.setLineWidth(0.65)
    path = c.beginPath()
    path.moveTo(x, p.H - y)
    path.lineTo(x + size, p.H - y)
    path.lineTo(x, p.H - y - size)
    path.close()
    c.drawPath(path, stroke=1, fill=1)
    c.restoreState()


def holiday_mark(p, x, y, r):
    c = p.c
    c.saveState()
    c.setFillColor(HexColor(RUST))
    c.setStrokeColor(HexColor(WHITE))
    c.setLineWidth(0.65)
    c.circle(x, p.H - y, r, stroke=1, fill=1)
    c.restoreState()


def centered(p, x, baseline, text, face, size, color):
    p.txt(x - stringWidth(text, face, size) / 2, baseline, text, face, size, color)


def grid(p, year, month, x, y, width, compact, schedule):
    label = f"{MONTHS[month].capitalize()} {year}"
    title_size = 17 if compact else 23
    p.txt(x, y + title_size, label, "Cond", title_size, INK)
    p.line(x, y + title_size + 8, x + width, y + title_size + 8, LINE)
    weekdays_y = y + title_size + (24 if compact else 29)
    top = weekdays_y + (5 if compact else 9)
    row_height = 15.2 if compact else 27
    col = width / 7
    for idx, label in enumerate(WEEKDAYS):
        centered(
            p,
            x + (idx + 0.5) * col,
            weekdays_y,
            label,
            "BarB",
            9.4 if compact else 10.9,
            MUTED,
        )
    weeks = calendar.Calendar(firstweekday=calendar.MONDAY).monthdayscalendar(
        year, month
    )
    for row, week in enumerate(weeks):
        for idx, number in enumerate(week):
            if not number:
                continue
            day = date(year, month, number)
            left = x + idx * col
            y_day = top + row * row_height
            fill, ink = schedule.color(day)
            gap = 2 if compact else 3
            height = row_height - gap
            rounded(
                p, left + 1, y_day, col - gap, height, fill, 2.2 if compact else 3.5
            )
            size = 10.4 if compact else 14
            centered(
                p,
                left + (col - gap) / 2 + 1,
                y_day + (height + size * 0.65) / 2,
                str(number),
                "BarB" if fill != OFF[0] else "Bar",
                size,
                ink,
            )
            if day == schedule.opening:
                opening_mark(p, left + 2, y_day + 1, 5.5 if compact else 8)
            if day in french_public_holidays(year):
                holiday_mark(
                    p, left + col - gap - 3, y_day + 3.8, 2.4 if compact else 3
                )


def span_title(months):
    if not months:
        return "Dates à confirmer"
    (year, first), (end_year, last) = months[0], months[-1]
    if len(months) == 1:
        return f"{MONTHS[first].capitalize()} {year}"
    left = (
        MONTHS[first].capitalize()
        if year == end_year
        else f"{MONTHS[first].capitalize()} {year}"
    )
    return f"{left} – {MONTHS[last]} {end_year}"


def page(p, schedule, months):
    title = span_title(months)
    p.begin(outline=f"Calendrier mensuel · {title}")
    p.side("calendar")
    p.txt(L, 45, title, "Cond", 29, INK)
    half = (BW - 12) / 2
    for index, x, (fill, ink), icon in [
        (2, L, REMOTE, "laptop"),
        (4, L + half + 12, CENTRE, "building"),
    ]:
        rounded(p, x, 63, half, 57, fill)
        p.icon(icon, x + 12, 78, 22, ink)
        p.emit(index, x + 46, 70, half - 55, "BarB", 11.2, ink)
        p.emit(index + 1, x + 46, 89, half - 55, "Bar", 12, ink)
    # Establish the same reading order in the PDF and the editable Word.
    p.line(L, 434, R, 434, LINE)
    opening_mark(p, L + 1, 453, 12)
    p.emit(6, L + 22, 445, half - 27, "BarB", 12, INK)
    p.emit(7, L + 22, 463, half - 27, "Bar", 11.3, MUTED)
    rounded(p, L + half + 13, 448, 14, 14, EXAM[0], 2)
    p.emit(8, L + half + 36, 445, half - 36, "BarB", 12, INK)
    p.emit(9, L + half + 36, 463, half - 36, "Bar", 11.3, MUTED)
    rounded(p, L, 490, 12, 11, OFF[0], 2)
    p.emit(10, L + 18, 488, 110, "BarB", 10.2, MUTED)
    holiday_mark(p, L + 128, 495, 3.5)
    p.emit(11, L + 138, 488, 98, "BarB", 10.2, MUTED)
    p.emit(12, L, 510, BW - 155, "Bar", 10.2, MUTED)
    p.emit(13, R - 144, 510, 144, "BarB", 10.2, MUTED)

    month_grids(p, months, schedule)
    p.finish()


def month_grids(p, months, schedule):
    columns = 2 if len(months) > 1 else 1
    gap = 17
    width = (BW - gap * (columns - 1)) / columns
    compact = len(months) > 2
    for i, (year, month) in enumerate(months):
        col, row = i % columns, i // columns
        y = (130 + 150 * row) if compact else 149
        grid(p, year, month, L + col * (width + gap), y, width, compact, schedule)
