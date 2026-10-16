"""Reviewed factual and editorial corrections for the immutable APS v10 edition.

Both entry points return copies. They do not write a catalogue, change grading
identifiers, or claim that an old recording has been regenerated. The publisher
must render the changed scripts and attach the resulting media to the new course
edition. Historical Vigipirate examples outside 12-01 are deliberately retained.
"""
from copy import deepcopy

VERSION = "20261010-aps62-v10"
REVIEWED_ON = "2026-10-10"
VIDEO_CHANGED_IDS = frozenset({
    "aps62-03-02", "aps62-05-03", "aps62-06-04", "aps62-07-04", "aps62-12-01",
})
SOURCE_URLS = {
    "vigipirate": "https://www.sgdsn.gouv.fr/vigipirate",
    "article73": "https://www.legifrance.gouv.fr/codes/article_lc/LEGIARTI000029000766",
    "uniform": "https://www.legifrance.gouv.fr/loda/id/JORFTEXT000047866921/",
}

VIGIPIRATE_OLD = (
    "Les niveaux « vigilance », « sécurité renforcée – risque attentat » et « urgence attentat » "
    "s'accompagnent de mesures dont l'application dépend du contexte."
)
VIGIPIRATE_CURRENT = (
    "Les trois stades du plan Vigipirate publié en 2026 sont « vigilance », "
    "« vigilance renforcée » et « alerte attentat ». Les mesures à appliquer se vérifient "
    "dans la posture officielle en vigueur et sa déclinaison sur le site."
)
ARTICLE73_DOCUMENT = (
    "Repère juridique — CPP, article 73 : l'appréhension suppose un crime flagrant "
    "ou un délit flagrant puni d'emprisonnement. Une critique, à elle seule, "
    "ne démontre pas ces conditions."
)
BADGE_SITUATION = (
    "Lina, agent de sécurité, tient l'accueil d'un entrepôt. Le client exige qu'elle prête "
    "son badge nominatif à Maxime, intervenant d'une autre société, pour éviter une formalité."
)
BADGE_FACT = "Le client veut faire entrer Maxime avec le badge nominatif de Lina."
INITIAL_REPORT = "Transmission initiale : simple désaccord, sans mention des insultes entendues."
REPORT_RULE = (
    "Consigne : dater les paroles utiles et leur source ; compléter la transmission "
    "si de nouveaux faits surviennent."
)
TRANSMISSION_FACT = "Elle ne distingue pas l'observation de l'agent, le témoignage et le ticket."

UNIFORM_DIAGRAM = {
    "id": "aps62-tenue-20261010",
    "src": "media/aps62/v10/tenue-identification.svg",
    "title": "Vérifier une tenue de surveillance privée",
    "alt": (
        "Schéma de face et de dos : numéro individuel sur la poitrine en haut à gauche "
        "au porté, insigne de l'entreprise en dessous, mention SÉCURITÉ PRIVÉE "
        "sur une ligne au dos. Les détails et dimensions sont repris dans le texte du cours."
    ),
    "caption": "Exemple fictif, non à l'échelle. Numéro 1234567 et entreprise EXEMPLE fictifs. Vérification : 10 octobre 2026.",
    "source_title": "Arrêté du 18 juillet 2023, articles 1 à 4",
    "source_url": SOURCE_URLS["uniform"],
    "scope": "Cas présenté : surveillance privée ordinaire d'un entrepôt, avec port de la tenue requis.",
    "points": [
        {"label": "Numéro individuel", "position": "Poitrine, en haut à gauche au porté",
         "rule": "Sept derniers chiffres du NUB de la carte professionnelle ; Arial 36 ; bande de 54 × 15 mm ; noir sur blanc ou blanc sur noir."},
        {"label": "Insigne professionnel", "position": "Sous le numéro individuel",
         "rule": "Dénomination ou sigle de l'entreprise ou du service interne ; taille au moins égale à un carré de 50 mm de côté."},
        {"label": "Mention au dos", "position": "Au dos, centrée horizontalement, sur une seule ligne",
         "rule": "SÉCURITÉ PRIVÉE en majuscules Arial 76 rétro-réfléchissantes, blanches sur fond noir."},
        {"label": "Visibilité", "position": "Pendant toute la mission concernée",
         "rule": "Numéro et éléments communs visibles en permanence, y compris avec la veste ou le gilet porté."},
    ],
}

