from datetime import date

from docx import Document
import pymupdf

import app
from academy_convocations.aps_calendar import (
    CENTRE,
    EXAM,
    OFF,
    REMOTE,
    Schedule,
    span_title,
)
from training_days import french_public_holidays


def test_opening_remote_weekends_exam_and_french_holidays():
    first = date(2027, 3, 19)
    schedule = Schedule(
        (first, date(2027, 3, 23)),
        (date(2027, 3, 25), date(2027, 4, 2)),
        first,
        date(2027, 4, 3),
    )
    assert schedule.color(first) == REMOTE
    assert schedule.color(date(2027, 3, 20)) == REMOTE
    assert schedule.color(date(2027, 3, 24)) == OFF
    assert schedule.color(date(2027, 3, 25)) == CENTRE
    assert schedule.color(date(2027, 3, 27)) == OFF
    assert date(2027, 3, 29) in french_public_holidays(2027)
    assert schedule.color(date(2027, 3, 29)) == OFF
    assert schedule.color(date(2027, 3, 30)) == CENTRE
    assert schedule.color(date(2027, 4, 3)) == EXAM


def test_partial_legacy_dates_do_not_assign_training_days_to_unknown_periods():
    fields = [""] * 10
    fields[3] = "Du 31/02/2027 au 02/03/2027"
    fields[5] = "Du 20/04/2027 au 05/04/2027"
    fields[7] = "À confirmer"
    fields[9] = "À confirmer"
    empty = Schedule.from_page(fields)
    assert empty.month_groups() == [[]]
    assert span_title([]) == "Dates à confirmer"
    fields[9] = "06/04/2027 à 08h00"
    partial = Schedule.from_page(fields)
    assert partial.month_groups() == [[(2027, 4)]]
    assert partial.color(date(2027, 4, 5)) == OFF
    assert partial.color(date(2027, 4, 6)) == EXAM


def test_multi_page_calendar_crosses_new_year_and_keeps_links_and_leap_day(
    tmp_path, monkeypatch
):
    session = dict(
        id="cross-year",
        name="APS",
        training_type="APS",
        date_start="2027-11-29",
        date_end="2028-03-30",
        exam_date="2028-04-03",
        aps_remote_start="2027-11-29",
        aps_remote_end="2028-01-15",
        aps_in_person_start="2028-01-17",
        aps_in_person_end="2028-03-30",
    )
    trainee = dict(
        id="test",
        first_name="Camille",
        last_name="Exemple",
        email="test@example.invalid",
    )
    monkeypatch.setattr(app, "APS_CONVOCATION_DIR", str(tmp_path))
    with app.app.test_request_context("/"):
        editable, pdf = app._generate_aps_convocation_files(session, trainee)
    with pymupdf.open(pdf) as pages:
        assert len(pages) == 9
        assert pages[0].search_for("Voir le plan des parkings en page 9")
        assert any(link.get("page") in (8, "9") for link in pages[0].get_links())
        first, second = pages[3], pages[4]
        assert all(
            first.search_for(m)
            for m in ("Novembre 2027", "Décembre 2027", "Janvier 2028", "Février 2028")
        )
        assert all(second.search_for(m) for m in ("Mars 2028", "Avril 2028"))
        assert pages[5].search_for("03/04/2028 à 08h00")
        assert pages[8].search_for("Parking public")

        # The last February row has a Monday 28 and Tuesday 29, with centre-day fills.
        title = first.search_for("Février 2028")[-1]
        grid = pymupdf.Rect(title.x0 - 2, title.y1, first.rect.x1, 434)
        words = [
            word for word in first.get_text("words", clip=grid) if word[4].isdecimal()
        ]
        assert sorted(int(word[4]) for word in words) == list(range(1, 30))
        by_number = {word[4]: pymupdf.Rect(word[:4]) for word in words}
        assert abs(by_number["28"].y0 - by_number["29"].y0) < 1
        assert by_number["28"].x0 < by_number["29"].x0
        point = (by_number["29"].tl + by_number["29"].br) / 2
        assert any(
            d["fill"]
            and bytes(round(c * 255) for c in d["fill"]).hex() == CENTRE[0][1:].lower()
            and point in d["rect"]
            for d in first.get_drawings()
        )
    word = Document(editable)
    assert word.element.xpath('.//w:hyperlink[@w:anchor="Page9"]')
    assert word.element.xpath('.//w:hyperlink[@w:anchor="Page4"]')
