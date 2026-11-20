"""Public VTC purchases, with Qonto collection and signed, practical-only agreements."""
import datetime as dt
import secrets
import re
import time
import uuid
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, session, url_for

import exam_retakes
import exam_retakes_workflow as provider
import vtc_order_agreements as agreements
import vtc_order_finance as finance
from manuals_commerce import ReviewRequired, collect_basket, safe_payment_url
from vtc_order_documents import AREA, BOOKING, CENTRES, CMA, CONTACT, OFFERS, document
from vtc_order_store import Store

PARIS = ZoneInfo("Europe/Paris")
ORIGIN = "https://admissions.integraleconnect.com"
STAGES = {"verify":"Adresse e-mail à confirmer", "calendar":"Rendez-vous CPF avec Cassandre",
          "planning":"Créneau de formation à fixer", "availability":"Créneau d’examen à confirmer",
          "contract":"Contrat à signer", "delivery":"Prestations à réaliser", "billing":"Règlement à suivre",
          "paid":"Commande réglée", "funded":"Financement CPF enregistré", "withdrawn":"Annulation demandée",
          "stopped":"Signature interrompue"}


def token(row):
    return row["id"] + "." + row["access_key"]


def status_link(host, row):
    return ORIGIN + "/vtc/suivi/" + token(row)


def notify(host, store, row, key, subject, message, paths=(), *, delivery_key=None):
    link = status_link(host, row)
    def content(_host, _row, _key, _link):
        actions = {
            "verify": "Confirmer mon adresse e-mail", "pay": "Accéder au paiement par carte",
            "signature": "Accéder à la signature", "reminder": "Accéder à la signature", "paid": "Retrouver ma facture et mon attestation",
            "signed": "Retrouver mon contrat signé", "cpf": "Consulter mon dossier CPF",
        }
        action = actions.get(key, "Consulter mon dossier VTC")
        summary = OFFERS[row["offer"]] + " · " + ("150 € TTC" if row["offer"] == "vehicule" else "600 € TTC")
        centre = CENTRES.get(row.get("exam_centre"))
        content = host.app.jinja_env.get_template("vtc_orders/email.html").render(
                                  row=row, message=message, link=link,
                                  action=action, summary=summary, centre=centre, area=AREA, cma=CMA)
        html = host.render_academy_email(content, title=subject, eyebrow="EXAMEN PRATIQUE VTC",
                                         subtitle="Votre dossier candidat", preheader=message)
        text = "\n\n".join([f"Bonjour {row['person']['first_name']},", message, action + " : " + link,
                            summary, centre or AREA, CMA, CONTACT])
        return subject + " · Intégrale Academy", html, text
    return provider.send_email(host, store, row, key, link, paths, delivery_key=delivery_key, content_builder=content)


def receipt(store, row):
    path = store.document(row["id"], "vehicle")
    if not path.is_file():
        document(row, path)
    return ("Attestation-vehicule-VTC.pdf", path)


