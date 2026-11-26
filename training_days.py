"""Working days used to schedule and print APS training in metropolitan France."""

import datetime
from functools import lru_cache


def _easter_date(year: int) -> datetime.date:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return datetime.date(year, month, day)


@lru_cache(maxsize=64)
def french_public_holidays(year: int) -> frozenset[datetime.date]:
    easter = _easter_date(year)
    return frozenset(
        {
            datetime.date(year, 1, 1),
            easter + datetime.timedelta(days=1),
            datetime.date(year, 5, 1),
            datetime.date(year, 5, 8),
            easter + datetime.timedelta(days=39),
            easter + datetime.timedelta(days=50),
            datetime.date(year, 7, 14),
            datetime.date(year, 8, 15),
            datetime.date(year, 11, 1),
            datetime.date(year, 11, 11),
            datetime.date(year, 12, 25),
        }
    )


def is_aps_working_day(day: datetime.date) -> bool:
    return day.weekday() < 5 and day not in french_public_holidays(day.year)
