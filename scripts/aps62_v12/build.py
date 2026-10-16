"""Build the immutable v12 edition from v11; never migrate learner records.

Run from the repository root: python -m scripts.aps62_v12.build
The dated courses and exams are written as a separate edition. Existing versions,
videos, captions and audio remain byte-for-byte unchanged.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from .content import (BLAST, CURRICULUM, CYBER, DATE, DIAGRAMS, ELECTRICAL,
                      LESSONS, NRBC, PNEUMOTHORAX, PREVIOUS, VERSION)
from .diagrams import write_diagrams
from .questions import FINAL12, MODULE12, WORDING
from .workshops import REPAIRS, apply_workshop_repairs

ROOT = Path(__file__).resolve().parents[2] / "elearning_native" / "aps62"
INDEPENDENT_CASE = "Nouvelle situation indépendante de l’exemple précédent. Appuyez-vous sur les faits décrits dans la question ci-dessous."
ELECTRICAL_OLD = "Reconnaissance par l'employeur de la capacité à effectuer certaines tâches électriques en sécurité."
ELECTRICAL_NEW = "Reconnaissance par l’employeur de la capacité à réaliser en sécurité les opérations confiées, électriques ou non, face au risque électrique."


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def activities(course):
    return [a for s in course["sections"] for a in s["activities"]]


def previous_digest():
    paths = sorted((ROOT / "courses").glob("*/" + PREVIOUS + ".json")) + sorted((ROOT / "exams" / PREVIOUS).glob("*.json"))
    assert len(paths) == 31, "The complete v11 source edition is required"
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(ROOT).as_posix().encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def replace_written(value, before, after):
    """Revise a definition without falsifying an existing video's transcript."""
    if isinstance(value, dict):
        return {k: v if k in {"video", "transcript"} else replace_written(v, before, after) for k, v in value.items()}
    if isinstance(value, list):
        return [replace_written(v, before, after) for v in value]
    if isinstance(value, str):
        return value.replace(before, after)
    return value


def set_single(question, prompt, correct, wrong1, wrong2, explanation):
    """Keep option IDs and the correct ID; never use display order as the key."""
    key = question.get("answer")
    if key is None:
        keys = [o["id"] for o in question["options"] if o.get("is_correct")]
        assert len(keys) == 1
        key = keys[0]
    wrong = iter([wrong1, wrong2])
    assert len(question["options"]) == 3
    for option in question["options"]:
        option["text"] = correct if option["id"] == key else next(wrong)
    question["prompt"] = prompt
    question["explanation"] = explanation


def update_exam(question, authored):
    prompt, correct, wrong1, wrong2, explanation, sources, competency = authored
    set_single(question, prompt, correct, wrong1, wrong2, explanation)
    question["sources"] = copy.deepcopy(sources)
    question["competency"] = competency
    question["assessment_origin"] = "independent-final-v12" if question["id"].startswith("aps62-final") else "module-v12-coverage"


def update_drill(exercise, context, prompt, correct, wrong1, wrong2, explanation, remediation):
    exercise["context"] = context
    set_single(exercise, prompt, correct, wrong1, wrong2, explanation)
    drill = exercise["remediation"]
    set_single(drill, *remediation)
    drill["lesson"] = "Relisez la fiche et les compléments écrits de ce dossier. Distinguez observation, incertitude, protection et alerte."


