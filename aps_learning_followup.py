"""Read-only APS roster summaries and contextual, durable daily follow-up."""
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
import statistics
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


@contextmanager
def read_ledger(host):
    """Open the existing send archive without creating or changing it."""
    path = ledger_path(host)
    if not path.is_file():
        yield None
        return
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)) as db:
        db.row_factory = sqlite3.Row
        yield db


def sent_history(host, sid, tid):
    with read_ledger(host) as db:
        if db is None:
            return []
        return db.execute("""SELECT day, sent_at, recipient, subject FROM deliveries
            WHERE session_id=? AND trainee_id=? AND status='sent' ORDER BY day DESC""",
            (str(sid), str(tid))).fetchall()


def delivery(host, sid, tid, day):
    with read_ledger(host) as db:
        if db is None:
            return None
        row = db.execute('SELECT * FROM deliveries WHERE session_id=? AND trainee_id=? AND day=?',
                         (str(sid), str(tid), str(day))).fetchone()
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


MAIL_TITLE = 'Suivi de votre formation e-learning'
TIPS = ('Installez-vous au calme et prévoyez un créneau sans interruption.',
        'Reprenez à l’endroit où vous vous êtes arrêté : votre progression est enregistrée.',
        'Après une séquence, prenez quelques minutes pour reformuler les idées essentielles.',
        'Notez vos questions au fur et à mesure : notre équipe est là pour vous aider.',
        'Alternez les temps de concentration et les petites pauses pour rester disponible.',
        'Gardez un créneau chaque jour dans votre agenda pour votre formation.',
        'Terminez les activités et vérifiez les objectifs de temps de chaque module.')


def cohort_reports(host, training, day, *, reader=None, known=None):
    """Read each eligible learner once, including those already finished.

    A failed report is omitted, never interpreted as zero progress. The mapping
    remains internal; only anonymous aggregates reach an individual email.
    """
    reader = reader or ProgressReader(host)
    reports = dict(known or {})
    for peer in host._session_trainees_list(training):
        key = str(peer.get('id') or '')
        if not key or key in reports or not eligible(host, training, peer, day):
            continue
        try:
            reports[key] = read_summary(host, training, peer, reader=reader)
        except Exception:
            host.app.logger.exception('APS_DAILY cohort_report_unavailable session=%s trainee=%s', training['id'], key)
    return reports


def cohort_comparison(reports, person, report):
    comparable = []
    for key, peer in (reports or {}).items():
        if str(key) == str(person['id']) or not peer.get('available'):
            continue
        if any(peer.get(k) != report.get(k) for k in ('versions', 'required_seconds', 'total_activities')):
            continue
        value = peer.get('overall_percent')
        if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 100:
            continue
        comparable.append(peer)
    # Avoid individual comparisons or disclosing a lone peer's progress.
    if len(comparable) < 3:
        return None
    return {'count': len(comparable),
            'median': statistics.median(p['overall_percent'] for p in comparable),
            'completed': sum(bool(p.get('complete')) for p in comparable),
            'advanced': sum(p['overall_percent'] >= 80 and not p.get('complete') for p in comparable)}


def percent_label(value):
    return f'{value:g}'.replace('.', ',')


def assessment(training, report, day, cohort=None):
    """Deadline/workload outrank the cohort and any improvement since yesterday."""
    start, onsite = period(training)
    deadline = date(training.get('aps_remote_end'))
    if onsite:
        latest = onsite - dt.timedelta(days=1)
        deadline = min(deadline, latest) if deadline else latest
    valid_period = bool(start and deadline and start <= deadline)
    days = max(0, (deadline - day).days + 1) if valid_period else None
    not_started = bool(valid_period and day < start)
    first_day = bool(valid_period and day == start)
    remaining = max(0, math.ceil(report.get('remaining_seconds', 0)))
    percent = report.get('overall_percent')
    if not report.get('available') or percent is None or not math.isfinite(percent):
        raise ValueError('Le suivi est indisponible : aucun diagnostic ne peut être calculé.')
    expected = min(100, max(0, (day - start).days) / ((deadline - start).days + 1) * 100) if valid_period else None
    daily_seconds = math.ceil(remaining / days / 60) * 60 if days and not not_started else None
    lag = max(0, expected - percent) if expected is not None else 0
    peer_gap = cohort['median'] - percent if cohort else 0
    if report['complete']:
        tone = 'complete'
    elif not not_started and (days == 0 or (daily_seconds or 0) > 8 * 3600
                             or (days is not None and days <= 3 and percent < 50)):
        tone = 'critical'
    elif not not_started and ((daily_seconds or 0) > 6 * 3600
            or (days is not None and (days <= 1 or (days <= 3 and percent < 90)
                                     or (days <= 7 and percent < 50) or (days <= 14 and lag >= 30)))):
        tone = 'urgent'
    elif not not_started and not first_day and (lag > 10 or peer_gap >= 20):
        tone = 'behind'
    elif percent >= 75 and valid_period and not not_started:
        tone = 'advanced'
    else:
        tone = 'steady'
    return {'tone': tone, 'deadline': deadline if valid_period else None, 'days': days,
            'remaining': remaining, 'expected': expected, 'lag': lag, 'peer_gap': peer_gap,
            'daily_seconds': daily_seconds, 'not_started': not_started,
            'daily_feasible': daily_seconds is not None and daily_seconds <= 8 * 3600}


