"""Dossiers and operations remain distinct without losing bookmarked views."""
import datetime as dt
from urllib.parse import urlparse, parse_qs

from html import unescape
import re

import edof_directory
import edof_invoicing
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


def test_billable_automation_matches_billing_and_shows_invoice_progress(site):
    key = edof_directory.record_key(site.owner)
    snap = site.vault.get(key)
    base = {**snap["rows"]["100000"], "state": "serviceDoneValidated"}
    cases = {
        "710001": {},
        "710002": {"state": "serviceDoneDeclared", "service_done_validated": True},
        "710003": {"billing_state": "billed"},
        "710004": {"payment_state": "issued"},
        "710005": {"state": "serviceDoneDeclared"},
    }
    rows = {folder: {**base, **fields, "folder_id": folder} for folder, fields in cases.items()}
    site.vault.put(key, {**snap, "rows": rows})
    site.gate.switch("integrale", 0, "admin")
    edof_invoicing.discover(site.store, site.owner, {"rows": {"710002": rows["710002"]}})
    invoice, = edof_invoicing.records(site.store.directory, site.owner)
    edof_invoicing.update(site.store.directory, invoice["token"], status="review", terms={"amount": "96.50"},
                          invoice_number="TEST-42", qonto_id="qonto-test", message="Réception à vérifier.")

    state = site.client.get("/admin/edof-test?section=state&group=billing&tab=billable").text
    billing_link = re.search(r'href="([^"]+)">Voir les dossiers à facturer dans Automatisations', state)
    page = site.client.get(unescape(billing_link[1]))
    assert page.status_code == 200 and table_ids(page.text) == table_ids(state) == ["710002", "710001"]
    assert '<strong>2</strong><span>À facturer</span>' in fragment(page.text, "nav", 'aria-label="Filtres des actions"')
    assert "2 dossiers" in page.text and "En attente de prise en charge" in page.text
    assert all(s in page.text for s in ("Facturation à vérifier", "Réception à vérifier.", "TEST-42", "96,50 €", "Voir la facture"))
    assert "Confirmer et transmettre" not in page.text
    # Opening this list never starts billing for the dossier without an invoice record.
    assert [r["folder"] for r in edof_invoicing.records(site.store.directory, site.owner)] == ["710002"]

    rows["710001"]["billing_state"] = "billed"
    site.vault.put(key, {**snap, "rows": rows})
    assert table_ids(site.client.get(unescape(billing_link[1])).text) == ["710002"]


def test_billable_counter_search_and_return_from_a_dossier_preserve_scope(site):
    key = edof_directory.record_key(site.owner)
    snap = site.vault.get(key)
    base = {**snap["rows"]["100000"], "state": "serviceDoneValidated", "title": "APS"}
    rows = {str(720000+i): {**base, "folder_id": str(720000+i)} for i in range(28)}
    rows["720026"]["title"] = "A3P"
    rows["720027"]["session_end_date"] = "2026-02-13"
    site.vault.put(key, {**snap, "rows": rows})
    params = {"section": "automations", "q": "Exemple", "course": "APS", "period": "2026-02-02/2026-02-06"}
    first = site.client.get("/admin/edof-test", query_string={**params, "tab": "overdue"}).text
    counter = re.search(r'<a [^>]*href="([^"]+)"[^>]*>\s*<strong>26</strong><span>À facturer</span>', first)
    first = site.client.get(unescape(counter[1])).text
    assert len(table_ids(first)) == 25
    next_page = re.search(r'href="([^"]+)">Suivant', first)
    second = site.client.get(unescape(next_page[1])).text
    assert table_ids(second) == ["720000"] and "Page 2 sur 2" in second
    detail_link = re.search(r'href="([^"]+)">Ouvrir le dossier', second)
    detail = site.client.get(unescape(detail_link[1])).text
    back = re.search(r'class="edof-back" href="([^"]+)"', detail)
    assert table_ids(site.client.get(unescape(back[1])).text) == ["720000"]
    empty = site.client.get("/admin/edof-test", query_string={**params, "tab": "billable", "q": "aucun"}).text
    assert not table_ids(empty) and "Aucun dossier à facturer" in empty


def test_today_counter_lists_only_current_actions_due_on_the_paris_day(site, monkeypatch):
    # Still the previous UTC day. Both 18:00 deadlines fall on the new Paris day.
    instant = dt.datetime(2026, 11, 4, 23, 30, tzinfo=dt.timezone.utc)
    class Clock(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz)
    monkeypatch.setattr(dashboard.dt, "datetime", Clock)
    key = edof_directory.record_key(site.owner)
    snap = site.vault.get(key)
    base = snap["rows"]["100000"]
    specs = [("600001","accepted","2026-11-05","2026-11-12"), ("600002","inTraining","2026-10-26","2026-11-05"),
             ("600003","accepted","2026-11-04","2026-11-10"), ("600004","accepted","2026-11-06","2026-11-11"),
             ("600005","serviceDoneValidated","2026-10-22","2026-11-05")]
    snap["rows"] = {f:{**base,"folder_id":f,"state":state,"session_start_date":start,"session_end_date":end}
                    for f,state,start,end in specs}
    site.vault.put(key, snap)
    def check(query, ids):
        html = site.client.get("/admin/edof-test", query_string={"section":"automations","tab":"today","q":query}).text
        assert table_ids(html) == ids
        assert re.search(r'<strong>'+str(len(ids))+r'</strong><span>Prévu aujourd’hui</span>', html)
    check("", ["600001", "600002"])
    instant += dt.timedelta(hours=12)
    check("", ["600001", "600002"])
    check("600002", ["600002"])