def enrich_module12(course):
    for section in course["sections"]:
        number = section["id"].replace("aps62-", "").replace("-", ".")
        if number not in LESSONS:
            continue
        authored = LESSONS[number]
        section["title"] = section["id"][-2:] + " · " + authored["title"]
        cards = [{"front": front, "back": back} for front, back in authored["cards"]]
        terms = [{"term": front, "definition": back} for front, back in authored["cards"]]
        lesson = next(a for a in section["activities"] if a.get("academy", {}).get("kind") == "lesson")
        lesson["title"] = "Le cours · " + authored["title"]
        academy = lesson["academy"]
        academy["title"] = authored["title"]
        academy["objectives"] = authored["objectives"]
        academy["deepening"] = [{"title": title, "paragraphs": paragraphs} for title, paragraphs in authored["parts"]]
        academy["visual_guide"]["title"] = authored["title"]
        academy["visual_guide"]["terms"] = terms
        academy["written_complement"] = {"edition": DATE, "scope": "Compléments écrits et fiches pédagogiques ; médias antérieurs conservés avec leur transcription originale."}
        if number in DIAGRAMS:
            academy["uniform_diagram"] = copy.deepcopy(DIAGRAMS[number])
            course["assets"].append(DIAGRAMS[number]["src"])
        for activity in section["activities"]:
            kind = activity.get("academy", {}).get("kind")
            if "easy_glossary" in activity:
                activity["easy_glossary"] = copy.deepcopy(terms)
            if kind in {"memory", "recap"}:
                activity["academy"]["cards"] = copy.deepcopy(cards)
            if kind == "memory":
                activity["academy"]["instruction"] = "Révisez les mots ci-dessous. La vidéo reprend les bases du dossier ; les notions ajoutées dans cette édition sont développées dans les compléments écrits et la fiche du cours."
            if kind == "recap":
                activity["academy"]["sources"] = copy.deepcopy(authored["sources"])
                activity["academy"]["decision"] = "Décrivez les faits avec leurs limites, protégez depuis une position sûre et transmettez au relais adapté. Les compléments écrits de ce dossier précisent les notions à reconnaître."
            if activity.get("question_type") == "matching":
                assert len(activity["pairs"]) == len(cards) == 3
                for pair, card in zip(activity["pairs"], cards):
                    pair.update(left=card["front"], right=card["back"])
                activity["explanation"] = " ".join(card["front"] + " : " + card["back"] for card in cards)
        academy["pacing"] = [{"label": a["title"], "minutes": a["planned_minutes"]} for a in section["activities"]]

    indexed = {a["id"]: a for a in activities(course)}
    set_single(indexed["aps62-12-02-q1"],
        "Depuis une position protégée, vous apercevez une crosse et une partie allongée ressemblant à une arme longue. Le modèle n’est pas identifiable. Quelle transmission est exacte ?",
        "Décrire une ressemblance avec une arme longue et les parties visibles, en précisant l’incertitude.",
        "Annoncer un modèle et un calibre précis à partir de la seule crosse.",
        "S’approcher de l’objet pour vérifier son état avant tout signalement.",
        "La reconnaissance de familles aide à décrire. Elle n’autorise ni identification certaine à partir d’une vue partielle ni approche destinée à lever le doute.")
    set_single(indexed["aps62-12-06-q1"],
        "Après des malaises signalés près d’une matière répandue, personne ne connaît la substance. Que signifie ici connaître les familles NRBC-E ?",
        "Comprendre les familles de dangers possibles tout en conservant l’incertitude et en appliquant la protection et l’alerte.",
        "Identifier automatiquement une substance précise à partir d’une toux.",
        "Déduire une intention terroriste certaine dès qu’un produit inconnu est présent.",
        "NRBC-E signifie nucléaire, radiologique, biologique, chimique et explosif. Cette classification ne remplace ni l’identification spécialisée ni l’établissement de la cause.")
    set_single(indexed["aps62-12-07-q1"],
        "Après une explosion, une personne en zone sûre décrit une douleur thoracique et une difficulté à respirer, sans plaie visible. Que transmettre ?",
        "Les signes décrits et le contexte de l’explosion, pour un relais médical urgent, sans diagnostic certain.",
        "Une absence de blessure parce que la peau ne présente pas de plaie visible.",
        "Un pneumothorax confirmé par l’APS à partir de ces deux signes seulement.",
        "Un pneumothorax ou une lésion liée au blast peut faire partie des risques à comprendre. Les signes imposent une alerte, mais ne suffisent pas à confirmer un diagnostic.")

    def application(sid):
        return next(e for e in indexed[f"aps62-{sid}-transfert"]["practice"]["exercises"] if e["id"] == "application")

    update_drill(application("12-02"),
        "Nouvelle situation : un objet ressemblant à une arme est découvert. Un tiers affirme que c’est un matériel factice ; aucun contrôle compétent ne l’a confirmé.",
        "Quelle limite conserver ?", "Ne pas le manipuler pour vérifier ; transmettre l’affirmation et suivre le relais prévu.",
        "Le prendre en main pour comparer son poids à celui d’un objet réel.",
        "Le déclarer inoffensif parce que le tiers paraît connaître ce matériel.",
        "Le statut factice se contrôle dans un cadre organisé. Une affirmation ne justifie pas une manipulation d’un objet découvert.",
        ("Dans une salle ouverte au public, un objet réaliste porte une marque de couleur. Cette marque suffit-elle à garantir un matériel factice ?", "Non ; son statut reste à confirmer sans manipulation par l’APS.", "Oui ; toute marque colorée garantit l’absence de danger.", "Oui ; il suffit de vérifier soi-même en actionnant l’objet.", "La couleur n’est pas une preuve technique. La conduite de protection reste guidée par le circuit prévu."))
    update_drill(application("12-06"),
        "Nouvelle situation : plusieurs occupants signalent une irritation près d’une matière répandue. La substance et la cause ne sont pas connues.",
        "Quelle réponse prépare un relais sûr ?", "Décrire les signes et les personnes exposées depuis une zone sûre, éviter de nouvelles expositions et alerter.",
        "Transporter la matière jusqu’au PC pour aider son identification.",
        "Faire sentir le produit à un collègue pour déterminer la substance.",
        "Les signes orientent l’alerte sans identifier la substance. Déplacement et recherche sensorielle peuvent créer une exposition supplémentaire.",
        ("Un colis ouvert est associé à des malaises rapportés. Un collègue propose un prélèvement avant d’appeler. Que retenir ?", "Alerter avec les faits disponibles sans prélèvement ni manipulation.", "Prélever d’abord pour ne transmettre que des certitudes.", "Transporter le colis dans une autre pièce occupée pour comparer les effets.", "Un bilan incomplet mais précis sur ses limites permet l’alerte sans ajouter d’exposition."))
    update_drill(application("12-07"),
        "Nouvelle situation : après une explosion, une personne a rejoint la zone sûre. Elle indique entendre moins bien et commence à respirer difficilement.",
        "Quelle information nouvelle transmettre ?", "Les troubles de l’audition et de la respiration après l’explosion, en demandant rapidement le relais médical.",
        "L’absence de blessure grave, puisqu’elle a pu marcher jusqu’à la zone sûre.",
        "Un diagnostic certain de blast pulmonaire posé par l’APS.",
        "Le souffle peut provoquer des lésions peu visibles. Les signes et leur évolution doivent être transmis sans diagnostic improvisé.",
        ("Une personne blessée par un projectile a une petite plaie et dit se sentir faible. Peut-on exclure une lésion interne grave ?", "Non ; décrire la plaie, la faiblesse et le contexte au relais médical.", "Oui ; une petite plaie garantit une blessure superficielle.", "Oui ; l’absence de projectile visible exclut une atteinte interne.", "L’aspect extérieur ne suffit pas à apprécier les lésions internes. Il faut alerter et transmettre les observations."))
    course["counts"]["assets"] = len(course["assets"])
    course["content_revision"] = VERSION


