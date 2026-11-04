"""Read-only APS roster summaries and durable daily learner encouragement."""
from __future__ import annotations

import datetime as dt
from contextlib import closing, contextmanager
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import uuid
from urllib.parse import quote
from zoneinfo import ZoneInfo

from flask import abort, jsonify, render_template, request, url_for

from elearning_native.aps_enrolments import is_native_aps_session
from elearning_native.store import ACTIVE_SESSION_STALE_SECONDS
from elearning_reporting import ProgressReader, time_label
from trainee_elearning_reporting import source_for
from email_design import render_email

PARIS = ZoneInfo('Europe/Paris')
FIRST_DAY = dt.date(2026, 11, 4)


def clock(now=None):
    value = now or dt.datetime.now(PARIS)
    return (value.replace(tzinfo=PARIS) if value.tzinfo is None else value).astimezone(PARIS)


def date(value):
    try:
        return dt.date.fromisoformat(str(value or '')[:10])
    except ValueError:
        return None


def period(training):
    return (date(training.get('aps_remote_start') or training.get('date_start') or training.get('date_debut')),
            date(training.get('aps_in_person_start')))


def eligible(host, training, person, day):
    start, onsite = period(training)
    return bool(is_native_aps_session(training)
                and training.get('partner_id') in (None, '', host.INTEGRALE_PARTNER_ID)
                and not training.get('archived') and not training.get('cancelled')
                and not host._trainee_registration_is_cancelled(person)
                and start and onsite and start <= day < onsite and day >= FIRST_DAY)


def live_records(reader, session_id, now=None):
    """Only a fresh, active, non-ended tracking lease means LIVE."""
    if not reader.database_path.is_file():
        return set()
    epoch = clock(now).timestamp()
    try:
        with closing(sqlite3.connect(reader.database_path.as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
            rows = db.execute('''SELECT t.trainee_id, t.course_id, t.course_version
                FROM tracking_sessions t JOIN learner_course_progress p ON p.active_tracking_session_id = t.id
                WHERE t.session_id = ? AND t.ended_at IS NULL AND t.status = 'open'
                  AND t.was_active = 1 AND t.was_duplicate = 0
                  AND t.last_seen_epoch BETWEEN ? AND ? AND t.active_until_epoch >= ?''',
                (str(session_id), epoch - ACTIVE_SESSION_STALE_SECONDS, epoch, epoch)).fetchall()
        return set(rows)
    except sqlite3.Error:
        return None  # Do not turn a tracking outage into an assertion of absence.


def summary(report, person, live):
    percent = report.get('progress_percent')
    complete = bool(report.get('complete') and report.get('available'))
    # Required activities alone can reach 100 before the required study time.
    overall = (100 if complete else min(99.9, percent)) if percent is not None else None
    keys = {(str(person['id']), m['course_id'], m['version']) for m in report.get('modules', [])}
    final = report.get('final_exam_time')
    if final:
        keys.add((str(person['id']), final['course_id'], final['version']))
    return {**report, 'overall_percent': overall, 'complete': complete,
            'live': None if live is None else bool(keys & live),
            'remaining_time_label': time_label(report.get('remaining_seconds', 0))}


def read_summary(host, training, person, *, reader=None, live=None):
    reader = reader or ProgressReader(host)
    source, effective = source_for(training, person)
    report = reader.report(source, person, detailed=False, session_obj=effective)
    return summary(report, person, live)


def ledger_path(host):
    return Path(host.PERSIST_DIR) / 'native_elearning' / 'daily_followup.sqlite3'


def delivery(host, sid, tid, day):
    path = ledger_path(host)
    if not path.is_file():
        return None
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)) as db:
        db.row_factory = sqlite3.Row
        row = db.execute('SELECT * FROM deliveries WHERE session_id=? AND trainee_id=? AND day=?',
                         (str(sid), str(tid), day.isoformat())).fetchone()
        return dict(row) if row else None


