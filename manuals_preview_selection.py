"""Public editorial selections. Page numbers are one-based PDF positions.

Only these pages are exported; full source files stay outside the repository.
Gallery images come from the same selection and expose no additional pages.
"""

PREVIEW_SELECTIONS = {
    "ssiap1": {
        "source": "specimenssiap.pdf",
        "pages": [11, 12, 13, 25, 46, 61, 73, 83, 95, 97, 133, 141, 145, 157, 179, 187, 193, 205, 217, 253],
        "gallery": [(11, "Le métier en images"), (25, "La propagation du feu"), (253, "L’accueil des secours")],
        "watermarked": True,
    },
    "aps": {
        "source": "specimenaps.pdf",
        "pages": [11, 12, 25, 54, 55, 57, 73, 89, 104, 105, 121, 137, 169, 185, 201, 217, 233, 265, 281, 329],
        "gallery": [(73, "Rendre compte avec précision"), (201, "Préparer une ronde"), (329, "Un rapport exploitable")],
        "watermarked": True,
    },
    "a3p": {
        "source": "specimena3p.pdf",
        "pages": [11, 12, 23, 49, 51, 65, 66, 93, 99, 100, 107, 121, 133, 135, 157, 177, 205, 233, 247, 289],
        "gallery": [(11, "Une mission illustrée"), (177, "Préparer un déplacement"), (289, "Les repères de la mission")],
        "watermarked": True,
    },
    "vtc": {
        "source": "specimenvtc.pdf",
        "pages": [12, 14, 15, 49, 64, 65, 85, 97, 117, 118, 130, 138, 156, 193, 217, 241, 301, 334, 372, 397],
        "gallery": [(14, "Le métier en images"), (138, "Les distances de sécurité"), (117, "Un cas pratique de gestion")],
        "watermarked": True,
    },
    "dssp": {
        "source": "specimendssp.pdf",
        "pages": [12, 13, 29, 59, 109, 117, 121, 157, 158, 169, 181, 209, 214, 229, 269, 277, 309, 337, 369, 385],
        "gallery": [(277, "Préparer une équipe opérationnelle"), (157, "Décomposer un coût horaire"), (385, "Un plan d’actions de prévention")],
        "watermarked": True,
    },
    "sst": {
        "source": "specimensst.pdf",
        "pages": [6, 7, 8, 10, 12, 14, 16, 18, 19, 21, 23, 25, 27, 29, 30],
        "gallery": [(6, "Prévenir avant l’accident"), (10, "Transmettre une alerte"), (30, "Les repères à conserver")],
        "watermarked": True,
    },
    "ssiap2": {
        "source": "Manuel_SSIAP_2_264_pages.pdf",
        "pages": [11, 12, 13, 33, 38, 39, 68, 93, 131, 132, 133, 150, 151, 167, 185, 201, 211, 220, 221, 238],
        "gallery": [(11, "Encadrer et accompagner"), (151, "Comprendre les systèmes de sécurité"), (221, "Coordonner les transmissions")],
    },
    "ssiap1_recyclage": {
        "source": "Manuel_SSIAP1_Recyclage_Remise_a_niveau_64_pages.pdf",
        "pages": [10, 11, 12, 15, 17, 21, 24, 26, 27, 30, 33, 36, 38, 39, 42, 45, 51, 54, 57, 60],
        "gallery": [(17, "La prévention en images"), (30, "La chaîne de sécurité incendie"), (54, "Une mise en situation au PC")],
    },
    "mac_aps": {
        "source": "Manuel_MAC_APS_64_pages.pdf",
        "pages": [7, 8, 9, 12, 15, 18, 22, 23, 24, 28, 30, 33, 35, 36, 42, 45, 51, 54, 57, 60],
        "gallery": [(7, "Actualiser les repères"), (24, "Gérer une agression verbale"), (60, "Préparer la vacation")],
    },
    "bs_be": {
        "source": "Manuel_BS_BE_Manoeuvre_64_pages.pdf",
        "pages": [6, 8, 12, 15, 18, 20, 24, 27, 30, 34, 37, 40, 43, 44, 47, 50, 51, 54, 57, 60],
        "gallery": [(12, "Comprendre avant d’agir"), (8, "Distinguer les deux périmètres"), (51, "Rendre compte avec précision")],
    },
    "h0b0": {
        "source": "Manuel_H0B0_32_pages(1).pdf",
        "pages": [6, 7, 8, 11, 12, 14, 15, 16, 18, 20, 22, 23, 26, 28, 30],
        "gallery": [(6, "Identifier avant d’entrer"), (12, "Respecter les limites"), (30, "Les réflexes H0/B0")],
    },
    "mac_sst": {
        "source": "Manuel_MAC_SST_24_pages.pdf",
        "pages": [5, 6, 7, 8, 9, 10, 12, 14, 15, 16, 18, 19, 21, 22, 23],
        "gallery": [(6, "Observer le travail réel"), (9, "Repérer l’urgence et alerter"), (23, "Les réflexes du SST")],
    },
    "ssiap3": {
        "source": "Exemples_Pages_SSIAP_3_Recyclages_SSIAP_2_et_3.pdf",
        "pages": [1, 2, 3],
        "gallery": [(1, "Conseiller le chef d’établissement"), (2, "Analyser un risque incendie"), (3, "Construire le budget du service")],
        "examples": True,
    },
    "ssiap2_recyclage": {
        "source": "Exemples_Pages_SSIAP_3_Recyclages_SSIAP_2_et_3.pdf",
        "pages": [4, 5, 6],
        "gallery": [(4, "Coordonner depuis le PC"), (5, "Transmettre un message utile"), (6, "Animer une séance de formation")],
        "examples": True,
    },
    "ssiap3_recyclage": {
        "source": "Exemples_Pages_SSIAP_3_Recyclages_SSIAP_2_et_3.pdf",
        "pages": [7, 8, 9],
        "gallery": [(7, "Suivre la maintenance"), (8, "Du signalement à la clôture"), (9, "Analyser un projet d’aménagement")],
        "examples": True,
    },
}


def preview_filename(code):
    selection = PREVIEW_SELECTIONS[code]
    return f"manuals/specimens/{code}-{len(selection['pages'])}-pages.pdf"