def build():
    before = previous_digest()
    report = {"version": VERSION, "reviewed_on": DATE, "previous_version": PREVIOUS,
              "previous_edition_sha256": before, "wording_repairs": [], "independent_workshop_contexts": [],
              "coverage_exam_questions": [], "course_question_changes": [], "workshop_wording_repairs": [], "section_budget_repairs": []}
    current_courses = []
    for path in sorted((ROOT / "courses").glob("*/" + PREVIOUS + ".json")):
        course = read(path)
        assert course["version"] == PREVIOUS
        course["version"] = VERSION
        course["interaction_revision"] = VERSION
        course["assessment_revision"] = VERSION
        course["source"]["reviewed_on"] = DATE
        for a in activities(course):
            if a.get("academy"):
                a["academy"]["edition"] = DATE
            if a.get("practice"):
                a["practice"]["revision"] = VERSION
                for e in a["practice"]["exercises"]:
                    if e["id"] == "application":
                        report["independent_workshop_contexts"].append({"activity": a["id"], "exercise": e["id"], "previous_context": e.get("context", "")})
                        e["context"] = INDEPENDENT_CASE
        if course["id"] == "academy-aps62-11":
            course = replace_written(course, ELECTRICAL_OLD, ELECTRICAL_NEW)
            first = course["sections"][0]
            lesson = next(a["academy"] for a in first["activities"] if a.get("academy", {}).get("kind") == "lesson")
            lesson["deepening"].insert(0, {"title": "Préciser le champ d’une habilitation électrique", "paragraphs": [ELECTRICAL_NEW, "Selon les opérations confiées, une habilitation peut concerner des opérations d’ordre électrique ou non électrique. Elle ne se déduit pas de la seule formation APS et n’autorise pas toute intervention. Le titre, les limites et la désignation par l’employeur se vérifient pour la tâche réelle."]})
            for a in first["activities"]:
                if a.get("academy", {}).get("kind") == "memory":
                    a["academy"]["instruction"] += " Le lexique écrit précise le champ de l’habilitation, qui peut aussi couvrir des opérations non électriques ; la capsule illustre notamment les tâches électriques."
                if a.get("academy", {}).get("kind") == "recap" and ELECTRICAL not in a["academy"]["sources"]:
                    a["academy"]["sources"].append(ELECTRICAL)
        if course["id"] == "academy-aps62-12":
            enrich_module12(course)
        apply_workshop_repairs(course, report["workshop_wording_repairs"])
        for section in course["sections"]:
            budget = sum(activity["planned_minutes"] for activity in section["activities"])
            if budget != section["planned_minutes"]:
                report["section_budget_repairs"].append({"section": section["id"], "previous_minutes": section["planned_minutes"], "minutes": budget})
                section["planned_minutes"] = budget
        old_by_id = {a["id"]: a for a in activities(read(path))}
        for a in activities(course):
            if a.get("type") == "question" and a != old_by_id[a["id"]]:
                report["course_question_changes"].append(a["id"])
        write(path.parent / (VERSION + ".json"), course)
        current_courses.append(course)

    for path in sorted((ROOT / "exams" / PREVIOUS).glob("*.json")):
        exam = read(path)
        exam.update(version=VERSION, reviewed_on=DATE, assessment_revision=VERSION)
        for q in exam["questions"]:
            if q["id"] in WORDING:
                spec = WORDING[q["id"]]
                old = copy.deepcopy(q)
                for field in ("prompt", "explanation"):
                    if field in spec:
                        q[field] = spec[field]
                for o in q["options"]:
                    if o["id"] in spec.get("options", {}):
                        o["text"] = spec["options"][o["id"]]
                    if o["id"] == q["answer"] and "answer_text" in spec:
                        o["text"] = spec["answer_text"]
                assert old != q, q["id"]
                report["wording_repairs"].append({"id": q["id"], "reason": spec["reason"], "previous_prompt": old["prompt"], "prompt": q["prompt"]})
            number = int(q["id"][-2:]) if path.name == "module-12.json" else None
            authored = MODULE12.get(number) if number else FINAL12.get(q["id"])
            if authored:
                update_exam(q, authored)
                report["coverage_exam_questions"].append(q["id"])
        write(ROOT / "exams" / VERSION / path.name, exam)

    assert len(report["wording_repairs"]) == len(WORDING)
    assert len(report["workshop_wording_repairs"]) == len(REPAIRS) + 1
    write_diagrams(ROOT)
    manifest = read(ROOT / "manifest.json")
    manifest["version"] = VERSION
    manifest["interaction_revision"] = VERSION
    for module in manifest["modules"]:
        module["version"] = VERSION
        module["previous_versions"] = list(dict.fromkeys([*module["previous_versions"], PREVIOUS]))
    manifest["exam_versions"] = list(dict.fromkeys([*manifest["exam_versions"], VERSION]))
    # Distinguish guided question workshops from authored productions.
    manifest["visual_learning"]["guided_workshops"] = sum(bool(a.get("practice") and a["practice"].get("mode") == "guided") for c in current_courses for a in activities(c))
    manifest["visual_learning"]["authored_on"] = DATE
    manifest["visual_learning"]["written_complement_diagrams"] = len(DIAGRAMS)
    manifest["content_review"] = {
        "edition": VERSION, "reviewed_on": DATE,
        "module12_written_sections_enriched": len(LESSONS),
        "module12_new_diagrams": len(DIAGRAMS),
        "exam_items_reviewed": 550, "course_questions_reviewed": 124,
        "workshop_exercises_reviewed": 364, "workshop_remediations_reviewed": 364,
        "exam_wording_repairs": len(WORDING),
        "exam_items_for_added_coverage": len(report["coverage_exam_questions"]),
        "independent_workshop_contexts": len(report["independent_workshop_contexts"]),
        "workshop_wording_repairs": len(report["workshop_wording_repairs"]),
        "section_budgets_reconciled": len(report["section_budget_repairs"]),
        "added_written_complement_words": sum(len(paragraph.split()) for lesson in LESSONS.values() for _, paragraphs in lesson["parts"] for paragraph in paragraphs),
        "report": "content_review_v12.json",
        "media": "62 vidéos existantes conservées ; compléments v12 dans les supports écrits, les fiches et les exercices.",
        "validation": "Relecture documentaire et contrôles techniques ; validation pédagogique par un formateur et mise à l’épreuve des durées encore à réaliser."
    }
    for source in [CURRICULUM, NRBC, CYBER, PNEUMOTHORAX, BLAST, ELECTRICAL]:
        if source not in manifest["sources"]:
            manifest["sources"].append(source)
    write(ROOT / "manifest.json", manifest)
    review = read(ROOT / "regulatory_review.json")
    review.update(checked_on=DATE, edition=VERSION)
    module12 = next(m for m in review["modules"] if m["id"] == "academy-aps62-12")
    module12["coverage"] = "Supports théoriques renforcés ; validation formateur requise"
    module12["objectives"] = "Modes d’action traditionnels et émergents, reconnaissance visuelle des familles de matériels, limites d’identification, NRBC-E et cyber, Vigipirate, vigilance factuelle, protection et alerte, lésions par balles et explosions, retour d’expérience."
    module12["review_note"] = "Édition v12 : quatre dossiers écrits enrichis, trois fiches SVG et évaluations ciblées. La reconnaissance porte sur les familles, les observations et les limites ; aucun procédé de fabrication, de déclenchement ou de neutralisation d’EEI n’est décrit. La revue documentaire ne remplace pas la validation par un formateur ni l’apprentissage pratique sur supports factices contrôlés. Le point du référentiel relatif au fonctionnement des EEI reste à traiter dans le cadre pédagogique sécurisé approprié ; sa couverture complète n’est pas attestée ici. TFP APS : 6 h 30 à distance. Les 6 h de pratique du programme ministériel de 13 h ne figurent pas dans ces 7 h."
    module12["v12_evidence"] = [{"section": "aps62-" + n.replace(".", "-"), "written_topics": [p[0] for p in data["parts"]], "diagram": DIAGRAMS.get(n, {}).get("src")} for n, data in LESSONS.items()]
    module12["trainer_validation"] = {"status": "pending", "checked_on": None, "scope": "Vérifier la reconnaissance des matériels sur supports factices contrôlés, les modalités sûres de traitement des points sensibles du référentiel et l’adéquation de la durée au public."}
    write(ROOT / "regulatory_review.json", review)
    report["counts"] = {
        "modules": len(current_courses),
        "sections": sum(len(c["sections"]) for c in current_courses),
        "activities": sum(len(activities(c)) for c in current_courses),
        "course_questions": sum(a.get("type") == "question" for c in current_courses for a in activities(c)),
        "practice_exercises": sum(len(a.get("practice", {}).get("exercises", [])) for c in current_courses for a in activities(c)),
        "planned_minutes": sum(c["planned_minutes"] for c in current_courses),
        "module12_minutes": next(c["planned_minutes"] for c in current_courses if c["id"] == "academy-aps62-12")
    }
    report["limits"] = ["Les 62 vidéos, leurs voix et leurs transcriptions n’ont pas été régénérées.", "Une revue éditoriale ne garantit pas l’absence absolue d’ambiguïté ; les remontées apprenants et formateurs restent nécessaires.", "Les durées restent un scénario pédagogique à éprouver ; aucune attestation de conformité globale ni validation pratique n’est délivrée par cette révision."]
    write(ROOT / "content_review_v12.json", report)
    assert previous_digest() == before, "Previous edition changed unexpectedly"
    print(json.dumps({"edition": VERSION, "counts": report["counts"], "wording_repairs": len(WORDING), "workshop_wording_repairs": len(report["workshop_wording_repairs"]), "coverage_exam_questions": len(report["coverage_exam_questions"]), "contexts_clarified": len(report["independent_workshop_contexts"]), "section_budgets_reconciled": len(report["section_budget_repairs"]), "course_question_changes": len(report["course_question_changes"]), "previous_edition_sha256": before}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    build()
