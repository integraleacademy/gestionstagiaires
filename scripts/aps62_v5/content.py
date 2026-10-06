from pathlib import Path


def courses():
    result = {}
    for line in Path(__file__).with_name('courses.txt').read_text().splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        cells = line.split('|')
        assert len(cells) == 8, cells[0]
        key, title, rule, example, takeaway, *terms = cells
        assert 'aps62-' + key not in result, key
        glossary = [dict(zip(('term', 'definition'), t.split('=', 1))) for t in terms]
        result['aps62-' + key] = dict(title=title, rule=rule, example=example,
            takeaway=takeaway, glossary=glossary)
    assert len(result) == 62
    return dict(sorted(result.items()))
