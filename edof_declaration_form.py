"""Drive only the requested official declaration form in the existing EFP browser."""
import datetime as dt
from decimal import Decimal, InvalidOperation
import re
import time
from urllib.parse import urlsplit

from edof_declarations import begin_send, is_recorded, verify_identity
from edof_directory import normalized
from edof_readonly_test import ID_RE

ENTRY = r"d[ée]clarer (?:l[’']entr[ée]e|une entr[ée]e) en formation"
EXIT = r"d[ée]clarer la sortie (?:de|de la) formation"
SERVICE = r"d[ée]clarer le service fait"

MOTIF_OPTIONS = {
    "trainee_absent": r"le stagiaire a [ée]t[ée] absent ou (?:a )?abandonn[ée] sans force majeure[.]?",
    "provider_postponed": r"l[’']organisme a interrompu la formation (?:et a fait|avec) une proposition de report[.]?",
    "provider_stopped": r"l[’']organisme a interrompu la formation sans propos(?:er|ition) (?:de |une )?(?:report|reprise)[.]?",
}


class FormChanged(ValueError):
    pass


def exact(pattern):
    return re.compile("^(?:"+pattern+")$", re.I)


def button(page, pattern):
    name = exact(r"(?:(?:save|arrow_forward|edit)\s+)?(?:" + pattern + r")(?:\s+(?:save|arrow_forward|edit))?")
    return page.get_by_role("button", name=name).or_(page.get_by_role("link", name=name))


def option(page, pattern):
    return page.get_by_text(exact(pattern), exact=True)


def use(locator):
    locator.wait_for(state="visible", timeout=5000)
    if locator.count() != 1 or not locator.is_enabled():
        raise FormChanged()
    locator.click(timeout=5000)


def date_field(page, intent, entry):
    hint = re.compile(
        r"stagiaire est entr[ée]|date (?:effective )?d[’']entr[ée]e" if entry else r"stagiaire est sorti|date (?:effective )?de sortie", re.I)
    field = page.get_by_label(hint)
    if field.count() != 1:
        field = page.locator(
            'input[type="date"]:visible, input[matdatepicker]:visible, input.mat-datepicker-input:visible, input[placeholder="JJ/MM/AAAA" i]:visible')
    field.wait_for(state="visible", timeout=5000)
    if field.count() != 1:
        raise FormChanged()
    day = dt.date.fromisoformat(intent["actual_date"])
    value = day.isoformat() if field.get_attribute("type") == "date" else day.strftime("%d/%m/%Y")
    field.fill(value)
    field.press("Tab")
    if field.input_value() != value:
        raise FormChanged()


def partial(page, intent):
    force = intent["motif"] == "trainee_force"
    use(option(page, r"oui,? du stagiaire" if force else r"non,? il n[’']y a pas de cas de force majeure"))
    if not force:
        choice = page.get_by_role("combobox", name=re.compile("motif", re.I))
        if not choice.count():
            choice = page.get_by_label(re.compile("motif de sortie", re.I))
        if choice.count() != 1:
            raise FormChanged()
        pattern = exact(MOTIF_OPTIONS[intent["motif"]])
        if choice.evaluate("e => e.tagName") == "SELECT":
            labels = [s.strip() for s in choice.locator(
                "option").all_text_contents() if pattern.fullmatch(s.strip())]
            if len(labels) != 1:
                raise FormChanged()
            choice.select_option(label=labels[0])
        else:
            use(choice)
            use(page.get_by_role("option", name=pattern))
        first = page.get_by_role("dialog").get_by_role(
            "button", name=exact(r"oui,? (?:enregistrer|continuer|confirmer)"))
        if first.count() == 1 and first.is_visible():
            use(first)
    rate = page.get_by_label(re.compile("taux de r[ée]alisation", re.I))
    if rate.count() != 1:
        rate = page.get_by_role("spinbutton", name=re.compile("taux", re.I))
    rate.fill(str(intent["rate"]))
    rate.press("Tab")
    if rate.input_value() != str(intent["rate"]):
        raise FormChanged()