def message(host, training, person, report, day, *, cohort=None):
    _, onsite = period(training)
    comparison = cohort_comparison(cohort, person, report)
    state = assessment(training, report, day, comparison)
    tone, days, remaining = state['tone'], state['days'], state['remaining']
    percent = report['overall_percent']
    complete = report['complete']
    at_risk = tone in ('critical', 'urgent', 'behind')
    delta = progress_since_yesterday(host, training, person, report, day)
    deadline_label = state['deadline'].strftime('%d/%m/%Y') if state['deadline'] else 'à confirmer'
    progress_note = f"Vous avez terminé {percent_label(percent)} % de votre e-learning"
    if remaining:
        progress_note += f" et il vous reste {time_label(remaining)} de formation à effectuer"
    else:
        progress_note += '. Il vous reste des activités à terminer'
    if state['deadline'] and days and days > 0:
        progress_note += f' au plus tard le {deadline_label}'
    progress_note += '.'
    if complete:
        headline = 'Bravo, votre parcours est terminé !'
        encouragement = 'Vous avez validé les activités et les temps de suivi requis. Félicitations pour votre engagement ! Profitez des jours à venir pour revoir les notions qui vous seront utiles en présentiel.'
    elif tone == 'critical':
        headline = 'Alerte critique : votre e-learning risque de ne pas être terminé à temps'
        encouragement = ('L’échéance de votre e-learning est dépassée et votre parcours n’est pas validé. '
                         if days == 0 else
                         'Vous avez pris du retard dans votre formation. ')
        encouragement += progress_note + ' Contactez-nous dès aujourd’hui pour faire le point sur votre situation.'
    elif tone == 'urgent':
        headline = 'Alerte : votre e-learning doit devenir une priorité'
        encouragement = 'Vous risquez de ne pas terminer votre e-learning dans le délai prévu. Vous devez augmenter votre rythme de travail dès aujourd’hui et réserver des créneaux suffisants. Contactez-nous aujourd’hui si vous ne pouvez pas tenir ce rythme.'
    elif tone == 'behind':
        headline = 'Point de vigilance : votre progression demande une accélération'
        encouragement = 'Votre avancement demande davantage de travail pour atteindre la validation complète dans le délai prévu. Reprenez votre parcours aujourd’hui et planifiez les créneaux nécessaires. Signalez-nous rapidement toute difficulté.'
    elif tone == 'advanced':
        headline = 'Belle progression, gardez cet élan !'
        encouragement = 'Vous avez déjà accompli une grande partie du parcours. Bravo pour votre travail ! Continuez avec la même régularité et prenez le temps de finaliser les dernières activités et les objectifs de chaque module.'
    else:
        headline = 'Organisez votre travail jusqu’à la validation complète'
        encouragement = 'Consultez les activités et les temps requis de votre parcours, puis réservez des créneaux réguliers pour les terminer. Votre objectif reste la validation à 100 %.'
    offset = int(hashlib.sha256(str(person['id']).encode()).hexdigest()[:8], 16)
    ordinal = day.toordinal() + offset
    daily_note = ''
    if delta is None and not complete and report.get('active_seconds', 0) > 0:
        daily_note = f"Votre temps de suivi enregistré à ce jour est de {report['active_time_label']}."
    if delta and not complete:
        if delta['advanced'] and at_risk:
            daily_note = 'Une progression a été enregistrée depuis hier. Elle est prise en compte, mais elle ne suffit pas à lever l’alerte sur votre situation actuelle.'
        elif delta['advanced']:
            daily_note = 'Votre progression depuis hier est prise en compte. Poursuivez les activités et vérifiez les temps restant à valider dans chaque module.'
        else:
            daily_note = 'Aucune nouvelle activité ni durée de suivi n’a été enregistrée depuis le point d’hier.'
            daily_note += (' Le délai se réduit sans que le travail restant diminue : reprenez dès aujourd’hui et contactez-nous si vous êtes bloqué.'
                           if at_risk else ' Réservez votre prochain créneau de travail pour poursuivre votre parcours.')
            if tone == 'advanced':
                headline = 'Votre parcours est avancé : reprenez pour le finaliser'
                encouragement = 'Il reste des activités ou des temps de suivi à valider. Reprenez votre parcours pour les terminer avant l’échéance.'
    tip = ('Ouvrez votre parcours, identifiez les modules non validés et contactez-nous aujourd’hui pour convenir des prochaines étapes.'
           if tone in ('critical', 'urgent') else
           'Planifiez dès aujourd’hui vos prochains créneaux en tenant compte du temps restant à valider.' if tone == 'behind' else
           TIPS[(ordinal + ordinal // len(TIPS)) % len(TIPS)])
    evidence = []
    if not complete and tone != 'critical':
        evidence.append(progress_note)
    group_note = ''
    if comparison and not complete:
        group_note = (f"Parmi les {comparison['count']} autres stagiaires de votre session disposant d’un suivi comparable, "
                      f"{comparison['completed']} {'a validé son' if comparison['completed'] == 1 else 'ont validé leur'} parcours à 100 % "
                      f"et {comparison['advanced']} {'autre a' if comparison['advanced'] == 1 else 'autres ont'} atteint au moins 80 %. "
                      f"La progression médiane est de {percent_label(round(comparison['median'], 1))} %.")
        if state['peer_gap'] >= 20:
            group_note += ' Votre avancement se situe nettement en dessous de ce repère collectif.'
        group_note += ' Ce repère collectif ne remplace pas votre échéance personnelle.'
    if complete:
        workload_note = 'Votre parcours est validé à 100 % : aucun rattrapage n’est nécessaire.'
    elif state['not_started']:
        workload_note = 'La période de formation n’a pas encore commencé. Préparez vos créneaux de travail dès l’ouverture du parcours.'
    elif days is None:
        workload_note = 'La date limite doit être confirmée avec notre équipe ; aucun rythme quotidien fiable ne peut être calculé pour le moment.'
    elif days == 0:
        workload_note = 'L’échéance est dépassée : contactez-nous dès aujourd’hui. Un nouveau délai ne peut pas être considéré comme acquis.'
    elif not state['daily_feasible']:
        workload_note = (f"Il reste {days} jour{'s' if days > 1 else ''}, aujourd’hui inclus. Le calcul du temps restant représente plus de 8 heures par jour, "
                         'sans compter un éventuel temps supplémentaire pour les activités. Ce rythme ne constitue pas un planning raisonnable : contactez-nous dès aujourd’hui pour faire le point.')
    else:
        workload_note = (f"Il reste {days} jour{'s' if days > 1 else ''}, aujourd’hui inclus. Objectif indicatif par jour : {time_label(state['daily_seconds'])} de temps requis, "
                         'à compléter par toutes les activités non terminées. Ce calcul ne garantit pas à lui seul la validation du parcours.')
    origin = host.PUBLIC_STUDENT_PORTAL_BASE.rstrip('/')
    access_url = origin + '/espace/' + quote(str(person.get('public_token') or ''), safe='') + '/elearning'
    training_label = 'Votre formation agent de prévention et de sécurité (APS)'
    subject_note = {'critical': 'ALERTE CRITIQUE — action requise aujourd’hui',
                    'urgent': 'ALERTE — risque de ne pas terminer à temps',
                    'behind': 'VIGILANCE — progression à accélérer',
                    'complete': 'Parcours validé à 100 %'}.get(tone, 'Votre point de progression')
    subject = f"E-learning APS · {subject_note} · {day:%d/%m}"
    context = dict(first_name=str(person.get('first_name') or person.get('prenom') or '').strip(),
                   session_name=training.get('name') or training.get('nom') or 'Formation APS',
                   day_label=day.strftime('%d/%m/%Y'), onsite_label=onsite.strftime('%d/%m/%Y') if onsite else 'à confirmer',
                   encouragement=encouragement, tip=tip, tone=tone, at_risk=at_risk,
                   headline=headline, evidence=evidence, group_note=group_note,
                   deadline_label=deadline_label, workload_note=workload_note,
                   delta=delta, daily_note=daily_note,
                   report=report, percent_label=percent_label(percent), remaining_label=time_label(remaining),
                   days=days, access_url=access_url, complete=complete)
    fragment = host.app.jinja_env.get_template('emails/aps_daily_followup.html').render(**context)
    html = render_email(fragment, title=MAIL_TITLE, eyebrow=training_label,
                        subtitle=headline, signature='cassandre', preheader=f"{subject_note}. Progression : {percent_label(percent)} %. Échéance : {deadline_label}.")
    text = (f"{MAIL_TITLE}\n{headline}\n\nBonjour {context['first_name']},\n\n"
            + f"{encouragement}\n\n"
            + '\n'.join(evidence) + '\n'
            + (f"{daily_note}\n\n" if daily_note else '')
            + (f"Depuis le point d’hier : {delta['time_label']} de suivi supplémentaire, {delta['activities']} activité(s) terminée(s).\n" if delta and delta['advanced'] else '')
            + f"{context['session_name']} — Point du {context['day_label']}\n"
            f"Progression : {percent_label(percent)} %\nTemps suivi : {report['active_time_label']}\n"
            f"Temps restant requis : {context['remaining_label']}\n"
            f"Échéance e-learning : {deadline_label}. Présentiel le {context['onsite_label']}.\n"
            'Votre e-learning doit être terminé à 100 % avant le début des cours en présentiel.\n'
            + f"{workload_note}\n"
            + (f"\nOù en est votre groupe ?\n{group_note}\n" if group_note else '')
            + f"\n{tip}\nReprendre mon parcours : {access_url}\n\n"
            "Vous pouvez répondre à ce mail, m’appeler sur ma ligne directe au 04 87 83 06 16 "
            "ou sur mon portable au 07 43 58 22 64.\n"
            "Signaler un problème technique : ecole@integraleacademy.com\n\n"
            "Cassandre MENARD\nResponsable commerciale – Intégrale Academy\n"
            "04 22 47 07 68 · cassandre@integraleacademy.com\n54 chemin du Carreou – 83480 Puget-sur-Argens")
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
        reports = None
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
                if reports is None:
                    reports = cohort_reports(host, training, now.date(), reader=reader)
                report = reports.get(tid)
                if report is None:
                    counts['failed'] += 1
                    continue
                if not report['available']:
                    counts['failed'] += 1
                    continue
                content = message(host, training, person, report, now.date(), cohort=reports)
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

    def daily_learner(session_id, trainee_id):
        training = scoped_training(session_id)
        person = next((t for t in host._session_trainees_list(training) if str(t.get('id')) == trainee_id), None)
        if person is None or training.get('partner_id') not in (None, '', host.INTEGRALE_PARTNER_ID):
            abort(404)
        return training, person

    def mail_response(html):
        return html, 200, {'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store',
                           'Referrer-Policy': 'no-referrer', 'Content-Security-Policy': 'sandbox'}

    @app.get('/admin/sessions/<session_id>/stagiaires/<trainee_id>/e-learning/suivi/historique-mails/<day>')
    @host.admin_login_required
    def admin_aps_sent_mail(session_id, trainee_id, day):
        daily_learner(session_id, trainee_id)
        receipt = delivery(host, session_id, trainee_id, day)
        if not receipt or receipt['status'] != 'sent':
            abort(404)
        return mail_response(receipt['html'])

    @app.get('/admin/sessions/<session_id>/stagiaires/<trainee_id>/e-learning/suivi/mail-du-jour')
    @host.admin_login_required
    def admin_aps_daily_preview(session_id, trainee_id):
        training, person = daily_learner(session_id, trainee_id)
        today = clock().date()
        sent = delivery(host, session_id, trainee_id, today)
        if sent and sent['status'] in ('sent', 'sending', 'uncertain'):
            html = sent['html']
        else:
            report = read_summary(host, training, person)
            if not report['available']:
                abort(409, 'Le suivi est indisponible : aucun mail ne sera envoyé avec des données incomplètes.')
            reports = cohort_reports(host, training, today, known={str(person['id']): report})
            html = message(host, training, person, report, today, cohort=reports)['html']
        return mail_response(html)

    @app.post('/internal/cron/aps-daily-followup')
    def internal_cron_aps_daily_followup():
        expected = os.environ.get('CRON_SECRET', '').strip()
        provided = request.headers.get('X-Cron-Secret', '').strip()
        if not expected or not provided or not hmac.compare_digest(expected, provided):
            return jsonify(ok=False, error='forbidden'), 403
        result = run(host)
        return jsonify(result), 200 if result['ok'] else 502
