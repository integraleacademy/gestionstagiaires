"""Local ambiguity repairs found during review of all 364 workshop exercises."""

REPAIRS = {
    ("aps62-02-02-atelier", "constat"): {
        "answer_text": "Il s’éloigne ; aucun nouveau geste d’attaque n’est observé.",
        "reason": "Le cas décrit une tentative de coup ; éviter de transformer cette tentative en coups effectivement portés."
    },
    ("aps62-06-03-atelier", "constat"): {
        "prompt": "Avant de donner accès au contrôle annoncé, quelle qualité faut-il vérifier ?",
        "reason": "Cibler le préalable d’identité des contrôleurs, sans englober la vérification de tous les documents du poste."
    },
    ("aps62-07-04-transfert", "application"): {
        "prompt": "Après une insulte, quelle phrase associe l’explication de la procédure et une demande explicite de cesser les insultes, sans jugement sur la personne ?",
        "reason": "Expliciter les deux éléments attendus au lieu de comparer abstraitement plusieurs formulations de fermeté."
    },
    ("aps62-09-03-etude", "classement"): {
        "prompt": "Classez selon la nature de l’information et le moment où elle est connue.",
        "options": {"0": "Fait connu lors de la première décision", "1": "Changement observé pendant l’incident", "2": "Information sur le passé reçue après la décision"},
        "reason": "Une évolution observée est aussi une information apprise ensuite ; distinguer changement actuel et information sur le passé."
    },
    ("aps62-10-07-atelier", "constat"): {
        "prompt": "Quel point de sécurité doit encore être établi avant l’entrée du matériel dans la zone ?",
        "reason": "La facture et la préférence du propriétaire étaient également inconnues ; cibler l’adéquation de sécurité recherchée."
    },
    ("aps62-11-01-transfert", "variante"): {
        "answer_text": "Garder la protection car un voyant éteint ne prouve pas l’absence de tension.",
        "explanation": "L’état d’un voyant ne constitue pas une vérification d’absence de tension. La sécurité doit être établie par le personnel compétent selon la procédure adaptée.",
        "reason": "L’ancien corrigé parlait d’étincelles absentes alors que le cas fournit seulement l’état d’un voyant."
    },
    ("aps62-11-02-transfert", "variante"): {
        "prompt": "Quelle conduite retenir tant que la sécurité de toutes les sources d’énergie n’est pas confirmée ?",
        "reason": "Poser une question sur la conduite à tenir, conformément aux réponses proposées, au lieu de demander uniquement une information."
    },
    ("aps62-12-01-transfert", "application"): {
        "options": {"2": "Reprendre la qualification du témoin comme un fait confirmé pour accélérer la réponse."},
        "reason": "Citer une qualification rapportée peut être utile si elle est attribuée ; rendre explicite la fausse confirmation dans le distracteur."
    },
    ("aps62-12-04-transfert", "variante"): {
        "answer_text": "Tenir compte de la difficulté de compréhension établie, citer sa source et réviser l’interprétation devenue infondée.",
        "options": {"2": "Conserver l’interprétation initiale parce que la difficulté n’a été comprise qu’après le signalement.", "3": "Effacer toutes les observations pour ne plus conserver de trace du signalement initial."},
        "explanation": "Le nouvel élément du cas est la difficulté de compréhension, et non une autorisation d’accès. La trace conserve les observations, la source de l’explication et l’actualisation de l’analyse.",
        "reason": "L’ancien corrigé exigeait une autorisation vérifiée qui ne figurait pas dans le cas."
    },
    ("aps62-12-04-transfert", "application"): {
        "prompt": "Quelle formulation décrit un comportement directement observable sans lui attribuer une intention ?",
        "reason": "Un signalement peut aussi contenir une hypothèse attribuée ; cibler le fait directement observable évalué ici."
    },
    ("aps62-12-07-transfert", "variante"): {
        "answer_text": "Actualiser le bilan avec le lieu, les signes et la source de la nouvelle victime signalée, en faisant le lien avec le premier signalement.",
        "options": {"1": "Additionner automatiquement les signalements comme deux victimes certaines, sans vérifier s’ils concernent des personnes distinctes.", "2": "Utiliser le lieu de la première victime pour la nouvelle information jusqu’à une vérification complète."},
        "explanation": "Une victime supplémentaire rapportée ne prouve pas un nouvel incident. Les lieux et les sources restent distincts ; le bilan est actualisé en évitant les doubles comptes et en conservant les incertitudes.",
        "reason": "Le cas portait sur une nouvelle victime, mais l’ancien corrigé affirmait un nouvel incident."
    },
    ("aps62-14-02-atelier", "constat"): {
        "prompt": "Qu’observe l’agent à la sortie du magasin ?",
        "reason": "Le cas se déroule au portique de sortie, sans observation personnelle du passage en caisse."
    },
    ("aps62-14-04-atelier", "evolution"): {
        "answer_text": "Prendre immédiatement en compte la difficulté respiratoire, alerter les secours et réévaluer la contrainte.",
        "explanation": "Une difficulté respiratoire pendant une prise en charge impose de prendre en compte la santé sans attendre la fin des formalités. L’agent alerte les secours, réévalue les mesures et suit les instructions adaptées.",
        "reason": "Éviter qu’un « si nécessaire » permette de différer l’alerte face à une difficulté respiratoire exprimée pendant une contrainte."
    },
    ("aps62-14-07-etude", "choix-2"): {
        "prompt": "Quel résumé respecte la portée des deux déclarations ?",
        "reason": "Les réponses sont des résumés des pièces, alors que l’ancien énoncé demandait une action."
    },
    ("aps62-14-07-etude", "classement"): {
        "options": {"0": "Constat ou action de l’agent", "1": "Témoignage d’une autre personne", "2": "Conclusion non démontrée"},
        "reason": "Une déclaration est aussi une pièce du dossier ; préciser les catégories par la source évite leur recouvrement."
    },
    ("aps62-15-01-transfert", "application"): {
        "prompt": "Avant l’ouverture au public, le plan prévoit un accès sans responsable identifié au briefing. Quelle action retenir ?",
        "reason": "L’ancienne question parlait d’un accès déjà utilisé mais attendait une action avant l’ouverture ; fixer le moment du cas."
    },
    ("aps62-15-07-atelier", "constat"): {
        "answer_text": "Le lecteur affiche « déjà utilisé », sans que la cause de ce statut soit encore établie.",
        "reason": "Distinguer le message de l’outil d’une utilisation réellement confirmée par vérification."
    }
}


