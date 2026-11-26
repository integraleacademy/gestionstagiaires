"""Vehicle-only attestation, signed on the same page as the undertaking."""

from .aps import fitted
from .drawing import BW, L, R, Book
from .agenda import grid


def make(ref, out):
    p = Book(ref, out, "vtc")
    p.total += len(ref.agenda.groups) if ref.agenda else 0
    p.begin()
    p.side("badge")
    p.emit(2, L, 18, BW - 130, "Cond", 20, p.ink)
    for i in range(3, 6):
        p.emit(i, L, 46 + (i - 3) * 16, BW - 118, "Bar", 10.8, grid.MUTED)
    art = next(pic for block in ref.blocks[0] for pic in block.pictures)
    p.bitmap(art, R - 106, 28, 100)
    p.rect(L, 108, BW, 118, p.light)
    p.icon("people", L + 12, 119, 20, p.accent)
    p.emit(6, L + 42, 118, BW - 55, "BarB", 12, p.accent)
    fitted(p, 7, L + 13, 146, BW - 26, 26, "BarB", 13, p.ink)
    fitted(p, 8, L + 13, 176, BW - 26, 21, "Bar", 11.5, p.ink)
    fitted(p, 9, L + 13, 199, BW - 26, 24, "Bar", 11.5, p.ink)
    p.emit(10, L, 244, BW, "Cond", 21, p.ink)
    fitted(p, 11, L, 278, BW, 40, "Bar", 11.5, p.ink)
    fitted(p, 12, L, 319, BW, 39, "Bar", 11.5, p.ink)
    fitted(p, 13, L, 360, BW, 31, "Bar", 11, p.ink)
    p.line(L, 399, R, 399, grid.LINE)
    p.emit(14, L, 408, 279, "Bar", 10, grid.MUTED)
    fitted(p, 15, L + 301, 410, BW - 301, 33, "Bar", 10, grid.MUTED)
    fitted(p, 16, L + 301, 453, BW - 301, 40, "BarB", 10.5, p.accent)
    p.link(L + 301, 451, BW - 301, 39, ref.portal)
    p.emit(17, L, 431, 280, "BarB", 13, p.ink)
    p.emit(18, L, 453, 280, "Bar", 10.8, grid.MUTED)
    signature, seal = ref.blocks[0][-1].pictures
    p.bitmap(signature, L, 478, 77)
    p.bitmap(seal, L + 90, 478, 134)
    p.finish()
    if ref.agenda:
        for months in ref.agenda.groups:
            ref.agenda.page(p, months, ref.course_label)
    p.save()