def sync_card_billing(host, store, row):
    # A prior invoice or an ambiguous creation must keep its original payment route.
    if not row.get("billing_flow"):
        legacy = any(row.get(key) for key in ("invoice_id", "invoice_started", "payment_id", "payment_started", "payment_url"))
        provider.checkpoint(store, row, billing_flow="invoice_first" if legacy else "payment_first")
    retired = row.get("retired_payment_links", [])
    suffix = f"-{len(retired)}" if retired else ""
    if row["billing_flow"] == "invoice_first":
        invoice = provider.ensure_invoice(host, store, row)
        provider.ensure_payment(host, store, row, invoice, idempotency_key="retake-payment-" + row["id"] + suffix,
                                retired_link_ids=retired)
        return
    if row["billing_flow"] != "payment_first":
        raise ReviewRequired("Le mode de facturation VTC doit être vérifié.")

    item = {"title": OFFERS[row["offer"]], "type": "service", "quantity": 1, "measure_unit": "unit",
            "description": f"Réservation VTC [{row['id']}]", "vat_rate": "0",
            "unit_price": {"value": f"{row['total_cents'] / 100:.2f}", "currency": "EUR"}}
    captured = collect_basket(host, order_id=row["id"], total_cents=row["total_cents"], items=[item],
                              state=row, save=lambda **fields: provider.checkpoint(store, row, **fields),
                              idempotency_key="vtc-basket-" + row["id"] + suffix, card_required=True, retired_link_ids=retired)
    if not captured:
        return
    capture = row["confirmed_payment"]
    payment_time = dt.datetime.fromisoformat(capture["paid_at"].replace("Z", "+00:00")).astimezone(PARIS)
    row["payment_terms"] = (f"Règlement intégral reçu le {payment_time:%d/%m/%Y}. "
                            f"Référence du paiement Qonto : {capture['id']}.")
    invoice = provider.ensure_invoice(host, store, row)
    if invoice.get("organization_id") != row["merchant_id"]:
        raise ReviewRequired("La facture VTC et le règlement ne correspondent pas au même organisme.")
    if invoice["status"] == "unpaid":
        host._qonto_request("POST", f"/v2/client_invoices/{invoice['id']}/mark_as_paid",
                            {"paid_at": payment_time.date().isoformat()},
                            idempotency_key="vtc-paid-" + row["id"])
        invoice = host._qonto_invoice_payload(host.get_qonto_invoice(row["invoice_id"]))
        provider.invoice_assert(row, invoice)
    if invoice["status"] != "paid":
        raise ReviewRequired("Règlement reçu. La confirmation de la facture acquittée est en attente.")
    provider.record_payment(store, row, "paid", row["total_cents"])


def advance(host, store, row):
    stage = row["stage"]
    if stage == "verify":
        if row["offer"] == "cpf":
            message = "Confirmez votre adresse pour choisir un rendez-vous téléphonique avec Cassandre au sujet de votre financement CPF."
        elif row["offer"] == "formation":
            message = "Confirmez votre adresse pour préparer votre séance et signer votre contrat de formation en ligne."
        elif finance.method(row) != "card":
            message = "Confirmez votre adresse pour poursuivre votre réservation. Mode de règlement prévu : " + finance.METHODS[finance.method(row)] + "."
        elif row.get("exam_date"):
            message = "Confirmez votre adresse pour que notre équipe vérifie la disponibilité du véhicule à la date de votre examen. Nous vous préviendrons dès que vous pourrez payer."
        else:
            message = "Confirmez votre adresse pour accéder au paiement sécurisé de 150 € par carte bancaire."
        notify(host, store, row, "verify", "Confirmez votre adresse e-mail", message)
    elif stage == "billing":
        if row["offer"] == "formation" and not store.document(row["id"],"completion").exists():
            document(row,store.document(row["id"],"completion"),completed=True)
        if not row.get("invoice_id") and not row.get("invoice_started"):
            row["vat_rate"] = "0"
        is_card = finance.method(row) == "card"
        try:
            if is_card:
                sync_card_billing(host, store, row)
            else:
                finance.sync_offline_billing(host, store, row)
        except Exception:
            row["billing_problem"] = True
            raise
        row["billing_problem"] = False
        if row.get("payment_status") == "paid" and row.get("paid_cents") == row["total_cents"]:
            path = store.document(row["id"], "invoice")
            pdf, _ = host.fetch_qonto_client_invoice_pdf(row["invoice_id"])
            provider.store_pdf(path, pdf)
            files = [("Facture-VTC.pdf",path),receipt(store,row)]
            if row["offer"] == "formation":
                files.append(("Attestation-realisation-VTC.pdf",store.document(row["id"],"completion")))
                files.append(("Contrat-VTC-signe.pdf",store.document(row["id"],"signed")))
            notify(host,store,row,"paid","Votre commande VTC est réglée",
                   "Votre règlement est confirmé. Retrouvez votre facture et votre attestation pour l’examen dans votre dossier.",files)
            row["stage"] = "paid"
        else:
            if not is_card and not (row.get("invoice_id") or row.get("manual_receipt") or row.get("invoice_requested")):
                return -1
            if payment_state(row) == "ready":
                notify(host, store, row, "pay", "Votre paiement par carte VTC",
                       "Votre lien sécurisé de règlement par carte est disponible dans votre dossier.",
                       delivery_key="pay-" + str(len(row["retired_payment_links"])) if row.get("retired_payment_links") else "pay")
            return 90 if time.time()-row["created"] < 3600 else 900
    elif stage == "funded":
        notify(host,store,row,"cpf","Votre dossier CPF VTC","Le centre a confirmé la prise en charge de votre dossier CPF. Votre attestation est jointe.",[receipt(store,row)])
    elif stage == "withdrawn":
        notify(host,store,row,"withdrawn","Réception de votre demande d’annulation","Nous avons enregistré votre demande. L’équipe vérifiera l’état de votre commande et les sommes éventuellement à vous restituer.")
    return -1