@contextmanager
def connect_ledger(host):
    path = ledger_path(host)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.execute('''CREATE TABLE IF NOT EXISTS deliveries (
        session_id TEXT NOT NULL, trainee_id TEXT NOT NULL, day TEXT NOT NULL,
        status TEXT NOT NULL, recipient TEXT NOT NULL, subject TEXT NOT NULL, html TEXT NOT NULL,
        text TEXT NOT NULL, attempted_at TEXT NOT NULL, sent_at TEXT NOT NULL DEFAULT '',
        message_id TEXT NOT NULL DEFAULT '', attempts INTEGER NOT NULL DEFAULT 1,
        progress_json TEXT NOT NULL DEFAULT '{}',
        PRIMARY KEY(session_id, trainee_id, day))''')
    # Preserve all existing send receipts while adding tomorrow's comparison.
    with db:
        db.execute('BEGIN IMMEDIATE')
        if 'progress_json' not in {row[1] for row in db.execute('PRAGMA table_info(deliveries)')}:
            db.execute("ALTER TABLE deliveries ADD COLUMN progress_json TEXT NOT NULL DEFAULT '{}'")
    try:
        with db:
            yield db
    finally:
        db.close()


def claim(host, training, person, day, content, now):
    key = (str(training['id']), str(person['id']), day.isoformat())
    with connect_ledger(host) as db:
        db.execute('BEGIN IMMEDIATE')
        existing = db.execute('SELECT status, attempts FROM deliveries WHERE session_id=? AND trainee_id=? AND day=?', key).fetchone()
        # An interrupted/ambiguous send is never blindly replayed after a restart.
        if existing and (existing[0] != 'refused' or existing[1] >= 4):
            return False
        values = (person['email'].strip(), content['subject'], content['html'], content['text'], now.isoformat())
        if existing:
            db.execute('''UPDATE deliveries SET status='sending', recipient=?, subject=?, html=?, text=?,
                attempted_at=?, attempts=attempts+1 WHERE session_id=? AND trainee_id=? AND day=?''', values + key)
        else:
            db.execute('''INSERT INTO deliveries(session_id,trainee_id,day,status,recipient,subject,html,text,attempted_at)
                VALUES(?,?,?,'sending',?,?,?,?,?)''', key + values)
        db.execute('UPDATE deliveries SET progress_json=? WHERE session_id=? AND trainee_id=? AND day=?',
                   (json.dumps(content.get('progress', {})),) + key)
    return True


def progress_snapshot(report):
    return {key: report.get(key) for key in ('active_seconds', 'completed_activities',
            'total_activities', 'required_seconds', 'overall_percent', 'versions')}


def progress_since_yesterday(host, training, person, report, day):
    receipt = delivery(host, training['id'], person['id'], day - dt.timedelta(days=1))
    if not receipt or receipt['status'] != 'sent':
        return None
    try:
        before = json.loads(receipt.get('progress_json') or '{}')
        current = progress_snapshot(report)
        if any(current[k] != before.get(k) for k in ('total_activities', 'required_seconds', 'versions')):
            return None
        seconds = current['active_seconds'] - before['active_seconds']
        activities = current['completed_activities'] - before['completed_activities']
        if seconds < 0 or activities < 0:
            return None  # A correction or curriculum change is not inactivity.
        return {'advanced': seconds > 0 or activities > 0, 'seconds': seconds,
                'time_label': time_label(seconds), 'activities': activities}
    except (ValueError, KeyError, TypeError):
        return None


TITLES = ('Votre prochain pas vers le présentiel', 'Un nouveau jour pour avancer',
          'Votre régularité fait la différence', 'Gardez votre élan', 'Votre objectif se rapproche',
          'Construisez vos acquis, jour après jour', 'On fait le point sur votre parcours')
TIPS = ('Installez-vous au calme et prévoyez un créneau sans interruption.',
        'Reprenez à l’endroit où vous vous êtes arrêté : votre progression est enregistrée.',
        'Après une séquence, prenez quelques minutes pour reformuler les idées essentielles.',
        'Notez vos questions au fur et à mesure : notre équipe est là pour vous aider.',
        'Alternez les temps de concentration et les petites pauses pour rester disponible.',
        'Gardez un créneau chaque jour dans votre agenda pour votre formation.',
        'Terminez les activités et vérifiez les objectifs de temps de chaque module.')


