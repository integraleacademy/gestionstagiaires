"""Public VTC purchases, with Qonto collection and signed, practical-only agreements."""
import datetime as dt
import hashlib
import secrets
import os
import re
import time
import uuid
from html import escape
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, redirect, render_template, request, send_file, session, url_for

import exam_retakes
import exam_retakes_workflow as provider
from manuals_commerce import safe_payment_url
from vtc_order_documents import BOOKING, CMA, CONTACT, OFFERS, document
from vtc_order_store import Store

PARIS = ZoneInfo("Europe/Paris")
ORIGIN = (os.getenv("RENDER_EXTERNAL_URL") or "https://gestionstagiaires-r5no.onrender.com").rstrip("/")
STAGES = {"verify":"Adresse e-mail à confirmer", "calendar":"Rendez-vous CPF avec Cassandre",
          "planning":"Créneau de formation à fixer", "availability":"Créneau d’examen à confirmer",
          "contract":"Contrat à signer", "delivery":"Prestations à réaliser", "billing":"Paiement par carte",
          "paid":"Commande réglée", "funded":"Financement CPF enregistré", "withdrawn":"Annulation demandée",
          "stopped":"Signature interrompue"}


def token(row):
    return row["id"] + "." + row["access_key"]


def status_link(host, row):
    return ORIGIN + "/vtc/suivi/" + token(row)


def notify(host, store, row, key, subject, message, paths=()):
    link = status_link(host, row)
    def content(_host, _row, _key, _link):
        body = (f"<p>Bonjour {escape(row['person']['first_name'])},</p><p>{escape(message)}</p>"
                f'<p><a href="{escape(link, quote=True)}">Accéder à mon dossier VTC</a></p>'
                f"<p>{escape(CMA)}</p><p>Intégrale Academy · {escape(CONTACT)}</p>")
        return subject + " · Intégrale Academy", body, message + "\n" + link + "\n" + CMA + "\n" + CONTACT
    return provider.send_email(host, store, row, key, link, paths, content_builder=content)


def receipt(store, row):
    path = store.document(row["id"], "vehicle")
    if not path.is_file():
        document(row, path)
    return ("Attestation-vehicule-VTC.pdf", path)