def data_values(obj):
    if isinstance(obj, dict):
        for value in obj.values():
            yield from data_values(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from data_values(value)
    else:
        yield obj


class SingleWrite:
    """Allow a single official UI request for this folder, only during its final save."""

    def __init__(self, spec, origin, prefix, directory):
        self.spec, self.origin, self.prefix, self.directory = spec, origin, prefix, directory
        self.armed = False
        self.sent = False
        self.rejected = False
        self.request_key = None
        self.response_status = None

    def allows_simulation(self, request):
        if (self.spec["mode"] != "declare" or self.spec["intent"]["action"] != "service_done"
                or self.sent or request.method != "POST" or request.resource_type not in {"xhr","fetch"}
                or request.url != f"https://{self.origin}{self.prefix}{self.spec['folder_id']}/simulation"):
            return False
        if not request.frame.url.startswith(f"https://{self.origin}/espace-prive/"):
            return False
        try:
            body = request.post_data_json
            return (isinstance(body, dict) and set(body) == {"tauxRealisationOF","motifFinFormation"}
                    and int(body["tauxRealisationOF"]) == self.spec["intent"]["rate"])
        except (TypeError, ValueError, KeyError):
            return False

    def allows(self, request):
        if not self.armed or self.sent or self.spec["mode"] != "declare":
            return False
        u = urlsplit(request.url)
        folder = self.spec["folder_id"]
        if not ID_RE.fullmatch(folder) or request.method not in {"POST", "PUT", "PATCH"} or request.resource_type not in {"xhr", "fetch"}:
            return False
        try:
            frame = urlsplit(request.frame.url)
        except Exception:
            return False
        if (u.scheme != "https" or u.netloc != self.origin or u.query or u.fragment or frame.scheme != "https"
                or frame.netloc != self.origin or not frame.path.startswith("/espace-prive/")):
            return False
        base = self.prefix+folder
        if u.path != base and not u.path.startswith(base+"/"):
            return False
        suffix = u.path[len(base):].strip("/")
        words = normalized(re.sub(r"([a-z])([A-Z])", r"\1 \2", suffix))
        entry = self.spec["intent"]["action"] == "entry_training"
        allowed = ({"in training", "intraining", "entry", "entry training", "training entry", "enter training", "begin training", "entry in training", "declare entry", "entry declaration", "start training", "begin date"}
                   if entry else {"service done", "service done declared", "declare service done", "training completion", "end training", "exit training", "end date", "service done declaration", "servicedone"})
        status_entry = entry and suffix == "status"
        if self.spec["intent"].get("pilot_ticket") and not status_entry:
            self.rejected = True
            return False
        status_exit = not entry and suffix == "status"
        if suffix and words not in allowed and not (status_entry or status_exit):
            self.rejected = True
            return False
        try:
            body = request.post_data_json
        except Exception:
            self.rejected = True
            return False
        values = list(data_values(body))
        date = self.spec["intent"]["actual_date"]
        if status_entry and (request.method != "PUT" or body != {
                "state": "IN_TRAINING", "date": dt.date.fromisoformat(date).strftime("%d/%m/%Y")}):
            self.rejected = True
            return False
        service_only = status_exit and self.spec["intent"].get("exit_confirmed") is True
        if status_exit:
            if (request.method != "PUT" or not isinstance(body, dict)
                    or body.get("state") not in {"TERMINATED", "SERVICE_DONE_DECLARED"}
                    or (service_only and body.get("state") != "SERVICE_DONE_DECLARED")
                    or (not service_only or "terminatedDate" in body) and body.get("terminatedDate") != dt.date.fromisoformat(date).strftime("%d/%m/%Y")
                    or type(body.get("achievementRate")) is not int or body["achievementRate"] != self.spec["intent"]["rate"]
                    or body.get("completed") is not (self.spec["intent"]["rate"] == 100)
                    or (body["completed"] and (str(body.get("terminatedReason")) != "8" or body.get("forceMajeureAbsence") is not False))):
                self.rejected = True
                return False
        if not service_only and not any(isinstance(v, str) and (v == date or v == dt.date.fromisoformat(date).strftime("%d/%m/%Y")
                   or re.fullmatch(re.escape(date)+r"T00:00:00(?:\.0+)?(?:Z|[+]00:00)?", v)) for v in values):
            self.rejected = True
            return False
        if not suffix:
            # A generic dossier update must identify the intended transition in its body.
            wanted = {"intraining", "in training"} if entry else {
                "servicedonedeclared", "service done declared"}
            if not any(isinstance(v, str) and normalized(v) in wanted for v in values):
                self.rejected = True
                return False
        if not entry:
            # Check any completion percentage the portal puts on the wire, including partial cases.
            rates = binding_values(body, {"trainingcompletionrate", "completionrate",
                                   "realizationrate", "realisationrate", "achievementrate", "rate"})
            try:
                if any(Decimal(str(value)) != Decimal(self.spec["intent"]["rate"]) for value in rates):
                    self.rejected = True
                    return False
            except (InvalidOperation, ValueError):
                self.rejected = True
                return False
        if not begin_send(self.directory, self.spec):
            return False
        self.request_key = (request.url, request.method)
        self.sent = True
        self.armed = False
        return True

    def observe(self, response):
        if self.sent and self.request_key == (response.url, response.request.method):
            self.response_status = response.status


def binding_values(data, keys):
    if isinstance(data, dict):
        for key, value in data.items():
            if normalized(key).replace(" ", "") in keys:
                yield value
            else:
                yield from binding_values(value, keys)
    elif isinstance(data, list):
        for item in data:
            yield from binding_values(item, keys)


def transmit(page, spec, fields, gate, reload_fields):
    intent = spec["intent"]

    def result(code, verified=None):
        outcome = {"code": code, "stage": "declaration"}
        if verified is not None:
            outcome["confirmed_state"] = verified["state"]
        return outcome
    if not verify_identity(fields, spec):
        return result("declaration_changed")
    if is_recorded(fields, intent):
        return result("declaration_confirmed", fields)
    def verified_exit_only(observed):
        return (intent["action"] == "service_done" and not intent.get("exit_confirmed")
                and observed and verify_identity(observed, spec)
                and normalized(observed.get("state") or "") in {"terminated","sortie declaree"}
                and observed.get("end_date") == intent["actual_date"])
    if spec["mode"] == "reconcile":
        return result("declaration_exit_confirmed" if verified_exit_only(fields) else "declaration_unverified")
    entry = intent["action"] == "entry_training"
    if normalized(fields.get("state") or "") not in ({"accepted", "accepte"} if entry else {"intraining", "en formation", "entree declaree", "terminated", "sortie declaree"}):
        return result("declaration_changed")
    if not entry and (not fields.get("start_date") or intent["actual_date"] < fields["start_date"]):
        return result("declaration_changed")
    if not entry and intent.get("source") in {"production", "local"}:
        try:
            actual = Decimal(intent["actual_hours"])
            contracted = Decimal(fields["duration_hours"])
            if not actual.is_finite() or not contracted.is_finite() or actual != contracted or actual <= 0:
                return result("declaration_evidence_changed")
        except (InvalidOperation, KeyError, TypeError):
            return result("declaration_evidence_changed")
    try:
        already_out = not entry and normalized(fields.get("state") or "") in {"terminated", "sortie declaree"}
        if already_out and fields.get("end_date") != intent["actual_date"]:
            return result("declaration_changed")
        if intent.get("exit_confirmed") and not already_out:
            return result("declaration_changed")
        if already_out:
            intent["exit_confirmed"] = True
        else:
            use(button(page, ENTRY if entry else EXIT))
        if entry:
            confirm = button(page, r"oui,? continuer")
            if not confirm.count() and not page.locator('input.mat-datepicker-input:visible,input[type="date"]:visible').count():
                confirm.wait_for(state="visible", timeout=4000)
            if confirm.count() and confirm.is_visible():
                use(confirm)
        if not already_out:
            date_field(page, intent, entry)
        if not entry:
            if not already_out:
                use(button(page, r"suivant"))
                dialog_next = page.get_by_role("dialog").get_by_role("button", name=exact(r"(?:arrow_forward )?suivant"))
                if dialog_next.count() == 1 and dialog_next.is_visible():
                    use(dialog_next)
            choice = option(page, r"suivi int[ée]gralement" if intent["rate"] == 100 else r"suivi partiellement")
            service = button(page, SERVICE)
            choice.or_(service).first.wait_for(state="visible", timeout=5000)
            if not choice.is_visible():
                use(service)
            use(choice)
            if intent["rate"] != 100:
                partial(page, intent)
        # The form itself constructs the transaction. The request fence is closed for every other click.
        gate.armed = True
        save = page.locator("sl7-registration-folder-set-in-training-form button#confirm-button:visible") if entry else None
        use(save if save is not None and save.count() == 1 else button(page, r"enregistrer(?: (?:le service fait|la déclaration))?"))
        if not gate.sent:
            dlg = page.get_by_role("dialog")
            confirm = dlg.get_by_role("button", name=exact(r"oui,? (?:enregistrer|confirmer|valider)"))
            if confirm.count() == 0:
                confirm = button(page, r"oui,? (?:enregistrer|confirmer|valider)")
            until = time.monotonic()+5
            while not gate.sent and not gate.rejected and time.monotonic() < until:
                if confirm.count() == 1 and confirm.is_visible():
                    if not entry:
                        summary = normalized((dlg if dlg.count() == 1 else page.locator("body")).inner_text())
                        if not (re.search(r"(?<!\d)"+str(intent["rate"])+r"(?!\d)", summary) or intent["rate"] == 100 and "integralement" in summary):
                            raise FormChanged()
                    use(confirm)
                    break
                page.wait_for_timeout(125)
        until = time.monotonic()+4
        while not gate.sent and not gate.rejected and time.monotonic() < until:
            page.wait_for_timeout(125)
    except Exception:
        if not gate.sent:
            return result("declaration_form_changed")
    finally:
        gate.armed = False
    if not gate.sent:
        return result("declaration_form_changed")
    # Do not navigate away while the final request is still in flight.
    deadline = time.monotonic()+20
    while gate.response_status is None and time.monotonic() < deadline:
        page.wait_for_timeout(125)
    if gate.response_status is None:
        return result("declaration_unverified")
    fresh = reload_fields()
    if fresh and verify_identity(fresh, spec) and is_recorded(fresh, intent):
        return result("declaration_confirmed", fresh)
    if verified_exit_only(fresh):
        return result("declaration_exit_confirmed")
    if gate.response_status in {400, 401, 403, 404, 422} and fresh and verify_identity(fresh, spec) and fresh.get("state") == fields.get("state"):
        return result("declaration_refused")
    return result("declaration_unverified")
