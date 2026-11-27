"""Build a monthly calendar from the dates that apply to the individual invitation."""

from dataclasses import dataclass
from datetime import date

from training_days import is_aps_working_day

from . import aps_calendar as grid
from .drawing import BW, L, R

PERIOD = ("#E3E6F2", "#344560")
SST = ("#C9EBDD", "#19513F")
STYLES = {
    "remote": (grid.REMOTE, "laptop"),
    "centre": (grid.CENTRE, "building"),
    "period": (PERIOD, "calendar"),
    "sst": (SST, "people"),
    "exam": (grid.EXAM, "badge"),
    "opening": (("#FFE8AA", "#57421A"), "clock"),
}


def iso(value):
    value = str(value or "").strip()
    try:
        if "/" in value:
            day, month, year = value.split("/")
            return date(int(year), int(month), int(day)).isoformat()
        return date.fromisoformat(value).isoformat()
    except (ValueError, TypeError):
        return ""


def desp_periods(training, first, last):
    """Read each actual phase. A single known boundary can still appear on the cover."""
    remote_start = iso(training.get("dirigeant_remote_start"))
    remote_end = iso(training.get("dirigeant_remote_end"))
    centre_start = iso(training.get("dirigeant_in_person_start"))
    centre_end = iso(training.get("dirigeant_in_person_end"))
    remote = (remote_start or (iso(first) if remote_end else ""), remote_end)
    centre = (centre_start, centre_end or (iso(last) if centre_start else ""))
    return tuple(("", "") if a and b and a > b else (a, b) for a, b in (remote, centre))


def entries(training, trainee, context, slug):
    """The serialized rows also enter the cache key for existing trainee downloads."""
    rows = []

    def period(kind, label, start, end):
        a, b = iso(start), iso(end)
        if a and b and a <= b:
            rows.append(dict(kind=kind, label=label, start=a, end=b))

    def days(kind, label, dates, time=""):
        selected = sorted({d for v in dates if (d := iso(v))})
        if selected:
            rows.append(dict(kind=kind, label=label, days=selected, time=time or ""))

    first, last = context.get("date_debut_formation"), context.get("date_fin_formation")
    exam = context.get("date_examen")
    if slug == "vtc":
        if trainee.get("vtc_offer") != "practice":
            period(
                "remote",
                "Formation à distance",
                training.get("remote_start"),
                training.get("remote_end"),
            )
            days(
                "exam",
                "Examen théorique VTC",
                [
                    training.get("exam_theory_date")
                    or training.get("date_examen_theorique")
                ],
            )
        start, end = (
            context.get("heure_formation_pratique"),
            context.get("heure_fin_formation_pratique"),
        )
        times = " – ".join(t for t in (start, end) if t)
        if training.get("practice_training_date") or context.get(
            "mention_groupe_pratique"
        ):
            days(
                "centre",
                "Formation pratique VTC",
                [context.get("date_formation_pratique")],
                times,
            )
        days(
            "exam",
            "Examen pratique VTC",
            [
                trainee.get("vtc_practice_exam_date")
                or training.get("exam_practice_date")
                or training.get("date_examen_pratique")
            ],
        )
    elif slug.startswith("desp_"):
        remote, centre = desp_periods(training, first, last)
        period("remote", "Formation à distance", *remote)
        period("centre", "Au centre de formation", *centre)
        if not rows:
            period("period", "Période de formation", first, last)
        paris = slug == "desp_paris"
        days(
            "opening",
            "Lancement sur Zoom" if paris else "Accueil au centre",
            [context.get("date_ouverture")],
            context.get("heure_convocation") or ("09h00" if paris else "08h30"),
        )
        days("exam", "Examen DESP", [exam], context.get("heure_examen") or "08h00")
    elif slug == "afc":
        period("period", "Période individuelle AFC", first, last)
        days(
            "opening",
            "Accueil au centre",
            [context.get("date_convocation")],
            context.get("heure_convocation"),
        )
        days("exam", "Examen APS", [context.get("date_examen_aps")])
        days("exam", "Examen SSIAP 1", [context.get("date_examen_ssiap")])
    elif context.get("maintien_ssiap"):
        days("centre", context["parcours_label"], context["dates_parcours"].split(", "))
    elif slug == "ssiap":
        if context.get("periode_ssiap"):
            span = grid.numeric_dates(context["periode_ssiap"], 2)
            if span:
                period("centre", "Formation SSIAP", *span)
        else:
            period("centre", "Au centre de formation", first, last)
        if context.get("avec_sst"):
            days("sst", "Formation SST", context["dates_sst"].split(" et "))
        days("exam", "Examen SSIAP", [exam])
    else:
        label = "Période du parcours VAE" if slug == "vae" else "Période de formation"
        # For a date range alone the calendar shows the extent of the session;
        # it makes no claim about individual attendance, including for split A3P cohorts.
        period("period", label, first, last)
        days(
            "exam",
            "Jury VAE" if slug == "vae" else "Examen",
            [exam],
            "08h00" if slug == "a3p" else "",
        )
    # Cover, calendar and personalised letters draw from the same examinations.
    letters = context.get("convocations_examens")
    if letters is not None:
        rows = [r for r in rows if r["kind"] != "exam"]
        for letter in letters:
            label = letter["label"]
            if letter["kind"] == "jury":
                label = "Jury VAE"
            elif letter["kind"] != "cma":
                label = "Examen " + label
            days("exam", label, [letter["day"]], letter["time"])
    return rows


