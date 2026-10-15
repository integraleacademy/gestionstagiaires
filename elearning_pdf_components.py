"""Small, vector PDF components for factual learning-duration reports."""
from __future__ import annotations

import math
import re

from reportlab.lib import colors
from reportlab.platypus import Flowable

INK = colors.HexColor("#19324B")
MUTED = colors.HexColor("#62768B")
BLUE = colors.HexColor("#248DCE")
TRACK = colors.HexColor("#E2ECF4")


def seconds_value(record, key, label_key):
    """Prefer recorded numbers; older demonstration fixtures only have labels."""
    value = record.get(key)
    if value is not None:
        try:
            number = float(value)
            return max(0.0, number) if math.isfinite(number) else None
        except (TypeError, ValueError):
            return None
    label = str(record.get(label_key) or "")
    match = re.fullmatch(r"\s*(\d+)\s*h\s*(\d+)\s*min\s*(\d+(?:[.,]\d+)?)\s*s\s*", label)
    if match:
        hours, minutes, seconds = match.groups()
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds.replace(",", "."))
    return None


def compact_duration(seconds):
    if seconds is None:
        return "Non renseigné"
    hours, rest = divmod(max(0, int(seconds)), 3600)
    minutes, seconds = divmod(rest, 60)
    parts = [f"{hours} h"] if hours else []
    if minutes or (hours and seconds):
        parts.append(f"{minutes:02d} min" if hours else f"{minutes} min")
    if seconds:
        parts.append(f"{seconds:02d} s" if parts else f"{seconds} s")
    return " ".join(parts) or "0 h"


def module_duration(module):
    active = seconds_value(module, "active_seconds", "active_time_label")
    required = seconds_value(module, "required_seconds", "required_time_label")
    known = bool(module.get("available", True)) and active is not None and required is not None and required > 0
    credited = min(active, required) if known else 0
    objectives = module.get("timed_objectives") or []
    if objectives and known:
        # Time exceeding one objective never fills another objective's shortfall.
        values = [module_duration({**item, "available": True}) for item in objectives]
        known = all(item["known"] for item in values)
        credited = min(required, sum(item["credited"] for item in values)) if known else 0
    return {"active": active, "required": required, "known": known,
            "credited": credited, "fraction": credited / required if known else None,
            "remaining": max(0, required - credited) if known else None}


def report_duration(report):
    modules = [module_duration(module) for module in report.get("modules", [])]
    required = seconds_value(report, "required_seconds", "required_time_label")
    if required is None and modules and all(item["required"] is not None for item in modules):
        required = sum(item["required"] for item in modules)
    known = bool(report.get("available")) and bool(modules) and all(item["known"] for item in modules) and bool(required)
    credited = min(required, sum(item["credited"] for item in modules)) if known else 0
    # The numerator describes fulfilled module durations, not surplus hours or
    # final-exam time. The uncapped active total is displayed separately.
    return {"active": credited if known else None, "required": required, "known": known,
            "credited": credited, "fraction": credited / required if known else None,
            "remaining": max(0, required - credited) if known else None}


def percentage(fraction):
    if fraction is None:
        return "Indisponible"
    number = 100 if fraction >= 1 else min(99.9, round(max(0, fraction) * 100, 1))
    return f"{number:g}".replace(".", ",") + " %"


def draw_check_badge(canvas, x, y, radius=7):
    """Blue scalloped seal and white tick, inspired by the supplied reference."""
    canvas.saveState()
    path = canvas.beginPath()
    for index in range(24):
        angle = math.pi / 2 + index * math.pi / 12
        r = radius if index % 2 == 0 else radius * .81
        px, py = x + math.cos(angle) * r, y + math.sin(angle) * r
        if index == 0:
            path.moveTo(px, py)
        else:
            path.lineTo(px, py)
    path.close()
    canvas.setFillColor(colors.HexColor("#39ADEF"))
    canvas.drawPath(path, fill=1, stroke=0)
    canvas.setStrokeColor(colors.white)
    canvas.setLineWidth(radius * .23)
    canvas.setLineCap(1)
    canvas.setLineJoin(1)
    path = canvas.beginPath()
    path.moveTo(x - radius * .36, y - radius * .02)
    path.lineTo(x - radius * .09, y - radius * .27)
    path.lineTo(x + radius * .42, y + radius * .30)
    canvas.drawPath(path, fill=0, stroke=1)
    canvas.restoreState()


class CompletionBadge(Flowable):
    def __init__(self, label="Terminé", font="Helvetica-Bold", size=8, width=75):
        super().__init__()
        self.label, self.font, self.size = label, font, size
        self.width, self.height = width, 17

    def draw(self):
        draw_check_badge(self.canv, 7, 9, 7)
        self.canv.setFillColor(INK)
        self.canv.setFont(self.font, self.size)
        self.canv.drawString(19, 6, self.label)


class TimeProgress(Flowable):
    def __init__(self, value, *, width=140, font="Helvetica", bold="Helvetica-Bold", large=False):
        super().__init__()
        self.value, self.width, self.font, self.bold, self.large = value, width, font, bold, large
        self.height = 54 if large else 18

    def wrap(self, availWidth, availHeight):
        self.width = min(self.width, availWidth)
        return self.width, self.height

    def draw(self):
        canvas, value = self.canv, self.value
        canvas.saveState()
        fraction = value["fraction"]
        label = compact_duration(value["active"]) + " / " + compact_duration(value["required"])
        if value["required"] is None:
            label = compact_duration(value["active"]) + " / durée non renseignée"
        font_size = 15 if self.large else 7.5
        canvas.setFont(self.bold, font_size)
        while canvas.stringWidth(label, self.bold, font_size) > self.width and font_size > 6.3:
            font_size -= .2
            canvas.setFont(self.bold, font_size)
        canvas.setFillColor(INK)
        canvas.drawString(0, 32 if self.large else 10, label)
        rail_y, rail_h = (17, 6) if self.large else (1, 3.5)
        canvas.setFillColor(TRACK)
        canvas.roundRect(0, rail_y, self.width, rail_h, rail_h / 2, stroke=0, fill=1)
        if fraction is not None and fraction > 0:
            fill_width = min(self.width, self.width * fraction)
            canvas.setFillColor(BLUE)
            canvas.roundRect(0, rail_y, fill_width, rail_h, min(rail_h / 2, fill_width / 2), stroke=0, fill=1)
        if self.large:
            canvas.setFont(self.font, 7.5)
            canvas.setFillColor(MUTED)
            if not value["known"]:
                caption = "Avancement indisponible - données partielles"
            elif value["remaining"] > 0:
                caption = compact_duration(math.ceil(value["remaining"])) + " restant à suivre"
            else:
                caption = "Durées prévues atteintes"
            canvas.drawString(0, 3, caption)
            canvas.drawRightString(self.width, 3, percentage(fraction))
        canvas.restoreState()
