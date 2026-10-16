"""Original SVG teaching diagrams: silhouettes and conceptual anatomy only."""
from html import escape


def label(x, y, value, size=22, color="#17304d", weight=400):
    return f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" font-weight="{weight}">{escape(value)}</text>'


def lines(x, y, values, size=20, gap=29, color="#30445c"):
    return "".join(label(x, y + i * gap, value, size, color) for i, value in enumerate(values))


def rect(x, y, w, h, fill="#fff", stroke="#d7e2ef", radius=18):
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{radius}" fill="{fill}" stroke="{stroke}"/>'


def document(title, desc, height, body):
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="' + str(height) +
            '" viewBox="0 0 1200 ' + str(height) + '" role="img" aria-labelledby="title desc">'
            '<title id="title">' + escape(title) + '</title><desc id="desc">' + escape(desc) + '</desc>'
            '<rect width="1200" height="100%" fill="#f2f6fb"/>'
            '<g font-family="Arial, DejaVu Sans, sans-serif">' + body + '</g></svg>\n')


def weapons():
    body = label(42, 58, "Reconnaître une famille, décrire ce qui est visible", 34, weight=700)
    body += lines(42, 99, ["Silhouettes d’étude sans échelle. Aucun mécanisme ni maniement.",
                           "Sur le site : rester protégé, signaler les faits et les incertitudes."], 22)
    silhouettes = [
        ("1 · Pistolet", "Arme de poing compacte", "Partie supérieure allongée et poignée.",
         '<path d="M15 12 H285 V53 H132 L105 135 H55 L72 55 H15 Z" fill="#294a70"/>'),
        ("2 · Revolver", "Arme de poing compacte", "Barillet représenté dans la silhouette.",
         '<path d="M135 22 H330 V48 H144 L118 80 L92 130 H50 L75 61 H52 V20 H130 Z" fill="#294a70"/><circle cx="116" cy="45" r="34" fill="#52769e"/>'),
        ("3 · Fusil d’assaut", "Arme longue", "Crosse, poignée et chargeur saillant.",
         '<path d="M8 39 L78 30 V49 H141 V33 H208 L232 43 H350 V63 H238 L220 75 H204 L195 125 L159 114 L167 77 H146 L128 113 H107 L114 72 H74 L8 90 Z" fill="#294a70"/>'),
        ("4 · Fusil de chasse", "Exemple à deux canons", "D’autres modèles ont une autre forme.",
         '<path d="M5 55 L91 26 H142 V41 H350 V57 H148 L126 75 H88 L25 115 H5 Z" fill="#294a70"/><path d="M150 48 H350" stroke="#95b1d1" stroke-width="3"/>'),
        ("5 · Fusil à pompe", "Arme longue", "Garde-main représenté sous le canon.",
         '<path d="M5 62 L80 30 H156 V44 H355 V59 H175 V69 H146 L135 84 H94 L25 118 H5 Z" fill="#294a70"/><rect x="189" y="60" width="107" height="23" rx="5" fill="#52769e"/>'),
        ("6 · Lance-roquettes", "Exemple de silhouette tubulaire", "Un tube vu seul ne confirme pas une arme.",
         '<path d="M15 38 H325 L350 25 V95 L325 80 H15 Z" fill="#294a70"/><rect x="92" y="80" width="24" height="42" rx="4" fill="#294a70"/><path d="M185 80 L225 80 L220 108 L183 108 Z" fill="#52769e"/>')
    ]
    for i, (title, subtitle, caption, drawing) in enumerate(silhouettes):
        x, y = 40 + (i % 2) * 570, 160 + (i // 2) * 242
        body += rect(x, y, 550, 224)
        body += label(x + 22, y + 35, title, 25, weight=700)
        body += label(x + 22, y + 64, subtitle, 18, "#516780")
        body += f'<g transform="translate({x + 92} {y + 64}) scale(.72)">{drawing}</g>'
        body += label(x + 22, y + 200, caption, 18)
    body += rect(40, 901, 1120, 100, "#e5eefb", "#bbd0ed")
    body += lines(62, 934, ["À ne pas déduire : modèle exact, calibre, chargement, portée ou état de fonctionnement.",
                            "Matériel factice : statut contrôlé par le formateur ; une ressemblance n’est pas une garantie."], 20)
    body += label(42, 1040, "APS · Théorie de la prévention du terrorisme · Édition du 12 octobre 2026", 17, "#516780")
    return document("Familles de matériels : reconnaissance visuelle sûre", "Six silhouettes de familles d’armes, avec limites d’identification. Aucune manipulation n’est enseignée.", 1060, body)


def nrbc():
    body = label(42, 58, "NRBC-E et cyber : reconnaître les limites de l’observation", 31, weight=700)
    body += lines(42, 100, ["Un danger décrit ne prouve ni une intention malveillante ni l’identité d’une substance.",
                           "La protection dépend de la situation et des instructions des intervenants compétents."], 21)
    rows = [
        ("N", "Nucléaire", "Effets d’un événement nucléaire."),
        ("R", "Radiologique", "Rayonnements ou matières radioactives."),
        ("B", "Biologique", "Agents pouvant provoquer une maladie."),
        ("C", "Chimique", "Substances toxiques."),
        ("E", "Explosif", "Souffle, projections et effets associés.")
    ]
    for i, (letter, title, line) in enumerate(rows):
        y = 160 + i * 101
        body += rect(40, y, 627, 86)
        body += f'<circle cx="83" cy="{y + 43}" r="26" fill="#2657a0"/>'
        body += label(72, y + 52, letter, 29, "#fff", 700)
        body += label(124, y + 33, title, 23, weight=700)
        body += label(124, y + 63, line, 18)
    body += rect(689, 160, 470, 490, "#e9f1fc", "#bdd2ed")
    body += label(715, 202, "Cyber : vérifier avant d’agir", 26, weight=700)
    body += lines(715, 249, ["Une demande paraît officielle ?", "Le logo ne prouve pas son origine.", "", "Ne pas ouvrir le lien suspect.", "Ne pas transmettre de secret.", "Vérifier par un contact déjà connu.", "Alerter le circuit de l’organisme.", "", "Une panne ne prouve pas une attaque.", "Appliquer le mode dégradé validé."], 20, 33)
    body += rect(40, 680, 1120, 196, "#fff", "#bdd2ed")
    body += label(65, 721, "Ce qui aide le relais", 25, weight=700)
    body += lines(65, 760, ["Où et quand ?  Quels signes ?  Qui les a observés ?  Qui est exposé ?  Que reste-t-il inconnu ?",
                            "Protéger depuis une zone sûre ; ne pas toucher, prélever, sentir ou transporter une matière.",
                            "Pas de nettoyage ou de décontamination improvisés. Suivre les instructions adaptées."], 21, 37)
    body += label(42, 916, "APS · Théorie de la prévention du terrorisme · Édition du 12 octobre 2026", 17, "#516780")
    return document("NRBC-E et cyber : familles de dangers et alerte", "Définitions des cinq familles, vérification indépendante des messages et informations utiles à la protection et à l’alerte.", 940, body)


def injuries():
    body = label(42, 58, "Après une balle ou une explosion : comprendre et alerter", 32, weight=700)
    body += lines(42, 100, ["Une blessure grave peut être peu visible. Décrire les signes et leur évolution, sans diagnostic.",
                           "L’approche doit être sûre. Les gestes s’apprennent dans la formation pratique prévue."], 21)
    body += rect(40, 160, 1120, 328)
    body += label(64, 198, "Pneumothorax : présence d’air dans l’espace pleural", 27, weight=700)
    # Two conceptual cross sections: outer chest wall, pleural space, lung.
    body += '<ellipse cx="238" cy="335" rx="122" ry="103" fill="#eef3f9" stroke="#6e86a2" stroke-width="5"/>'
    body += '<ellipse cx="238" cy="335" rx="107" ry="90" fill="#8bc2db" stroke="#437da6" stroke-width="3"/>'
    body += label(125, 460, "Poumon déployé", 22, weight=700)
    body += '<ellipse cx="590" cy="335" rx="122" ry="103" fill="#fae6b8" stroke="#6e86a2" stroke-width="5"/>'
    body += '<ellipse cx="569" cy="335" rx="66" ry="75" fill="#8bc2db" stroke="#437da6" stroke-width="3"/>'
    body += label(477, 460, "Déploiement réduit", 22, weight=700)
    body += '<path d="M672 299 L758 266 H782" fill="none" stroke="#906926" stroke-width="3"/>'
    body += lines(796, 263, ["Air dans l’espace pleural", "entre poumon et paroi.", "", "Schéma de principe :", "il ne permet pas", "un diagnostic."], 20, 29)
    cards = [
        ("Hémorragie", ["Perte importante de sang.", "Elle peut être visible ou interne.", "Transmettre le saignement observé."]),
        ("Pneumothorax", ["Une respiration peut être gênée.", "Signaler douleur thoracique", "et difficulté à respirer."]),
        ("Blast", ["Le souffle peut léser des organes.", "Signaler aussi troubles respiratoires", "ou de l’audition après l’explosion."]),
        ("Projectiles et impacts", ["Fragments projetés, chute ou choc.", "L’aspect extérieur ne suffit pas", "à apprécier les lésions internes."])
    ]
    for i, (title, values) in enumerate(cards):
        x, y = 40 + (i % 2) * 570, 510 + (i // 2) * 167
        body += rect(x, y, 550, 149)
        body += label(x + 23, y + 35, title, 25, weight=700)
        body += lines(x + 23, y + 71, values, 21, 29)
    body += rect(40, 853, 1120, 108, "#e5eefb", "#bbd0ed")
    body += label(62, 888, "Alerte depuis la zone sûre", 24, weight=700)
    body += lines(62, 922, ["Lieu et accès · dangers · victimes comptées ou estimation précisée · signes · source · inconnues."], 20)
    body += label(42, 1000, "APS · Repères théoriques, sans gestes médicaux · Édition du 12 octobre 2026", 17, "#516780")
    return document("Blessures par balles et explosions : repères pour l’alerte", "Comparaison conceptuelle du déploiement d’un poumon, puis notions d’hémorragie, de pneumothorax, de blast et de projectiles. Aucun soin n’est représenté.", 1025, body)


def write_diagrams(root):
    target = root / "assets" / "media" / "aps62" / "v12"
    target.mkdir(parents=True, exist_ok=True)
    for filename, render in [("reconnaissance-materiels.svg", weapons), ("nrbc-cyber.svg", nrbc), ("blessures-alerte.svg", injuries)]:
        (target / filename).write_text(render(), encoding="utf-8")
