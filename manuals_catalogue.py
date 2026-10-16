"""Collection and TTC prices from the 21-page brochure supplied 12 October 2026.

Prices are integer cents, shared by the public showcase and server-side checkout.
The 50/100-copy thresholds apply per manual, not to the combined basket.
"""

CATEGORIES = (
    ("securite-privee", "Sécurité privée"),
    ("securite-incendie", "Sécurité incendie"),
    ("electricite", "Habilitations électriques"),
    ("transport", "Transport"),
    ("secourisme", "Secourisme"),
)


def _book(code, name, title, description, category, color, price, bulk_price, usb_price, page):
    return dict(code=code, name=name, title=title, description=description,
                category=category, category_name=dict(CATEGORIES)[category], color=color,
                price=price, bulk_price=bulk_price, usb_price=usb_price, brochure_page=page)


CATALOGUE = (
    _book("aps", "APS", "Agent de prévention et de sécurité",
          "Des situations professionnelles pour relier les cours aux missions quotidiennes de l’agent.",
          "securite-privee", "#2468b3", 2000, 1800, 19900, 5),
    _book("mac_aps", "MAC APS", "Maintien et actualisation des compétences APS",
          "Un manuel de 64 pages pour actualiser les repères et retravailler les situations du métier. Premiers secours dans le manuel dédié.",
          "securite-privee", "#2468b3", 1200, 1000, 9900, 6),
    _book("a3p", "A3P", "Protection physique des personnes",
          "Des missions illustrées et des schémas pour travailler les méthodes de protection.",
          "securite-privee", "#28795f", 2200, 2000, 19900, 7),
    _book("dssp", "DSSP", "Dirigeant d’une société de sécurité privée",
          "Des méthodes, calculs expliqués et fiches pour aborder la gestion d’une société de sécurité.",
          "securite-privee", "#d77824", 2200, 2000, 19900, 8),
    _book("ssiap1", "SSIAP 1", "Agent de sécurité incendie et d’assistance à personnes",
          "Des schémas et des situations illustrées pour rendre la sécurité incendie concrète.",
          "securite-incendie", "#c64042", 1700, 1500, 19900, 9),
    _book("ssiap2", "SSIAP 2", "Chef d’équipe de sécurité incendie et d’assistance à personnes",
          "Organiser, transmettre et coordonner : 264 pages illustrées pour les missions du chef d’équipe.",
          "securite-incendie", "#c64042", 1700, 1500, 19900, 10),
    _book("ssiap3", "SSIAP 3", "Chef de service de sécurité incendie et d’assistance à personnes",
          "Des repères pour analyser les risques, conseiller l’établissement et piloter le service de sécurité.",
          "securite-incendie", "#c64042", 2200, 2000, 19900, 11),
    _book("ssiap1_recyclage", "Recyclage / Remise à niveau SSIAP 1", "Actualisation des compétences de l’agent",
          "Un format de 64 pages pour réactiver les connaissances et retrouver les repères opérationnels de l’agent.",
          "securite-incendie", "#c64042", 1200, 1000, 9900, 12),
    _book("ssiap2_recyclage", "Recyclage / Remise à niveau SSIAP 2", "Encadrement et coordination de l’équipe",
          "Reprendre les missions du chef d’équipe et travailler la coordination du service en situation.",
          "securite-incendie", "#c64042", 1200, 1000, 9900, 13),
    _book("ssiap3_recyclage", "Recyclage / Remise à niveau SSIAP 3", "Analyse et pilotage du service",
          "Actualiser la lecture des risques et les méthodes de pilotage du chef de service de sécurité incendie.",
          "securite-incendie", "#c64042", 1200, 1000, 9900, 14),
    _book("h0b0", "H0B0", "Habilitation électrique du personnel non électricien",
          "32 pages pour comprendre le risque électrique et repérer les limites des opérations d’ordre non électrique.",
          "electricite", "#cc6b0a", 900, 800, 9900, 15),
    _book("bs_be", "BS-BE manœuvre", "Interventions élémentaires et manœuvres électriques",
          "64 pages pour distinguer les interventions élémentaires BS et les manœuvres BE, avec des repères concrets.",
          "electricite", "#cc6b0a", 1200, 1000, 9900, 16),
    _book("vtc", "VTC", "Voiture de transport avec chauffeur",
          "Un support structuré pour organiser les révisions et travailler les situations professionnelles.",
          "transport", "#7951a8", 2200, 2000, 19900, 17),
    _book("sst", "SST", "Sauveteur secouriste du travail",
          "32 pages de situations illustrées pour comprendre la prévention et accompagner l’apprentissage des premiers secours.",
          "secourisme", "#558538", 1200, 1000, 9900, 18),
    # The brochure lists a MAC SST manual, but no separate MAC SST USB product.
    _book("mac_sst", "MAC SST", "Maintien et actualisation des compétences SST · Pense-bête",
          "24 pages de révision avec un pense-bête à conserver pour réactiver les repères de prévention et de secours.",
          "secourisme", "#558538", 900, 800, None, 19),
)
