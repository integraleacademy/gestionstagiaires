"""Keep issued training convocations in sync with their current source data."""
import copy
import fcntl
import hashlib
import json
import os
import re
import zipfile
from contextlib import contextmanager
from pathlib import Path


def source_hash(context, template_path):
    # The issue date alone must not force a new conversion every day.
    values = {key: value for key, value in context.items() if key != "date_jour"}
    digest = hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    digest.update(Path(template_path).read_bytes())
    return digest.hexdigest()


def current_source_hash(services, training, trainee):
    if services.vtc_individual_offers.is_vtc(training) and services.vtc_individual_offers.vehicle(trainee):
        return services.vtc_individual_offers.vehicle_hash(training, trainee)
    context = services._build_aps_convocation_context(copy.deepcopy(training), copy.deepcopy(trainee))
    template = services._ssiap_document_template(training, trainee, "convocation", services._aps_template_path)
    return source_hash(context, template)


@contextmanager
def generation_lock(directory):
    """Run at most one office converter across preview, delivery and scheduled jobs."""
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".conversion.lock").open("ab") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def cached_pair(directory, base, trainee, revision, is_pdf):
    """Find the current complete pair, including previously issued SSIAP/AFC files."""
    names = [base + ".pdf"]
    if trainee.get("convocation_aps_source_hash") == revision:
        previous = os.path.basename(str(trainee.get("convocation_aps_source_pdf_path") or ""))
        if re.fullmatch(re.escape(base) + r"_[0-9a-f]{12}_[0-9a-f]{8}\.pdf", previous):
            names.append(previous)
    for name in names:
        pdf = Path(directory) / name
        docx = pdf.with_suffix(".docx")
        if pdf.is_symlink() or docx.is_symlink() or not is_pdf(str(pdf)) or not docx.is_file():
            continue
        try:
            with zipfile.ZipFile(docx) as document:
                document.getinfo("word/document.xml")
        except (OSError, KeyError, zipfile.BadZipFile):
            continue
        return str(docx), str(pdf)
    return None


def owns_download(trainee, file_token):
    previous = trainee.get("convocation_aps_previous_pdf_tokens") or []
    return bool(file_token) and (
        file_token == trainee.get("convocation_aps_pdf_token")
        or (isinstance(previous, list) and file_token in previous)
    )


def remember_download(trainee):
    previous = trainee.get("convocation_aps_previous_pdf_tokens")
    previous = list(previous) if isinstance(previous, list) else []
    old_token = trainee.get("convocation_aps_pdf_token")
    if old_token and old_token not in previous:
        previous.append(old_token)
    trainee["convocation_aps_previous_pdf_tokens"] = previous


def existing_pdf(services, trainee):
    stored_path = str(trainee.get("convocation_aps_pdf_path") or "")
    stored_token = str(trainee.get("convocation_aps_pdf_token") or "")
    candidates = [stored_path] if stored_path else []
    if stored_token:
        candidates.append(services._detokenize_path(stored_token))
    for root in services._aps_convocation_allowed_pdf_roots():
        for source in (stored_path, stored_token):
            if source:
                candidates.append(os.path.join(root, os.path.basename(source)))
    return next((path for path in candidates
                 if services._aps_convocation_pdf_is_allowed(path) and services._is_pdf_file(path)), "")


def current_pdf(services, training, trainee, *, cached_only=False):
    """Refresh an issued PDF, without sending mail or changing signed documents."""
    if not services._public_convocation_has_record(trainee):
        raise FileNotFoundError("Aucune convocation n’a encore été émise.")
    pdf_path = existing_pdf(services, trainee)
    if (services._trainee_registration_is_cancelled(trainee)
            or not services._automation_document_config(training).get("convocation_template")):
        if pdf_path:
            return pdf_path
        raise FileNotFoundError("Cette convocation n’est plus disponible.")

    expected_hash = current_source_hash(services, training, trainee)
    source_pdf = str(trainee.get("convocation_aps_source_pdf_path") or "")
    if (pdf_path and trainee.get("convocation_aps_source_hash") == expected_hash
            and os.path.basename(source_pdf) == os.path.basename(pdf_path)):
        return pdf_path
    if cached_only:
        return None

    # No hash means an older PDF whose source data cannot be verified. Refresh
    # it once, too. Generate outside the data lock and on a detached record.
    rendered = copy.deepcopy(trainee)
    docx_path, pdf_path = services._generate_aps_convocation_files(
        copy.deepcopy(training), rendered, str(training.get("id") or ""), str(trainee.get("id") or ""),
    )
    if not services._aps_convocation_pdf_is_allowed(pdf_path) or not services._is_pdf_file(pdf_path):
        raise RuntimeError("Le PDF de convocation n’a pas pu être généré.")
    if rendered.get("convocation_aps_source_hash") != expected_hash:
        raise RuntimeError("Les informations ont changé pendant la préparation. Veuillez rouvrir la convocation.")

    def persist(data):
        current_training, trainees, current = services._find_session_trainee(
            data, str(training.get("id") or ""), str(trainee.get("id") or ""),
        )
        if (not current_training or not current
                or not services._public_convocation_has_record(current)
                or services._trainee_registration_is_cancelled(current)
                or current_source_hash(services, current_training, current) != expected_hash):
            raise RuntimeError("Les informations ont changé pendant la préparation. Veuillez rouvrir la convocation.")
        remember_download(current)
        current.update(
            convocation_aps_docx_path=docx_path,
            convocation_aps_pdf_path=pdf_path,
            convocation_aps_pdf_token=services._store_public_file_token(pdf_path),
            convocation_aps_source_hash=expected_hash,
            convocation_aps_source_pdf_path=pdf_path,
            convocation_aps_generated_at=services._now_iso(),
            convocation_aps_last_error="",
        )
        current_training["trainees"] = trainees
        current_training.pop("stagiaires", None)
        return {"pdf_path": pdf_path}

    # Persist only the document fields into the latest dossier. A slow office
    # conversion must never replace a session or trainee edited in the meantime.
    return services._atomic_update_data(persist)["pdf_path"]