@dataclass(frozen=True)
class Event:
    kind: str
    label: str
    dates: tuple
    interval: bool
    time: str

    @classmethod
    def load(cls, item):
        interval = "start" in item
        values = [item["start"], item["end"]] if interval else item["days"]
        return cls(
            item["kind"],
            item["label"],
            tuple(date.fromisoformat(d) for d in values),
            interval,
            item.get("time", ""),
        )

    def includes(self, day):
        if not self.interval:
            return day in self.dates
        return self.dates[0] <= day <= self.dates[-1] and (
            self.kind != "centre" or is_aps_working_day(day)
        )

    def value(self):
        values = [d.strftime("%d/%m/%Y") for d in self.dates]
        if self.interval and values[0] != values[-1]:
            return "Du " + values[0] + " au " + values[-1]
        if len(values) > 3:
            return f"{len(values)} journées · du {values[0]} au {values[-1]}"
        text = " · ".join(dict.fromkeys(values))
        return text + (" · " + self.time if self.time else "")


class Agenda:
    def __init__(self, rows):
        self.events = [Event.load(e) for e in rows]
        self.opening = next(
            (e.dates[0] for e in self.events if e.kind == "opening"), None
        )
        self.groups = grid.month_groups([d for e in self.events for d in e.dates])

    def color(self, day):
        # An examination or a specifically booked appointment takes precedence over a period.
        events = sorted(self.events, key=lambda e: (e.kind != "exam", e.interval))
        for e in events:
            if e.kind != "opening" and e.includes(day):
                return STYLES[e.kind][0]
        return grid.OFF

    def cover(self, p, page_number):
        items = [e for e in self.events if e.kind != "opening"][:3]
        p.line(34, 473, R, 473, grid.LINE)
        if items:
            cell = 625 / len(items)
            for i, event in enumerate(items):
                x = 34 + i * cell
                p.icon(STYLES[event.kind][1], x, 486, 16, p.accent)
                p.paragraph(x + 23, 480, cell - 29, event.label, "BarB", 9.8, p.accent)
                value = event.value()
                p.paragraph(x + 23, 498, cell - 28, value, "Bar", 10.3, p.ink, 12)
        p.txt(673, 496, "Calendrier mensuel", "BarB", 12, p.accent)
        p.txt(673, 513, f"Voir page {page_number}", "Bar", 10.5, p.ink)
        p.link(667, 477, 140, 44, f"#p{page_number}")

    def page(self, p, months, family_name):
        title = grid.span_title(months)
        p.begin(
            items=[family_name, "Calendrier mensuel"],
            outline="Calendrier mensuel · " + title,
        )
        p.side("calendar")
        self.body(p, months)
        p.finish()

    def body(self, p, months):
        title = grid.span_title(months)
        p.txt(L, 45, title, "Cond", 29, grid.INK)
        half = (BW - 12) / 2
        count = min(2, len(self.events))
        for i, event in enumerate(self.events[:count]):
            x = L + i * (half + 12)
            w = BW if count == 1 else half
            (fill, ink), icon = STYLES[event.kind]
            grid.rounded(p, x, 62, w, 57, fill)
            p.icon(icon, x + 12, 78, 21, ink)
            if event.kind == "opening":
                grid.opening_mark(p, x + 2, 64, 9)
            p.paragraph(x + 43, 69, w - 51, event.label, "BarB", 11.2, ink)
            p.paragraph(x + 43, 88, w - 51, event.value(), "Bar", 11.2, ink, 12)
        grid.month_grids(p, months, self)
        p.line(L, 434, R, 434, grid.LINE)
        for i, event in enumerate(self.events[2:]):
            x = L + i % 2 * (half + 12)
            y = 443 + 30 * (i // 2)
            (fill, ink), icon = STYLES[event.kind]
            if event.kind == "opening":
                grid.opening_mark(p, x, y + 4, 11)
            else:
                grid.rounded(p, x, y + 1, 16, 15, fill, 2)
            p.paragraph(x + 22, y - 3, half - 24, event.label, "BarB", 10.5, grid.INK)
            p.paragraph(
                x + 22, y + 12, half - 24, event.value(), "Bar", 10.6, grid.MUTED
            )
        grid.rounded(p, L, 490, 12, 11, grid.OFF[0], 2)
        p.txt(L + 18, 500, "Autres jours", "Bar", 10.2, grid.MUTED)
        grid.holiday_mark(p, L + 117, 495, 3.5)
        p.txt(L + 128, 500, "Jour férié", "Bar", 10.2, grid.MUTED)
        p.txt(R - 147, 521, "Sous réserve de modifications.", "BarB", 10.3, grid.MUTED)
