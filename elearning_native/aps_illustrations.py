"""Original manual illustrations shared by assigned APS editions.

Source pages and checksums are recorded in aps62/illustrations_manual_v14.json.
"""
from __future__ import annotations

REVISION = '20261013-aps-manual-illustrations'
PREFIX = 'media/aps62/v14/illustrations/'
SCENES = {
    'welcome': ('Un agent et un responsable accueillent une visiteuse à un comptoir.',
        'Accueil : expliquer le cadre de la mission et les règles applicables.'),
    'conflict': ('Une agente écoute un visiteur qui lui présente sa demande dans un hall.',
        'Dialogue : écouter, garder une posture calme et préserver une distance adaptée.'),
    'radio': ('Une agente utilise sa radio pendant qu’un homme lui indique un lieu dans un couloir.',
        'Transmission : préciser le lieu, les faits observés et le besoin.'),
    'coordination': ('Deux agents échangent devant un bâtiment ; l’un indique une direction.',
        'Coordination : partager les informations utiles avec l’équipe.'),
    'overview': ('Vue d’ensemble d’un site avec accueil, contrôle des accès, ronde et poste de surveillance.',
        'Organisation du site : relier les missions d’accueil, de surveillance et d’alerte.'),
    'monitoring': ('Une agente surveille plusieurs écrans au poste de sécurité.',
        'Poste de sécurité : utiliser les outils et les informations dans le cadre de la mission.'),
    'fire': ('Un agent observe des cartons et un chariot devant une double porte, près d’un extincteur.',
        'Prévention incendie : repérer les obstacles et préserver les dégagements.'),
    'industrial': ('Un agent en gilet de visibilité accueille deux intervenants avec leurs équipements.',
        'Intervenants extérieurs : vérifier les consignes et les risques avant l’accès au site.'),
    'observation': ('Une personne munie d’un dossier décrit une situation à un agent dans un magasin.',
        'Observation : recueillir les éléments utiles avant de décider.'),
    'threat': ('Un agent utilise sa radio dans un hall ; un sac isolé est visible près d’une porte.',
        'Objet isolé : garder ses distances et appliquer la procédure d’alerte du site.'),
    'patrol': ('Un agent effectue une ronde à la tombée de la nuit, radio en main.',
        'Ronde : observer les accès et signaler les anomalies rencontrées.'),
    'access': ('Une agente effectue un contrôle visuel d’un sac posé sur une table devant son propriétaire.',
        'Contrôle : informer la personne et respecter le cadre autorisé.'),
    'alarm': ('Deux agents vérifient un équipement près d’une porte donnant sur un escalier.',
        'Alarme : vérifier les informations disponibles et organiser la réponse prévue.'),
    'event': ('Une agente organise l’accueil d’une file de visiteurs entre des barrières de guidage.',
        'Gestion des flux : contrôler les accès tout en préservant la circulation.'),
    'support': ('Une agente dialogue avec un visiteur au comptoir ; un collègue reste à proximité.',
        'Appui de l’équipe : garder une communication calme et solliciter un relais si nécessaire.'),
}

# The three scenes accompany action, reasoning, then the decision sequence.
MODULE_SCENES = {
    '01': ('welcome', 'overview', 'coordination'),
    '02': ('conflict', 'observation', 'radio'),
    '03': ('observation', 'patrol', 'radio'),
    '04': ('monitoring', 'welcome', 'coordination'),
    '05': ('welcome', 'conflict', 'support'),
    '06': ('welcome', 'monitoring', 'coordination'),
    '07': ('conflict', 'support', 'radio'),
    '08': ('radio', 'monitoring', 'coordination'),
    '09': ('conflict', 'observation', 'radio'),
    '10': ('industrial', 'overview', 'coordination'),
    '11': ('industrial', 'coordination', 'radio'),
    '12': ('threat', 'patrol', 'radio'),
    '13': ('monitoring', 'radio', 'coordination'),
    '14': ('observation', 'patrol', 'radio'),
    '15': ('event', 'access', 'coordination'),
}
LESSON_SCENES = {
    '02-03': ('radio', 'industrial', 'coordination'),
    '06-02': ('monitoring', 'support', 'coordination'),
    '06-03': ('welcome', 'overview', 'coordination'),
    '06-04': ('coordination', 'welcome', 'radio'),
    '07-05': ('support', 'observation', 'radio'),
    '08-01': ('coordination', 'overview', 'radio'),
    '08-03': ('monitoring', 'observation', 'radio'),
    '08-04': ('observation', 'monitoring', 'radio'),
    '08-05': ('coordination', 'monitoring', 'radio'),
    '09-02': ('radio', 'industrial', 'coordination'),
    '09-03': ('welcome', 'access', 'coordination'),
    '10-04': ('industrial', 'overview', 'radio'),
    '10-05': ('industrial', 'fire', 'coordination'),
    '12-03': ('access', 'threat', 'coordination'),
    '12-04': ('observation', 'welcome', 'patrol'),
    '12-05': ('monitoring', 'radio', 'coordination'),
    '12-06': ('industrial', 'monitoring', 'radio'),
    '12-07': ('radio', 'coordination', 'overview'),
    '14-02': ('alarm', 'observation', 'radio'),
    '14-03': ('fire', 'alarm', 'radio'),
    '14-04': ('observation', 'radio', 'coordination'),
    '14-07': ('observation', 'alarm', 'coordination'),
    '15-04': ('event', 'overview', 'radio'),
    '15-05': ('event', 'radio', 'coordination'),
    '15-06': ('welcome', 'industrial', 'coordination'),
    '15-07': ('event', 'conflict', 'support'),
}


def illustrate_course(course):
    for section in course['sections']:
        ref = section['id'].removeprefix('aps62-')
        keys = LESSON_SCENES.get(ref, MODULE_SCENES.get(ref[:2], ()))
        for activity in section['activities']:
            lesson = activity.get('academy', {})
            if lesson.get('kind') != 'lesson':
                continue
            lesson['illustrations'] = {}
            for slot, key in zip(('action', 'reason', 'flow'), keys):
                alt, caption = SCENES[key]
                src = PREFIX + key + '.webp'
                width, height = (1536, 1024) if key in ('coordination', 'overview') else (1122, 1402)
                lesson['illustrations'][slot] = dict(
                    src=src, alt=alt, caption=caption, width=width, height=height)
                if src not in course['assets']:
                    course['assets'].append(src)
    course['illustration_revision'] = REVISION
    course.setdefault('counts', {})['assets'] = len(course['assets'])
    return course