def apply_workshop_repairs(course, report):
    for section in course["sections"]:
        for activity in section["activities"]:
            for exercise in activity.get("practice", {}).get("exercises", []):
                repair = REPAIRS.get((activity["id"], exercise["id"]))
                if not repair:
                    continue
                for field in ("prompt", "explanation"):
                    if field in repair:
                        exercise[field] = repair[field]
                for option in exercise["options"]:
                    if option["id"] in repair.get("options", {}):
                        option["text"] = repair["options"][option["id"]]
                    if "answer_text" in repair and option["id"] == exercise.get("answer"):
                        option["text"] = repair["answer_text"]
                report.append({"activity": activity["id"], "exercise": exercise["id"], "reason": repair["reason"]})
                if activity["id"] in {"aps62-12-04-transfert", "aps62-12-07-transfert"} and exercise["id"] == "variante":
                    activity["academy"]["model"] = exercise["explanation"]
            if activity["id"] == "aps62-12-01-atelier":
                evolution = next(e for e in activity["practice"]["exercises"] if e["id"] == "evolution")
                evolution["remediation"]["prompt"] = "Une consigne arrive ensuite par le canal officiel identifié. Quelle référence appliquer ?"
            if activity["id"] == "aps62-15-07-etude":
                document = next(d for d in activity["practice"]["documents"] if d["title"] == "Consignes de coordination")
                document["rows"].extend([
                    ["File empiétant sur une issue", "Dans cet exercice, le premier relais est le responsable des flux."],
                    ["Obstacle sur l’accès S", "Dans cet exercice, le premier relais est le relais accès secours / dispositif."],
                    ["Demande d’extension d’un badge", "Dans cet exercice, le premier relais est le relais accréditation."]
                ])
                report.append({"activity": activity["id"], "exercise": "classement", "reason": "Préciser dans le dossier le premier relais par fonction ; sans cette consigne, plusieurs responsables pouvaient être sollicités légitimement."})