def process_pending(host):
    store = Store(host)
    for oid in store.pending():
        try:
            with store.lock(oid):
                row = store.get(oid)
                if row.get("due",0) < 0 or row.get("due",0) > time.time():
                    continue
                try:
                    signature_wait = agreements.sync(host, store, row, notify, receipt)
                    row["agreement_error"] = ""
                except Exception as exc:
                    signature_wait = 180
                    row["agreement_error"] = host._sanitize_yousign_error(str(exc))[:400]
                    host.app.logger.warning("vtc_order_signature id=%s type=%s", oid, type(exc).__name__)
                try:
                    wait = advance(host, store, row)
                    row["error"] = ""
                except Exception as exc:
                    wait = 180
                    row["error"] = host._sanitize_qonto_error(host._sanitize_yousign_error(str(exc)))[:400]
                    host.app.logger.warning("vtc_order_processing id=%s type=%s",oid,type(exc).__name__)
                waits = [delay for delay in (wait, signature_wait) if delay >= 0]
                row["due"] = time.time() + min(waits) if waits else -1
                store.save(row)
        except exam_retakes.RetakeError:
            continue


def clean_person(form, host, offer):
    fields = {"first_name":80,"last_name":80,"email":254,"phone":30,"address":160,"zip_code":12,"city":90}
    if offer == "cpf":
        fields = {key:fields[key] for key in ("first_name","last_name","email","phone")}
    person = {}
    for key, limit in fields.items():
        value = form.get(key,"").strip()
        if not value or len(value)>limit or any(ord(c)<32 for c in value):
            raise ValueError("Complétez vos coordonnées avec des valeurs valides.")
        person[key] = value
    person["email"] = person["email"].lower()
    if not re.fullmatch(r"[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+",person["email"]) or not host._normalize_yousign_sms_phone(person["phone"]):
        raise ValueError("Vérifiez votre adresse e-mail et votre numéro de mobile.")
    code = form.get("country_code","FR").strip().upper()
    if not re.fullmatch(r"[A-Z]{2}",code):
        raise ValueError("Indiquez un code pays à deux lettres, par exemple FR.")
    person["country_code"] = code
    return person


def new_order(host, form, offer, oid):
    person = clean_person(form, host, offer)
    if form.get("accepted") != "yes":
        raise ValueError("Veuillez prendre connaissance des modalités de votre formule et de la consigne CMA.")
    centre = form.get("exam_centre", "")
    if centre not in CENTRES:
        raise ValueError("Choisissez votre centre d’examen parmi les deux centres desservis.")
    day = form.get("exam_date","").strip()
    if day and exam_retakes.date_value(day,"Examen") < exam_retakes.today():
        raise ValueError("La date d’examen indiquée est passée.")
    if offer != "vehicule" and form.get("admissible") != "yes":
        raise ValueError("Confirmez votre admissibilité à l’épreuve pratique.")
    total = 15000 if offer=="vehicule" else 60000
    return {"id":oid, "access_key":secrets.token_urlsafe(32), "created":time.time(), "submitted_at":exam_retakes.now(), "offer":offer, "kind":"VTC pratique",
            "stage":"verify","status":"queued","person":person,"exam_centre":centre,"exam_date":day,"days":[],"accepted_at":exam_retakes.now(),
            "selected_slot":form.get("slot_id","")[:64] if offer=="formation" else "",
            "total_cents":total, "purchase_order":"VTC-"+oid, "invoice_title":OFFERS[offer],
            "billing_lines":[{"label":OFFERS[offer]+" – examen VTC","unit_cents":total,"total_cents":total,"quantity":1}],
            "vat_rate":"0", "vat_exemption":"" if offer=="vehicule" else "S261",
            "payment_terms":"Paiement par carte bancaire. "+("Mise à disposition du véhicule pour le passage organisé avec le centre." if offer=="vehicule" else "Règlement à l’issue des prestations."),
            "due":0}