UNIFORM_LESSON = {
    "title": "Contrôler les mentions et leur emplacement sur une tenue ordinaire",
    "paragraphs": [
        "Dans ce cas, l'agent surveille un entrepôt avec port de la tenue requis. Le schéma est un exemple fictif, non à l'échelle. « À gauche au porté » désigne la gauche de la personne qui porte la tenue ; en la regardant de face, cette zone est à votre droite.",
        "Sur la poitrine, en haut à gauche au porté, le numéro individuel reprend les sept derniers chiffres du numéro unique de bénéficiaire, le NUB figurant sur la carte professionnelle. Il utilise des caractères Arial 36 sur une bande de 54 × 15 mm, noirs sur fond blanc ou blancs sur fond noir. Le nom personnel de l'agent ne remplace pas ce numéro.",
        "Sous le numéro se trouve l'insigne reproduisant la dénomination ou le sigle de l'entreprise, ou du service interne de sécurité. Quelle que soit sa forme, sa taille doit être au moins égale à un carré de 50 mm de côté. L'insigne ne prend donc pas la place du numéro.",
        "Au dos, la mention SÉCURITÉ PRIVÉE figure sur une seule ligne, centrée horizontalement. Les caractères sont des majuscules Arial 76 rétro-réfléchissantes, blanches sur fond noir. Un marquage sur deux lignes ne correspond pas à cette disposition.",
        "Vérifiez la tenue réellement portée : les éléments communs et le numéro doivent rester visibles en permanence. Une veste ou un gilet qui les masque appelle une correction avant le poste, même si le vêtement situé dessous est conforme. L'identification ne confère aucun pouvoir de police.",
        "Ces repères viennent des articles 1 à 3 de l'arrêté du 18 juillet 2023, vérifié le 10 octobre 2026. Vérifiez aussi le champ et les exceptions applicables à la mission : l'article 4 prévoit notamment que seul le numéro de l'article 2, 1°, s'applique aux personnes visées à l'article R. 213-5-2 du code de l'aviation civile. Ne transposez pas automatiquement cet exemple d'entrepôt à une autre activité.",
    ],
}

_PATCHES = {
    "aps62-03-02": (
        ("Le responsable veut retarder l'appel pour une raison commerciale.",
         "Le responsable demande de retarder l'appel jusqu'au retour du directeur."),
        ("Retarder l’appel à la police pour une raison commerciale.",
         "Attendre le retour du directeur avant d'appeler la police."),
    ),
    "aps62-05-03": (
        ("Repère civique : devise Liberté, Égalité, Fraternité ; drapeau tricolore ; hymne La Marseillaise.", ARTICLE73_DOCUMENT),
    ),
    "aps62-06-04": (
        ("Un donneur d'ordre exige que l'agent prête son badge nominatif à un intervenant d'une autre société pour éviter une formalité.", BADGE_SITUATION),
        ("La demande implique l'usage de l'identité d'un autre agent.", BADGE_FACT),
        ("Refuser d’utiliser l’identité d’un collègue. Garder le poste en sécurité et demander une solution autorisée à l’employeur.",
         "Refuser de prêter son badge nominatif. Garder le poste en sécurité et demander à l'employeur un accès attribué à Maxime."),
        ("Refuser le prêt, maintenir la sécurité du poste et demander une solution régulière à l'employeur.",
         "Refuser de prêter le badge, maintenir la sécurité du poste et demander un accès nominatif autorisé pour Maxime."),
    ),
    "aps62-07-04": (
        ("Transmission : simple désaccord, sans mention de la menace explicite.", INITIAL_REPORT),
        ("Consigne : rapporter exactement les paroles utiles en identifiant leur source.", REPORT_RULE),
        ("La première phrase vise le comportement et préserve le cadre.",
         "La réponse adaptée vise le comportement et préserve le cadre."),
    ),
    "aps62-12-01": ((VIGIPIRATE_OLD, VIGIPIRATE_CURRENT),),
    "aps62-14-06": (
        ("Elle mélange observations, témoignages et suppositions.", TRANSMISSION_FACT),
    ),
}


