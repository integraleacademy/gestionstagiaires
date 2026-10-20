"""Presentation and text alternative for the two jury messages."""
import datetime as dt
from pathlib import Path
from urllib.parse import quote, urlencode

from jinja2 import Environment, FileSystemLoader, select_autoescape

_templates = Environment(loader=FileSystemLoader(Path(__file__).parent / 'templates'),
                         autoescape=select_autoescape(['html']))
MONTHS = ('janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août',
          'septembre', 'octobre', 'novembre', 'décembre')
DAYS = ('Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche')


def render_mail(config, member, kind, count, logo_url):
    date = dt.date.fromisoformat(config['date'])
    day = DAYS[date.weekday()]
    long_date = f'{date.day} {MONTHS[date.month - 1]} {date.year}'
    numeric_date = date.strftime('%d/%m/%Y')
    reminder = kind == 'reminder'
    role = 'président du jury' if member['role'] == 'president' else 'membre du jury'
    subject = f"{'Rappel - Jury d’examen' if reminder else 'Jury - Examen'} {config['level']} du {numeric_date} à {config['time']}"
    intro = ('Votre jury d’examen approche. Voici les informations utiles pour votre participation'
             if reminder else 'Nous avons le plaisir de vous accueillir pour participer')
    intro += f" en qualité de {role} à l’examen {config['level']} organisé par Intégrale Academy."
    confirmation = ('Si vous nous avez déjà confirmé votre présence, aucune nouvelle confirmation n’est nécessaire.'
                    if reminder else 'Pour nous permettre de finaliser l’organisation, merci de nous confirmer votre présence en répondant à ce message.')
    action_label = 'Contacter le centre' if reminder else 'Confirmer ma présence'
    reply_subject = ('Question concernant' if reminder else 'Confirmation de présence au') + f" jury {config['level']} du {numeric_date}"
    action_url = 'mailto:' + quote(config['contact_email'], safe='@.') + '?' + urlencode({'subject': reply_subject}, quote_via=quote)
    lines = [f"Bonjour {member['first_name']} {member['last_name']},", '', intro, '',
             f'Date : {day} {long_date}', f"Début de l’examen : {config['time']}"]
    for key, label in [('arrival_time', 'Accueil du jury'), ('end_time', 'Fin prévisionnelle')]:
        if config[key]:
            lines.append(f'{label} : {config[key]}')
    lines += [f"Lieu : {config['location']}", config['address'], f'Candidats présentés : {count}']
    if config['instructions']:
        lines += ['', 'Informations pratiques', config['instructions']]
    lines += ['', confirmation, 'En cas d’empêchement ou de retard, merci de prévenir le centre dès que possible.',
              '', 'Merci pour votre participation et votre engagement auprès de nos candidats.', '',
              'Bien cordialement,', config['contact_name'], 'Intégrale Academy', config['contact_phone'], config['contact_email']]
    html = _templates.get_template('emails/ssiap_exam_jury.html').render(
        config=config, member=member, reminder=reminder, role=role, count=count, logo_url=logo_url,
        day=day, long_date=long_date, intro=intro, confirmation=confirmation,
        action_label=action_label, action_url=action_url,
        directions_url='https://www.google.com/maps/search/?' + urlencode({'api': '1', 'query': config['address']}),
        phone_url='tel:' + quote(config['contact_phone'].replace(' ', ''), safe='+'),
        preheader=f"{day} {long_date} à {config['time']} · {config['location']} · Toutes les informations pour votre venue.")
    return {'to': member['email'], 'subject': subject, 'html': html, 'text': '\n'.join(lines),
            'reply_to': {'email': config['contact_email'], 'name': config['contact_name']}}
