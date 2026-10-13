"""Teaching scenes shared by assigned APS editions, without changing activities."""
from __future__ import annotations

REVISION = '20261013-aps-illustrations'
PREFIX = 'media/aps62/v13/illustrations/'
SCENES = {
    'access': ('Un agent vérifie le badge d’un visiteur à l’entrée d’un site.',
               'Contrôle d’accès : vérifier les éléments prévus par la consigne.'),
    'conflict': ('Une agente écoute un visiteur mécontent, à distance, les mains ouvertes.',
                 'Dialogue : écouter, garder une posture calme et préserver une distance adaptée.'),
    'radio': ('Un agent transmet un message radio pendant que sa collègue repère un lieu sur le plan.',
              'Transmission : préciser le lieu, les faits observés et le besoin.'),
    'privacy': ('Une agente range un registre dans un tiroir, près d’un poste informatique verrouillé.',
                'Confidentialité : garder les informations dans les supports et espaces prévus.'),
    'briefing': ('Trois agents préparent leur prise de poste autour des consignes et du plan du site.',
                 'Prise de poste : partager les consignes, les rôles et les points de vigilance.'),
    'welcome': ('Une agente accueille plusieurs visiteurs, dont une personne en fauteuil roulant.',
                'Accueil : appliquer les mêmes règles avec respect, en tenant compte des besoins d’accès.'),
    'records': ('Un agent rédige un compte rendu pendant que sa collègue vérifie ses notes et l’heure.',
                'Traçabilité : noter les faits, les horaires et les actions réalisées.'),
    'hazards': ('Des agents maintiennent un passage sûr à distance d’un déversement dans un entrepôt.',
                'Prévention : distinguer la zone dangereuse du cheminement sûr.'),
    'electrical': ('Un agent empêche l’approche d’un câble endommagé près d’eau ; une collègue alerte à distance.',
                   'Danger électrique : rester à distance et empêcher une nouvelle exposition.'),
    'observation': ('Deux agents observent une porte endommagée sans la toucher et consignent leurs constats.',
                     'Observation : décrire ce qui est visible et préserver les lieux.'),
    'threat': ('Des agents et des visiteurs restent éloignés d’un sac isolé près d’un banc.',
               'Objet isolé : garder ses distances et appliquer la procédure d’alerte du site.'),
    'event': ('Deux agents organisent une file d’attente et maintiennent un passage dégagé.',
              'Gestion des flux : contrôler les accès tout en préservant la circulation.'),
    'handover': ('Un agent transmet un plan et ses observations à une intervenante des secours.',
                 'Relais aux secours : donner les informations utiles et faciliter leur accès.'),
}

# The three scenes accompany action, reasoning, then the decision sequence.
MODULE_SCENES = {
    '01': ('access', 'briefing', 'records'),
    '02': ('conflict', 'briefing', 'records'),
    '03': ('observation', 'radio', 'records'),
    '04': ('privacy', 'access', 'records'),
    '05': ('welcome', 'access', 'briefing'),
    '06': ('access', 'privacy', 'briefing'),
    '07': ('conflict', 'welcome', 'radio'),
    '08': ('radio', 'records', 'briefing'),
    '09': ('conflict', 'radio', 'records'),
    '10': ('hazards', 'briefing', 'radio'),
    '11': ('electrical', 'briefing', 'handover'),
    '12': ('threat', 'briefing', 'radio'),
    '13': ('records', 'privacy', 'briefing'),
    '14': ('observation', 'radio', 'records'),
    '15': ('event', 'access', 'briefing'),
}
LESSON_SCENES = {
    '02-03': ('hazards', 'electrical', 'handover'),
    '06-02': ('privacy', 'records', 'briefing'),
    '06-03': ('records', 'privacy', 'briefing'),
    '06-04': ('briefing', 'access', 'records'),
    '07-05': ('conflict', 'records', 'radio'),
    '08-01': ('briefing', 'access', 'records'),
    '08-03': ('records', 'observation', 'radio'),
    '08-04': ('observation', 'records', 'radio'),
    '08-05': ('briefing', 'records', 'radio'),
    '09-02': ('hazards', 'radio', 'handover'),
    '09-03': ('access', 'briefing', 'records'),
    '10-04': ('briefing', 'hazards', 'access'),
    '10-05': ('hazards', 'electrical', 'briefing'),
    '12-03': ('access', 'threat', 'briefing'),
    '12-04': ('observation', 'welcome', 'records'),
    '12-05': ('records', 'radio', 'briefing'),
    '12-06': ('hazards', 'privacy', 'radio'),
    '12-07': ('handover', 'radio', 'briefing'),
    '14-03': ('handover', 'briefing', 'radio'),
    '14-04': ('hazards', 'radio', 'briefing'),
    '14-07': ('observation', 'briefing', 'records'),
    '15-04': ('event', 'radio', 'briefing'),
    '15-05': ('event', 'radio', 'handover'),
    '15-06': ('handover', 'access', 'briefing'),
    '15-07': ('event', 'conflict', 'records'),
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
                lesson['illustrations'][slot] = dict(src=src, alt=alt, caption=caption)
                if src not in course['assets']:
                    course['assets'].append(src)
    course['illustration_revision'] = REVISION
    course.setdefault('counts', {})['assets'] = len(course['assets'])
    return course
