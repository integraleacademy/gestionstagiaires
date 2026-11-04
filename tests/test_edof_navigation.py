"""Dossiers and operations remain distinct without losing bookmarked views."""
import datetime as dt
from urllib.parse import urlparse, parse_qs

from html import unescape
import re

import edof_directory
import integrale_edof_dashboard as dashboard
import integrale_edof_views as views
from test_integrale_edof_dashboard import site


def table_ids(html):
    return re.findall(r'<tr data-edof-folder="(\d+)">', html)


def fragment(html, tag, attr):
    return re.search(r"<" + tag + r"\b[^>]*" + attr + r"[^>]*>(.*?)</" + tag + ">", html, re.S).group(1)


def test_dossier_navigation_has_one_home_for_each_status(site):
    snap = site.vault.get(edof_directory.record_key(site.owner))
    base = snap["rows"]["100000"]
    states = ["notProcessed", "validated", "accepted", "inTraining", "terminated",
              "serviceDoneDeclared", "serviceDoneValidated", "billed", "paid", "refused", "canceled"]
    snap["rows"] = {str(200000+i): {**base, "folder_id": str(200000+i), "state": state}
                    for i, state in enumerate(states)}
    site.vault.put(edof_directory.record_key(site.owner), snap)
    seen = []
    for group, expected in [("requests", [0, 1]), ("training", [2, 3, 4]), ("billing", [5, 6, 7, 8]), ("closed", [9, 10])]:
        page = site.client.get("/admin/edof-test", query_string={"section": "state", "group": group, "tab": "all"})
        assert page.status_code == 200
        assert {r for r in table_ids(page.text)} == {str(200000+i) for i in expected}
        seen.extend(table_ids(page.text))
        nav = fragment(page.text, "nav", 'aria-label="Rubriques Intégrale EDOF"')
        assert "Dossiers CPF" in nav and "Automatisations" in nav
        assert "État des dossiers" not in nav and "Traitement des demandes" not in nav and "Traitement des automatisations" not in nav
        counters = fragment(page.text, "nav", 'aria-label="Filtres des dossiers"')
        assert ("Facturé" in counters) == (group == "billing")
        assert "Entrée déclarée" not in counters
    assert len(seen) == len(set(seen)) == len(states)
    assert len(table_ids(site.client.get("/admin/edof-test?group=all").text)) == len(states)


def test_formation_session_search_and_pagination_preserve_scope(site):
    key = edof_directory.record_key(site.owner)
    snap = site.vault.get(key)
    base = snap["rows"]["100000"]
    records = {str(300000+i): {**base, "folder_id": str(300000+i), "title": "APS novembre"} for i in range(30)}
    records["400000"] = {**base, "folder_id": "400000", "title": "A3P"}
    records["400001"] = {**base, "folder_id": "400001", "title": "APS novembre", "session_end_date": "2026-03-02"}
    site.vault.put(key, {**snap, "rows": records})
    params = {"section": "state", "group": "training", "tab": "accepted", "q": "Exemple", "course": "APS novembre", "period": "2026-02-02/2026-02-06"}
    page = site.client.get("/admin/edof-test", query_string=params)
    assert len(table_ids(page.text)) == 25
    assert "30 dossiers" in fragment(page.text, "span", 'class="wedof-result-summary"')
    scopes = [fragment(page.text, "nav", 'class="edof-pagination"'),
              fragment(page.text, "div", 'class="wedof-folder-ref"'),
              fragment(page.text, "nav", 'aria-label="Filtres des dossiers"')]
    for href in re.findall(r'href="([^"]+)"', "".join(scopes)):
        values = parse_qs(urlparse(unescape(href)).query)
        assert all(values[k] == [params[k]] for k in ("group", "q", "course", "period"))
    second = site.client.get("/admin/edof-test", query_string={**params, "page": 2})
    assert len(table_ids(second.text)) == 5
    assert not set(table_ids(page.text)) & set(table_ids(second.text))


def test_operation_states_use_receipts_without_repeating_dossier_statuses():
    now = dt.datetime(2026, 11, 4, 10, tzinfo=dashboard.PARIS)
    base = {"first_name": "Anne", "last_name": "Exemple", "title": "APS", "state": "accepted",
            "session_start_date": "2026-11-04", "session_end_date": "2026-11-30"}
    records = {str(500000+i): {**base, "folder_id": str(500000+i)} for i in range(8)}
    records["500000"]["session_start_date"] = "2026-11-05"  # Upcoming.
    records["500002"]["session_start_date"] = ""  # Incomplete.
    records["500007"]["state"] = "inTraining"  # Entry receipt, next action is the exit.
    data = {"wedof_automation_blocks": [{"external_id": "500003", "action": "both", "active": True}]}
    rows, _ = dashboard.dashboard_rows({"rows": records}, data, {}, now)
    dispatches = [{"folder": f, "action": "entry_training", "revision": 2, "status": status,
                   "changed": now.timestamp(), "intent": {**records[f], "actual_date": "2026-11-04"}}
                  for f, status in [("500004", "queued"), ("500005", "uncertain"), ("500006", "review"), ("500007", "confirmed")]]
    result = views.operation_rows(rows, dispatches, now, 2)
    state = {(r["folder_id"], r["action"]): r["operation_bucket"] for r in result}
    for i, expected in enumerate(["planned", "overdue", "attention", "blocked", "running", "attention", "blocked", "history"]):
        assert state[(str(500000+i), "entry_training")] == expected
    assert state[("500007", "service_done")] == "planned"
    assert len(result) == len(state) == 9
    assert all(r["dispatch_status"] == "confirmed" for r in result if r["operation_bucket"] == "history")


def test_automations_show_actions_and_legacy_billing_links_find_dossiers(site):
    page = site.client.get("/admin/edof-test?section=automations&tab=overdue")
    counters = fragment(page.text, "nav", 'aria-label="Filtres des actions"')
    assert all(label in counters for label in views.AUTOMATION_TABS.values())
    assert all(label not in counters for label in ["En formation", "Facturé", "Payé", "Entrée déclarée"])
    assert "2 actions" in fragment(page.text, "span", 'class="wedof-result-summary"')
    assert "Entrée en formation" in page.text and "Sortie et service fait" in page.text
    assert not table_ids(site.client.get("/admin/edof-test?section=automations&tab=history").text)
    for args, expected in [({"section": "automations", "tab": "invoiced"}, ("state", "billing", "invoiced")),
                           ({"section": "requests", "tab": "accepted"}, ("state", "training", "accepted")),
                           ({"section": "state", "tab": "entry"}, ("state", "training", "training")),
                           ({"section": "cancellations"}, ("state", "closed", "canceled"))]:
        section, group, _, tab = views.navigation(args)
        assert (section, group, tab) == expected
        assert site.client.get("/admin/edof-test", query_string=args).status_code == 200