def message(host, training, person, report, day):
    start, onsite = period(training)
    days = max(1, (onsite - day).days) if onsite else 1
    remaining = max(0, math.ceil(report.get('remaining_seconds', 0)))
    percent = report.get('overall_percent') or 0
    elapsed = max(0, (day - start).days) if start else 0
    expected = elapsed / max(1, (onsite - start).days) * 100 if onsite and start else 0
    daily_seconds = math.ceil(remaining / days / 60) * 60
    complete = report['complete']
    delta = progress_since_yesterday(host, training, person, report, day)
    if complete:
        tone, headline = 'complete', 'Bravo, votre parcours est terminé !'
        encouragement = 'Vous avez validé les activités et les temps de suivi requis. Félicitations pour votre engagement ! Profitez des jours à venir pour revoir les notions qui vous seront utiles en présentiel.'
    elif (days <= 3 and percent < 90) or daily_seconds > 6 * 3600:
        tone, headline = 'urgent', 'Le présentiel approche : avançons ensemble'
        encouragement = 'Il est important de vous mobiliser dès aujourd’hui pour terminer votre e-learning à temps. Réservez des créneaux réguliers et contactez-nous rapidement si vous avez besoin d’aide pour organiser la suite.'
    elif percent < max(10, expected - 10):
        tone, headline = 'behind', 'Chaque journée compte pour votre formation'
        encouragement = 'Votre e-learning demande une progression régulière. Commencez ou reprenez une séquence aujourd’hui, puis gardez ce rendez-vous chaque jour : c’est essentiel pour être prêt avant les cours en présentiel.'
    elif percent >= 75:
        tone, headline = 'advanced', 'Belle progression, gardez cet élan !'
        encouragement = 'Vous avez déjà accompli une grande partie du parcours. Bravo pour votre travail ! Continuez avec la même régularité et prenez le temps de finaliser les dernières activités et les objectifs de chaque module.'
    else:
        tone, headline = 'steady', 'Gardez un rendez-vous quotidien avec votre formation'
        encouragement = 'Les séquences réalisées construisent vos compétences pour le métier d’agent de prévention et de sécurité. Votre travail compte : gardez ce rythme et faites aujourd’hui un pas de plus vers la fin du parcours.'
    offset = int(hashlib.sha256(str(person['id']).encode()).hexdigest()[:8], 16)
    ordinal = day.toordinal() + offset
    daily_note = ''
    if delta is None and not complete and report.get('active_seconds', 0) > 0:
        daily_note = (f"Vous avez déjà consacré {report['active_time_label']} à votre parcours. "
                      'Bravo pour cet engagement ! Continuez à construire vos compétences, une séquence après l’autre.')
    if delta and not complete:
        if delta['advanced']:
            praise = ('Bravo pour le travail accompli depuis hier ! Chaque effort vous rapproche de votre objectif.',
                      'Félicitations, votre travail depuis hier porte ses fruits ! Continuez à avancer avec régularité.',
                      'Belle avancée depuis notre dernier point ! Vous construisez vos compétences, étape après étape.')
            daily_note = praise[ordinal % len(praise)]
        else:
            restart = ('Aucune nouvelle activité ni durée de suivi n’a été enregistrée depuis le point d’hier. Reprenons aujourd’hui : choisissez un créneau au calme et relancez votre prochaine séquence. Je suis là pour vous aider si quelque chose vous bloque.',
                       'Votre suivi n’a pas évolué depuis le point d’hier. C’est le bon moment pour reprendre : un créneau réservé aujourd’hui vous aidera à retrouver votre rythme. Contactez-moi si vous rencontrez une difficulté.',
                       'Nous n’avons pas enregistré de nouvelle avancée depuis hier. Ne laissez pas les séquences s’accumuler : reprenez votre parcours dès aujourd’hui, puis prévoyez un temps de travail chaque jour. Nous pouvons faire le point ensemble.')
            daily_note = restart[ordinal % len(restart)]
            if tone not in ('urgent', 'behind'):
                headline = 'Retrouvons votre rythme, une étape à la fois'
                encouragement = 'Vous avez déjà construit des acquis. Reprenez votre parcours aujourd’hui pour les consolider et poursuivre jusqu’à la validation complète avant le présentiel.'
    title = TITLES[ordinal % len(TITLES)]
    tip = TIPS[(ordinal + ordinal // len(TITLES)) % len(TIPS)]
    origin = host.PUBLIC_STUDENT_PORTAL_BASE.rstrip('/')
    access_url = origin + '/espace/' + quote(str(person.get('public_token') or ''), safe='') + '/elearning'
    training_label = 'Votre formation agent de prévention et de sécurité (APS)'
    subject = f"{training_label} · Votre point du {day:%d/%m}"
    context = dict(first_name=str(person.get('first_name') or person.get('prenom') or '').strip(),
                   session_name=training.get('name') or training.get('nom') or 'Formation APS',
                   day_label=day.strftime('%d/%m/%Y'), onsite_label=onsite.strftime('%d/%m/%Y') if onsite else 'à confirmer',
                   title=title, headline=headline, encouragement=encouragement, tip=tip, tone=tone,
                   training_label=training_label, delta=delta, daily_note=daily_note,
                   report=report, remaining_label=time_label(remaining), daily_label=time_label(daily_seconds),
                   days=days, access_url=access_url, complete=complete,
                   daily_feasible=daily_seconds <= 8 * 3600)
    fragment = host.app.jinja_env.get_template('emails/aps_daily_followup.html').render(**context)
    html = render_email(fragment, title=title, eyebrow=training_label,
                        subtitle=headline, signature='cassandre', preheader=f"Votre progression : {percent:g} %. Présentiel le {context['onsite_label']}.")
    text = (f"Bonjour {context['first_name']},\n\n{training_label}\n{headline}\n{daily_note}\n{encouragement}\n\n"
            + (f"Depuis le point d’hier : {delta['time_label']} de suivi supplémentaire, {delta['activities']} activité(s) terminée(s).\n" if delta and delta['advanced'] else '')
            + f"{context['session_name']} — Point du {context['day_label']}\n"
            f"Progression : {percent:g} %\nTemps suivi : {report['active_time_label']}\n"
            f"Temps restant requis : {context['remaining_label']}\n"
            f"Le e-learning doit être terminé avant le début du présentiel le {context['onsite_label']}.\n"
            + ('' if complete else f"Objectif indicatif par jour : {context['daily_label']}, sur {days} jour(s).\n"
               if context['daily_feasible'] else "Le volume restant est important au regard du délai : contactez-nous dès aujourd’hui pour faire le point et organiser la suite de votre parcours.\n")
            + f"\n{tip}\nReprendre mon parcours : {access_url}\n\n"
            "À la moindre difficulté, contactez-nous au 04 22 47 07 68. "
            "Signaler un problème technique : ecole@integraleacademy.com\n\n"
            "Cassandre MENARD\nResponsable commerciale · Intégrale Academy\n"
            "Ligne directe : 04 87 83 06 16\nPortable : 07 43 58 22 64\n"
            "cassandre@integraleacademy.com\n54 chemin du Carreou, 83480 Puget-sur-Argens")
    return {'subject': subject, 'html': html, 'text': text, 'tone': tone,
            'progress': progress_snapshot(report)}


def run(host, *, now=None):
    now = clock(now)
    if now.date() < FIRST_DAY or now.hour < 9 or now.hour >= 19:
        return {'ok': True, 'reason': 'outside_delivery_window', 'sent': 0}
    data = host.load_data(run_background_tasks=False)
    reader = ProgressReader(host)
    counts = {'ok': True, 'eligible': 0, 'sent': 0, 'skipped': 0, 'failed': 0, 'uncertain': 0}
    for training in data.get('sessions', []):
        for person in host._session_trainees_list(training):
            if not eligible(host, training, person, now.date()):
                continue
            counts['eligible'] += 1
            sid, tid = str(training['id']), str(person['id'])
            previous = delivery(host, sid, tid, now.date())
            if previous and previous['status'] != 'refused':
                counts['skipped'] += 1
                if previous['status'] in ('sending', 'uncertain'):
                    counts['uncertain'] += 1
                continue
            if not person.get('public_token') or not re.fullmatch(r'[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+', str(person.get('email') or '')):
                counts['failed'] += 1
                continue
            try:
                report = read_summary(host, training, person, reader=reader)
                if not report['available']:
                    counts['failed'] += 1
                    continue
                content = message(host, training, person, report, now.date())
                if not claim(host, training, person, now.date(), content, now):
                    counts['skipped'] += 1
                    continue
            except Exception:
                host.app.logger.exception('APS_DAILY preparation_failed session=%s trainee=%s', sid, tid)
                counts['failed'] += 1
                continue
            key = str(uuid.uuid5(uuid.NAMESPACE_URL, f'aps-daily:{sid}:{tid}:{now.date()}'))
            try:
                result = host.brevo_send_email(person['email'].strip(), content['subject'], content['html'],
                    text_content=content['text'], sender_name='Cassandre · Intégrale Academy',
                    reply_to={'email': 'cassandre@integraleacademy.com', 'name': 'Cassandre MENARD'},
                    metadata={'purpose': 'aps_daily_followup', 'idempotency_key': key, 'session_id': sid, 'trainee_id': tid})
                result = result if isinstance(result, dict) else {'ok': result is True}
            except Exception:
                result = {'ok': False}
            accepted = result.get('ok') is True
            code = result.get('status_code')
            refused = result.get('not_sent') is True or (isinstance(code, int) and 400 <= code < 500 and code != 408)
            status = 'sent' if accepted else 'refused' if refused else 'uncertain'
            with connect_ledger(host) as db:
                db.execute('UPDATE deliveries SET status=?,sent_at=?,message_id=? WHERE session_id=? AND trainee_id=? AND day=?',
                    (status, now.isoformat() if accepted else '', str(result.get('message_id') or ''), sid, tid, now.date().isoformat()))
            counts['sent' if accepted else 'failed' if refused else 'uncertain'] += 1
            if accepted:
                def record(current):
                    session = host.find_session(current, sid)
                    trainee = next((t for t in host._session_trainees_list(session or {}) if str(t.get('id')) == tid), None)
                    if trainee is not None:
                        history = trainee.setdefault('sent_email_history', [])
                        if not any(e.get('aps_daily_key') == key for e in history):
                            history.insert(0, {'to_email': person['email'], 'subject': content['subject'], 'html': content['html'],
                                               'sent_at': now.isoformat(), 'aps_daily_key': key})
                            trainee['sent_email_history'] = history[:200]
                    return {}
                host._atomic_update_data(record)
            host.app.logger.warning('APS_DAILY delivery session=%s trainee=%s day=%s status=%s', sid, tid, now.date(), status)
    counts['ok'] = not (counts['failed'] or counts['uncertain'])
    host.app.logger.warning('APS_DAILY summary day=%s eligible=%s sent=%s skipped=%s failed=%s uncertain=%s',
        now.date(), counts['eligible'], counts['sent'], counts['skipped'], counts['failed'], counts['uncertain'])
    return counts


def register(host):
    app = host.app

    def scoped_training(sid):
        training = host.find_session(host.load_data(run_background_tasks=False), sid)
        if not training or not is_native_aps_session(training):
            abort(404)
        owner = training.get('partner_id') or host.INTEGRALE_PARTNER_ID
        unrestricted = host._is_super_admin_session() and not host.session.get('assist_partner_id')
        if not unrestricted and owner != (host._current_partner_id() or host.INTEGRALE_PARTNER_ID):
            abort(404)
        return training

    @app.get('/admin/sessions/<session_id>/e-learning/aps-resume')
    @host.admin_login_required
    def admin_aps_learning_roster(session_id):
        training = scoped_training(session_id)
        reader = ProgressReader(host)
        live = live_records(reader, session_id)
        rows = {}
        for person in host._session_trainees_list(training):
            try:
                report = read_summary(host, training, person, reader=reader, live=live)
                rows[str(person['id'])] = render_template('_aps_learning_roster_cell.html', report=report,
                    report_url=url_for('manuals_shop.trainee_elearning_progress', session_id=session_id, trainee_id=person['id']))
            except (ValueError, OSError, sqlite3.Error):
                app.logger.exception('APS roster summary unavailable session=%s trainee=%s', session_id, person.get('id'))
                rows[str(person['id'])] = '<span class="aps-followup-empty">Suivi temporairement indisponible</span>'
        return jsonify(ok=True, rows=rows), 200, {'Cache-Control': 'no-store'}

    @app.get('/admin/sessions/<session_id>/stagiaires/<trainee_id>/e-learning/suivi/mail-du-jour')
    @host.admin_login_required
    def admin_aps_daily_preview(session_id, trainee_id):
        training = scoped_training(session_id)
        person = next((t for t in host._session_trainees_list(training) if str(t.get('id')) == trainee_id), None)
        if person is None or training.get('partner_id') not in (None, '', host.INTEGRALE_PARTNER_ID):
            abort(404)
        today = clock().date()
        sent = delivery(host, session_id, trainee_id, today)
        if sent and sent['status'] in ('sent', 'sending', 'uncertain'):
            html = sent['html']
        else:
            report = read_summary(host, training, person)
            if not report['available']:
                abort(409, 'Le suivi est indisponible : aucun mail ne sera envoyé avec des données incomplètes.')
            html = message(host, training, person, report, today)['html']
        return html, 200, {'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'}

    @app.post('/internal/cron/aps-daily-followup')
    def internal_cron_aps_daily_followup():
        expected = os.environ.get('CRON_SECRET', '').strip()
        provided = request.headers.get('X-Cron-Secret', '').strip()
        if not expected or not provided or not hmac.compare_digest(expected, provided):
            return jsonify(ok=False, error='forbidden'), 403
        result = run(host)
        return jsonify(result), 200 if result['ok'] else 502