def advance(host, store, row):
    stage = row["stage"]
    if stage == "verify":
        notify(host, store, row, "verify", "Confirmez votre adresse e-mail", "Ouvrez votre dossier puis confirmez votre adresse pour poursuivre votre demande VTC.")
    elif stage == "contract":
        path = store.document(row["id"], "convention")
        if not row.get("pdf_sha256"):
            field = document(row, path, contract=True)
            provider.checkpoint(store, row, signature_field=field, pdf_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        remote = provider.ensure_signature(host, store, row, name="Contrat de formation pratique VTC",
                                           prefix="vtc", filename="Contrat-formation-pratique-VTC.pdf", notify=False)
        if row.get("status") == "stopped":
            row["stage"] = "stopped"
        elif remote.get("status") in {"done","completed"}:
            signed = store.document(row["id"], "signed")
            if not signed.is_file():
                result = host._yousign_request("GET", "/signature_requests/"+row["request_id"]+"/documents/download",
                    params={"version":"completed","archive":"false"}, headers={"Accept":"application/pdf"})
                provider.store_pdf(signed, result.content)
            # Start the cooling-off period conservatively at the first verified completion.
            row.setdefault("signed_day", exam_retakes.today())
            notify(host, store, row, "signed", "Votre contrat de formation signé",
                   "Votre contrat signé et votre attestation de mise à disposition sont joints.",
                   [("Contrat-VTC-signe.pdf", signed), receipt(store,row)])
            row["stage"] = "delivery"
        else:
            notify(host,store,row,"signature","Votre contrat VTC est prêt","Consultez puis signez votre contrat en ligne.",[("Contrat-VTC.pdf",path)])
            return 180
    elif stage == "billing":
        if row["offer"] == "formation" and not store.document(row["id"],"completion").exists():
            document(row,store.document(row["id"],"completion"),completed=True)
        invoice = provider.ensure_invoice(host, store, row)
        provider.ensure_payment(host, store, row, invoice)
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
            if row.get("payment_url"):
                notify(host,store,row,"pay","Votre paiement par carte VTC","Votre lien sécurisé de règlement par carte est disponible dans votre dossier.")
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
                    wait = advance(host, store, row)
                    row["error"] = ""
                except Exception as exc:
                    wait = 180
                    row["error"] = host._sanitize_qonto_error(host._sanitize_yousign_error(str(exc)))[:400]
                    host.app.logger.warning("vtc_order_processing id=%s type=%s",oid,type(exc).__name__)
                row["due"] = -1 if wait < 0 else time.time()+wait
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
    day = form.get("exam_date","").strip()
    if day and exam_retakes.date_value(day,"Examen") < exam_retakes.today():
        raise ValueError("La date d’examen indiquée est passée.")
    if offer != "vehicule" and form.get("admissible") != "yes":
        raise ValueError("Confirmez votre admissibilité à l’épreuve pratique.")
    total = 15000 if offer=="vehicule" else 60000
    return {"id":oid, "access_key":secrets.token_urlsafe(32), "created":time.time(), "submitted_at":exam_retakes.now(), "offer":offer, "kind":"VTC pratique",
            "stage":"verify","status":"queued","person":person,"exam_date":day,"days":[],"accepted_at":exam_retakes.now(),
            "selected_slot":form.get("slot_id","")[:64] if offer=="formation" else "",
            "total_cents":total, "purchase_order":"VTC-"+oid, "invoice_title":OFFERS[offer],
            "billing_lines":[{"label":OFFERS[offer]+" – examen VTC","unit_cents":total,"total_cents":total,"quantity":1}],
            "vat_rate":"20" if offer=="vehicule" else "0", "vat_exemption":"" if offer=="vehicule" else "S261",
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
                               cma=CMA, booking=BOOKING, today=exam_retakes.today(), **values)

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
            exam_retakes.wake_worker(host)
        except ValueError as exc:
            return render("checkout",offer=offer,error=str(exc),slots=Store(host).slots(earliest()) if offer=="formation" else []),400
        return redirect(url_for(".sent",offer=offer),303)

    @bp.get("/vtc/commande/<offer>/confirmation")
    def sent(offer):
        if offer not in OFFERS:
            abort(404)
        # The email link is the only public access to the purchaser's details.
        session.pop("vtc_form_"+offer,None)
        return render("sent",offer=offer)

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
                        if row["stage"]=="planning" and row.get("selected_slot"):
                            slot=store.claim(row,earliest())
                            if slot:
                                row.update(slot=slot,stage="contract")
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
        return render("status",row=row,key=key,error=error,pay=safe_payment_url(row.get("payment_url")),
                      docs=available_documents(store,row))

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
        rows=store.recent(page)
        return render("admin",rows=rows[:50],page=page,more=len(rows)>50,error=request.args.get("message",""),
                      documents=lambda row: available_documents(store,row),slots=store.slots(earliest()),
                      slot_key=session.setdefault("vtc_slot_form",uuid.uuid4().hex))

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

    @bp.get("/admin/commandes-vtc/<oid>/<kind>.pdf")
    @host.admin_login_required
    def admin_pdf(oid,kind):
        staff()
        store=Store(host)
        row=store.get(oid)
        if not row:
            abort(404)
        return download(store,row,kind)

    @bp.post("/admin/commandes-vtc/<oid>")
    @host.admin_login_required
    @host.admin_write_required
    def manage(oid):
        staff()
        check_csrf()
        store=Store(host)
        message=""
        try:
            with store.lock(oid):
                row=store.get(oid)
                if not row:
                    abort(404)
                action=request.form.get("action")
                if action=="schedule" and row["stage"] in {"planning","calendar"}:
                    personal=row["offer"]=="formation"
                    row["slot"]=schedule(request.form,personal)
                    if row["exam_date"] and row["exam_date"] < row["slot"]["day"]:
                        raise ValueError("La formation doit précéder l’examen.")
                    if not personal:
                        ref=request.form.get("cpf_reference","").strip()
                        if not re.fullmatch(r"[0-9]{8,18}",ref) or request.form.get("funding_confirmed")!="yes":
                            raise ValueError("Vérifiez le dossier accepté dans Mon Compte Formation et indiquez sa référence.")
                        row["cpf_reference"]=ref
                    row["stage"]="contract" if personal else "funded"
                elif action=="available" and row["stage"]=="availability":
                    row["stage"]="billing"
                elif action=="delivered" and row["stage"]=="delivery":
                    limit=dt.date.fromisoformat(row["signed_day"])+dt.timedelta(days=14)
                    today=dt.date.fromisoformat(exam_retakes.today())
                    if today<=limit or row["slot"]["day"]>today.isoformat() or row["exam_date"]>today.isoformat() or request.form.get("delivered")!="yes":
                        raise ValueError("Confirmez les deux prestations réalisées après expiration du délai de rétractation.")
                    row["stage"]="billing"
                    row["performed_at"]=exam_retakes.now()
                    row["days"]=[{"date":row["slot"]["day"]}]
                elif action!="retry":
                    raise ValueError("L’état de ce dossier a changé. Actualisez le suivi.")
                row["due"]=0
                store.save(row)
            exam_retakes.wake_worker(host)
        except ValueError as exc:
            message=str(exc)
        return redirect(url_for(".admin",message=message),303)
    app.register_blueprint(bp)


def available_documents(store,row):
    kinds={"convention":"Contrat de formation","signed":"Contrat signé","vehicle":"Attestation véhicule","invoice":"Facture","completion":"Attestation de réalisation"}
    return {kind:label for kind,label in kinds.items() if store.document(row["id"],kind).is_file()}


def download(store,row,kind):
    if kind not in available_documents(store,row):
        abort(404)
    return send_file(store.document(row["id"],kind),mimetype="application/pdf",as_attachment=True,
                     download_name=f"VTC-{kind}-{row['id'][:10]}.pdf")