def _replace(value, replacements):
    if isinstance(value, str):
        for old, new in replacements:
            value = value.replace(old, new)
        return value
    if isinstance(value, list):
        return [_replace(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: _replace(item, replacements) for key, item in value.items()}
    return value


def _exercise(section, suffix, exercise_id):
    activity = next(a for a in section["activities"] if a["id"] == section["id"] + suffix)
    return next(e for e in activity["practice"]["exercises"] if e["id"] == exercise_id)


def _options(exercise, texts):
    if set(texts) != {item["id"] for item in exercise["options"]}:
        raise ValueError("Unexpected option IDs in content correction: " + exercise["id"])
    for item in exercise["options"]:
        item["text"] = texts[item["id"]]


def _add_source(section, title, url):
    recap = next(a["academy"] for a in section["activities"] if a["id"].endswith("-synthese"))
    sources = recap.setdefault("sources", [])
    if not any(source[1] == url for source in sources):
        sources.append([title, url])


def apply_course(course):
    """Correct one copied v9-derived course; publication/versioning is the caller's job."""
    result = deepcopy(course)
    for index, source_section in enumerate(result["sections"]):
        sid = source_section["id"]
        section = _replace(source_section, _PATCHES.get(sid, ()))
        result["sections"][index] = section
        if sid == "aps62-06-04":
            observed = _exercise(section, "-atelier", "constat")
            observed["prompt"] = "Si le badge était prêté, sous quelle identité Maxime entrerait-il ?"
            _options(observed, {
                "a": "Sous l'identité de Lina, titulaire du badge demandé.",
                "b": "Sous sa propre identité, déjà portée sur ce badge.",
                "v9-alternative": "Sous une identité commune autorisée pour l'équipe.",
            })
            observed["explanation"] = (
                "Le badge nominatif appartient à Lina. Maxime entrerait donc sous l'identité de Lina, "
                "et non sous la sienne. La demande du client ne transforme pas le badge en accès collectif."
            )
            decision = _exercise(section, "-atelier", "decision")
            _options(decision, {
                "1": "Prêter le badge en ajoutant le nom de Maxime dans une remarque.",
                "2": "Refuser le prêt et faire attribuer un accès autorisé à Maxime.",
                "v9-alternative": "Prêter le badge pour cette vacation afin de maintenir le service.",
            })
        elif sid == "aps62-03-02":
            observed = _exercise(section, "-atelier", "constat")
            _options(observed, {
                "a": "Attendre le retour du directeur avant d'appeler la police.",
                "b": "Prévenir la police maintenant et informer le directeur à son retour.",
                "v9-alternative": "Suivre une demande de la police qui aurait prescrit cette attente.",
            })
        elif sid == "aps62-14-06":
            observed = _exercise(section, "-atelier", "constat")
            _options(observed, {
                "a": TRANSMISSION_FACT,
                "b": "Elle attribue clairement chaque information à l'agent, au témoin ou au ticket.",
                "v9-alternative": "Elle reprend uniquement les faits constatés personnellement par l'agent.",
            })
        elif sid == "aps62-01-04":
            lesson = next(a["academy"] for a in section["activities"] if a["id"].endswith("-comprendre"))
            parts = lesson.setdefault("deepening", [])
            if not any(part["title"] == UNIFORM_LESSON["title"] for part in parts):
                parts.append(deepcopy(UNIFORM_LESSON))
            lesson["uniform_diagram"] = deepcopy(UNIFORM_DIAGRAM)
            lesson["objectives"] = [
                "Situer le numéro individuel, l'insigne professionnel et la mention dorsale sur une tenue de surveillance privée.",
                "Repérer un marquage masqué ou mal placé en comparant la tenue au champ réglementaire applicable.",
                "Décrire la correction à demander avant le poste sans se présenter comme un service public.",
            ]
            _add_source(section, "Arrêté du 18 juillet 2023 relatif aux tenues — articles 1 à 4", SOURCE_URLS["uniform"])
            result["assets"] = sorted(set(result.get("assets", [])) | {UNIFORM_DIAGRAM["src"]})
        if sid == "aps62-05-03":
            _add_source(section, "Code de procédure pénale — article 73", SOURCE_URLS["article73"])
        elif sid == "aps62-12-01":
            _add_source(section, "SGDSN — plan Vigipirate 2026 et posture en vigueur", SOURCE_URLS["vigipirate"])
    return result


def apply_video_scripts(rows):
    """Return corrected authored scripts for NEW recordings, without media metadata.

    Render these rows with the generation pipeline; do not copy revised text into
    a timed v7 manifest or VTT attached to an unchanged old MP4.
    """
    result = deepcopy(rows)
    for sid in VIDEO_CHANGED_IDS & result.keys():
        row = _replace(result[sid], _PATCHES[sid])
        if "src" in row or "duration_seconds" in row:
            raise ValueError("Expected authored scripts, not a timed media manifest: " + sid)
        row["transcript"] = "\n\n".join(scene["text"] for scene in row["scenes"])
        row["content_revision"] = VERSION
        result[sid] = row
    return result