def schedule(form, personal):
    day = dt.date.fromisoformat(exam_retakes.date_value(form.get("day"),"Jour de formation"))
    minimum = dt.date.fromisoformat(exam_retakes.today()) + dt.timedelta(days=15 if personal else 0)
    if day < minimum:
        raise ValueError("Choisissez une date laissant au moins 14 jours complets pour la rétractation." if personal else "La séance doit être à venir.")
    start, end = form.get("start",""), form.get("end","")
    if not all(re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d",t) for t in (start,end)) or end<=start:
        raise ValueError("Vérifiez les horaires de la séance.")
    trainer = form.get("trainer","").strip()
    if not 5 <= len(trainer) <= 160:
        raise ValueError("Indiquez le nom et la qualification du formateur.")
    mins = int(end[:2])*60+int(end[3:])-int(start[:2])*60-int(start[3:])
    return dict(day=day.isoformat(),start=start,end=end,trainer=trainer,duration=f"{mins//60} h {mins%60:02d}")


def payment_state(row):
    """Only an open, verified Qonto link may be offered to the candidate."""
    if row["stage"] != "billing":
        return row["stage"]
    if finance.method(row) != "card":
        return "offline"
    status = row.get("payment_status")
    if status == "paid":
        return "documents" if row.get("paid_cents") == row["total_cents"] else "review"
    if status == "processing":
        return "processing"
    if status in {"review", "partially_paid", "canceled"}:
        return "review"
    if row.get("billing_problem", bool(row.get("error"))):
        return "unavailable"
    if status == "unpaid" and safe_payment_url(row.get("payment_url")):
        return "ready"
    return "preparing"


def register(app, host):
    bp = Blueprint("vtc_orders",__name__)
    def csrf_token():
        return session.setdefault("vtc_csrf", secrets.token_hex(32))

    def check_csrf():
        expected = session.get("vtc_csrf")
        actual = request.form.get("csrf_token","")
        if not expected or not secrets.compare_digest(expected.encode(), actual.encode()):
            abort(400, "Ce formulaire a expiré. Rechargez la page.")

    bp.add_app_template_filter(exam_retakes.date_label,"vtc_date")
    def earliest():
        return (dt.date.fromisoformat(exam_retakes.today()) + dt.timedelta(days=15)).isoformat()

    def render(template, **values):
        return render_template("vtc_orders/"+template+".html", csrf=csrf_token(), offers=OFFERS, stages=STAGES,
                               centres=CENTRES, area=AREA, cma=CMA, booking=BOOKING, today=exam_retakes.today(),
                               payment_method=finance.method, methods=finance.METHODS, money=exam_retakes.money,
                               agreement_state=agreements.state, agreement_labels=agreements.LABELS, **values)

    @bp.before_request
    def canonical_public_address():
        # Legacy email links remain valid. The gateway marker only prevents a
        # redirect loop; it never grants access or replaces token/CSRF checks.
        if (request.method in {"GET", "HEAD"}
                and request.path.startswith(("/vtc/commande/", "/vtc/suivi/"))
                and request.host.split(":")[0] in {"gestionstagiaires-r5no.onrender.com", "integraleconnect.com", "www.integraleconnect.com"}
                and request.headers.get("X-VTC-Gateway") != "admissions"):
            return redirect(ORIGIN + request.full_path.rstrip("?"), 302)

    @bp.after_request
    def private_headers(response):
        response.headers["Cache-Control"]="no-store"
        response.headers["Referrer-Policy"]="no-referrer"
        response.headers["X-Robots-Tag"]="noindex, nofollow"
        return response

    @bp.route("/vtc/commande/<offer>", methods=["GET","POST"])
    def checkout(offer):
        if offer not in OFFERS:
            abort(404)
        key = "vtc_form_"+offer
        if request.method == "GET":
            session.setdefault(key,uuid.uuid4().hex)
            return render("checkout",offer=offer,error="",slots=Store(host).slots(earliest()) if offer=="formation" else [])
        check_csrf()
        oid=session.get(key)
        if not oid or request.form.get("draft") != oid:
            abort(400)
        try:
            row = new_order(host, request.form, offer, oid)
            store = Store(host)
            if row["selected_slot"]:
                slot = next((slot for slot in store.slots(earliest()) if slot["id"]==row["selected_slot"]), None)
                if not slot or row["exam_date"] and slot["day"] > row["exam_date"]:
                    raise ValueError("Choisissez un créneau disponible avant votre examen.")
            store.add(row,request.remote_addr or "unknown")
            session["vtc_sent_"+offer] = oid
            exam_retakes.wake_worker(host)
        except ValueError as exc:
            return render("checkout",offer=offer,error=str(exc),slots=Store(host).slots(earliest()) if offer=="formation" else []),400
        return redirect(url_for(".sent",offer=offer),303)

    @bp.get("/vtc/commande/<offer>/confirmation")
    def sent(offer):
        if offer not in OFFERS:
            abort(404)
        # The email link is the only public access to the purchaser's details.
        oid = session.get("vtc_sent_"+offer)
        row = Store(host).get(oid) if oid else None
        if oid and session.get("vtc_form_"+offer) == oid:
            session.pop("vtc_form_"+offer, None)
        return render("sent", offer=offer, sent=row)

    def lookup(key):
        parts = re.fullmatch(r"([a-f0-9]{32})\.([A-Za-z0-9_-]{43})", key)
        if not parts:
            abort(404)
        store = Store(host)
        row = store.get(parts[1])
        if not row or not secrets.compare_digest(parts[2], row["access_key"]):
            abort(404)
        return store,row

    @bp.route("/vtc/suivi/<key>", methods=["GET","POST"])
    def status(key):
        store,row = lookup(key)
        error = ""
        if request.method == "POST":
            check_csrf()
            try:
                with store.lock(row["id"]):
                    row=store.get(row["id"])
                    action=request.form.get("action")
                    if action=="verify" and row["stage"]=="verify":
                        row["stage"]={"cpf":"calendar","formation":"planning","vehicule":"availability" if row["exam_date"] else "billing"}[row["offer"]]
                        if row["stage"] == "planning" and row.get("slot") and agreements.locked(row):
                            row["stage"] = {"signed": "delivery", "stopped": "stopped"}.get(agreements.state(row), "contract")
                        elif row["stage"]=="planning" and row.get("selected_slot"):
                            slot=store.claim(row,earliest())
                            if slot:
                                row.update(slot=slot, stage="contract", agreement_state="queued")
                                if row.get("pdf_sha256"):
                                    agreements.generate(store, row)
                        row["verified_at"]=exam_retakes.now()
                    elif action=="withdraw" and row["stage"]!="withdrawn":
                        row["previous_stage"]=row["stage"]
                        row["stage"]="withdrawn"
                        row["withdrawn_at"]=exam_retakes.now()
                    elif action=="refresh" and row["stage"] in {"billing","contract"}:
                        if time.time() - row.get("last_refresh",0) < 30:
                            return redirect(url_for(".status",key=key),303)
                        row["last_refresh"]=time.time()
                    else:
                        return redirect(url_for(".status",key=key),303)
                    row["due"]=0
                    store.save(row)
                exam_retakes.wake_worker(host)
                return redirect(url_for(".status",key=key),303)
            except exam_retakes.RetakeError as exc:
                error=str(exc)
        return render("status",row=row,key=key,error=error,payment=payment_state(row),
                      docs=available_documents(store,row))

    @bp.get("/vtc/suivi/<key>/etat-paiement")
    def payment_progress(key):
        _, row = lookup(key)
        return {"state": payment_state(row)}

    @bp.get("/vtc/suivi/<key>/payer")
    def pay(key):
        _, row = lookup(key)
        if payment_state(row) == "ready":
            return redirect(safe_payment_url(row["payment_url"]), 303)
        return redirect(url_for(".status", key=key), 303)

    @bp.get("/vtc/suivi/<key>/<kind>.pdf")
    def pdf(key,kind):
        store,row=lookup(key)
        return download(store,row,kind)

    def staff():
        if host._is_external_partner_session() or host._current_partner_id() not in ("",host.INTEGRALE_PARTNER_ID):
            abort(403)

    @bp.get("/admin/commandes-vtc")
    @host.admin_login_required
    def admin():
        staff()
        page=max(0,request.args.get("page",0,type=int))
        store=Store(host)
        q = request.args.get("q", "").strip()[:160]
        offer = request.args.get("offer", "")
        stage = request.args.get("stage", "")
        filters = dict(q=q, offer=offer if offer in OFFERS else "", stage=stage if stage in STAGES else "")
        rows = store.recent(min(page, 1000000), q, filters["offer"], filters["stage"])
        return render("admin", rows=rows[:50], page=page, more=len(rows)>50, filters=filters, counts=store.offer_counts(),
                      error=request.args.get("message",""), slots=store.slots(earliest()),
                      slot_key=session.setdefault("vtc_slot_form",uuid.uuid4().hex))

    @bp.get("/admin/commandes-vtc/<oid>")
    @host.admin_login_required
    def detail(oid):
        staff()
        store = Store(host)
        row = store.get(oid)
        if not row:
            abort(404)
        return render("detail", row=row, docs=available_documents(store, row, admin=True),
                      agreement_locked=agreements.locked(row))

    @bp.post("/admin/commandes-vtc/creneaux")
    @host.admin_login_required
    @host.admin_write_required
    def publish():
        staff()
        check_csrf()
        store = Store(host)
        if request.form.get("close"):
            store.close_slot(request.form["close"])
            return redirect(url_for(".admin"),303)
        try:
            if request.form.get("draft") != session.get("vtc_slot_form") or not session.get("vtc_slot_form"):
                abort(400)
            slot=schedule(request.form,True)
            capacity=request.form.get("capacity",0,type=int)
            if not 1 <= capacity <= 12:
                raise ValueError("Indiquez de 1 à 12 places disponibles pour ces candidats.")
            store.publish(session.pop("vtc_slot_form"),slot,capacity)
            return redirect(url_for(".admin"),303)
        except ValueError as exc:
            return redirect(url_for(".admin",message=str(exc)),303)

    @bp.get("/admin/commandes-vtc/<oid>/conventions/<int:version>.pdf")
    @host.admin_login_required
    def archived_agreement(oid, version):
        staff()
        store = Store(host)
        row = store.get(oid)
        if not row or not any(item["version"] == version for item in row.get("agreement_history", [])):
            abort(404)
        archive = store.document(oid, "convention").with_suffix(f".v{version}.pdf")
        if not archive.is_file():
            abort(404)
        return send_file(archive, mimetype="application/pdf", as_attachment=True,
                         download_name=f"Convention-VTC-{oid[:10]}-v{version}.pdf")

    @bp.get("/admin/commandes-vtc/<oid>/<kind>.pdf")
    @host.admin_login_required
    def admin_pdf(oid,kind):
        staff()
        store=Store(host)
        row=store.get(oid)
        if not row:
            abort(404)
        return download(store, row, kind, admin=True)

    @bp.post("/admin/commandes-vtc/<oid>")
    @host.admin_login_required
    @host.admin_write_required
    def manage(oid):
        staff()
        check_csrf()
        store=Store(host)
        try:
            with store.lock(oid):
                row = store.get(oid)
                if not row:
                    abort(404)
                action = request.form.get("action", "")
                message, wake = manage_order(host, store, row, action, request.form)
                if wake:
                    row["due"] = 0
                store.save(row)
            if wake:
                exam_retakes.wake_worker(host)
            flash(message, "success")
        except ValueError as exc:
            flash(str(exc), "error")
        except Exception as exc:
            from werkzeug.exceptions import HTTPException
            if isinstance(exc, HTTPException):
                raise
            host.app.logger.warning("vtc_admin_action id=%s type=%s", oid, type(exc).__name__)
            flash(host._sanitize_qonto_error(host._sanitize_yousign_error(str(exc)))[:400]
                  or "La modification n’a pas pu être confirmée. Actualisez le dossier.", "error")
        return redirect(url_for(".detail", oid=oid), 303)
    app.register_blueprint(bp)


def read_slot(form, row):
    slot = schedule(form, row["offer"] == "formation")
    if row.get("exam_date") and row["exam_date"] < slot["day"]:
        raise ValueError("La formation doit précéder l’examen.")
    return slot


def set_slot(store, row, form):
    slot = read_slot(form, row)
    if row.get("selected_slot") and not store.matches_slot(row["selected_slot"], slot):
        row["_release_slot_id"] = row["selected_slot"]
        row["selected_slot"] = ""
    row["slot"] = slot


def reserve_selected_slot(store, row):
    if row.get("selected_slot"):
        earliest_day = (dt.date.fromisoformat(exam_retakes.today()) + dt.timedelta(days=15)).isoformat()
        if not store.claim(row, earliest_day):
            raise ValueError("Le créneau sélectionné est complet ou fermé. Renseignez un autre créneau avant l’envoi.")


def prepare_agreement(store, row, form):
    if agreements.locked(row) or row["stage"] == "withdrawn":
        raise ValueError("Cette convention est déjà engagée ou la commande a été annulée.")
    for key, limit in (("address", 160), ("zip_code", 12), ("city", 90)):
        if key in form:
            value = form[key].strip()
            if len(value) > limit or any(ord(c) < 32 for c in value):
                raise ValueError("Vérifiez l’adresse du candidat.")
            row["person"][key] = value
    if "exam_centre" in form:
        centre = form["exam_centre"]
        if centre and centre not in CENTRES:
            raise ValueError("Choisissez un centre d’examen proposé.")
        row["exam_centre"] = centre
    if "exam_date" in form:
        row["exam_date"] = exam_retakes.date_value(form["exam_date"], "Examen") if form["exam_date"] else ""
    if row["offer"] != "vehicule" and any(form.get(k) for k in ("day", "start", "end", "trainer")):
        # A reserved or historical slot can be printed again at its original date.
        if not all(form.get(k) == (row.get("slot") or {}).get(k) for k in ("day", "start", "end", "trainer")):
            set_slot(store, row, form)
    if row.get("slot") and row.get("exam_date") and row["exam_date"] < row["slot"]["day"]:
        raise ValueError("La formation doit précéder l’examen.")
    agreements.generate(store, row)
    row.update(agreement_state="draft", agreement_error="", agreement_generated_at=exam_retakes.now())


def manage_order(host, store, row, action, form):
    stage = row["stage"]
    state = agreements.state(row)
    if action == "generate":
        prepare_agreement(store, row, form)
        return "Convention générée. Vous pouvez vérifier le PDF avant l’envoi.", False
    if action == "send":
        if state in {"queued", "sent", "signed"}:
            return "La demande de signature est déjà enregistrée.", False
        if stage == "withdrawn" or state != "draft" or form.get("revision") != row.get("pdf_sha256"):
            raise ValueError("Rechargez et vérifiez la dernière convention générée avant l’envoi.")
        agreements.validate_for_signature(row)
        reserve_selected_slot(store, row)
        if row["offer"] == "formation" and stage == "planning":
            row["stage"] = "contract"
        row.update(agreement_state="queued", agreement_queued_at=exam_retakes.now())
        return "Envoi de la convention en signature demandé.", True
    if action == "restart":
        if form.get("confirm_restart") != "yes":
            raise ValueError("Confirmez la reprise de la convention.")
        agreements.restart(host, store, row, form.get("agreement_version", ""))
        return "Convention à nouveau modifiable. Vérifiez le document avant un nouvel envoi.", False
    if action == "remind" and state == "sent" and stage != "withdrawn":
        day = exam_retakes.today()
        if (row.get("emails", {}).get(agreements.delivery_key(row, "vtc-reminder-" + day)) or {}).get("sent_at"):
            return "La relance a déjà été envoyée aujourd’hui.", False
        row["agreement_reminder"] = day
        return "Relance de signature demandée.", True
    if action == "payment_method":
        changed = finance.set_method(host, row, form.get("payment_method"), agreements.locked(row))
        if changed and state == "draft":
            agreements.generate(store, row)
        return "Mode de paiement enregistré.", changed
    if action == "invoice" and stage == "billing" and finance.method(row) not in {"card", "cpf"}:
        row["invoice_requested"] = True
        return "Génération de la facture Qonto demandée.", True
    if action == "receive":
        finance.record_receipt(row, form)
        return "Encaissement enregistré. La facture sera rapprochée dans Qonto.", True
    if action == "schedule" and stage in {"planning", "calendar"}:
        personal = row["offer"] == "formation"
        if agreements.locked(row) or (row.get("slot") and not form.get("day")):
            if not row.get("slot"):
                raise ValueError("Renseignez un créneau de formation avant la validation.")
        else:
            set_slot(store, row, form)
        if not personal:
            ref = form.get("cpf_reference", "").strip()
            if not re.fullmatch(r"[0-9]{8,18}", ref) or form.get("funding_confirmed") != "yes":
                raise ValueError("Vérifiez le dossier accepté dans Mon Compte Formation et indiquez sa référence.")
            row["cpf_reference"] = ref
        if state == "draft":
            agreements.generate(store, row)
        row["stage"] = "contract" if personal else "funded"
        if personal:
            reserve_selected_slot(store, row)
            row["agreement_state"] = "queued"
        return "Créneau enregistré." if personal else "Prise en charge CPF enregistrée.", True
    if action == "available" and stage == "availability":
        row["stage"] = "billing"
        return "Disponibilité du véhicule confirmée.", True
    if action == "delivered" and stage == "delivery":
        limit = dt.date.fromisoformat(row["signed_day"]) + dt.timedelta(days=14)
        today = dt.date.fromisoformat(exam_retakes.today())
        if (today <= limit or row["slot"]["day"] > today.isoformat() or (row.get("exam_date") or "") > today.isoformat()
                or form.get("delivered") != "yes"):
            raise ValueError("Confirmez les deux prestations réalisées après expiration du délai de rétractation.")
        row.update(stage="billing", performed_at=exam_retakes.now(), days=[{"date":row["slot"]["day"]}])
        return "Prestations réalisées. Le règlement est ouvert.", True
    if action == "retry":
        return "Actualisation du dossier demandée.", True
    raise ValueError("L’état de ce dossier a changé. Rechargez la fiche.")


def available_documents(store, row, *, admin=False):
    kinds = {"convention": "Convention", "signed": "Convention signée", "vehicle": "Attestation véhicule",
             "invoice": "Facture", "completion": "Attestation de réalisation"}
    if not admin and not (row.get("request_id") or row.get("signed_day")):
        kinds.pop("convention")
    return {kind:label for kind,label in kinds.items() if store.document(row["id"],kind).is_file()}


def download(store, row, kind, *, admin=False):
    if kind not in available_documents(store, row, admin=admin):
        abort(404)
    return send_file(store.document(row["id"], kind), mimetype="application/pdf",
                     as_attachment=not (admin and request.args.get("apercu") == "1"),
                     download_name=f"VTC-{kind}-{row['id'][:10]}.pdf")
