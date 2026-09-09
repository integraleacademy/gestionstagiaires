"""Contenu du guide envoyé après validation du devis VTC."""

import html


def build_confirmation_content(fields, account_url):
    first_name = (fields.get("first_name") or "").strip()
    greeting = f"Bonjour {first_name}," if first_name else "Bonjour,"
    folder_id = (fields.get("wedof_case_id") or "").strip()
    subject = "Chauffeur VTC : confirmez votre inscription CPF"
    steps = [
        ("Connectez-vous à Mon Compte Formation",
         "Cliquez sur le bouton « Accéder à Mon Compte Formation », puis connectez-vous à votre espace personnel. "
         "Utilisez FranceConnect+ (Identité Numérique la Poste) si la plateforme vous le demande et gardez votre téléphone à portée de main pour la vérification d’identité."),
        ("Ouvrez « Vos dossiers de formation »",
         "Une fois connecté, accédez à la rubrique « Vos dossiers de formation » depuis le menu de votre espace personnel."),
        ("Cliquez sur « Devis à valider »",
         "Ouvrez votre dossier de formation VTC. Notre école y apparaît sous le nom « INTEGRALE SECURITE FORMATIONS ». "
         + (f"Le numéro de votre dossier est {folder_id}." if folder_id else "")),
        ("Vérifiez votre devis",
         "Prenez connaissance des dates de formation, du programme, du prix et du financement indiqué. "
         "Si une information ne correspond pas à ce qui était prévu, contactez-nous avant de confirmer."),
        ("Confirmez votre inscription",
         "Dans ce dossier, cliquez sur le bouton permettant de confirmer l’inscription. "
         "Lisez et acceptez les conditions demandées, puis suivez toutes les étapes jusqu’au message de confirmation. "
         "Si un reste à payer est affiché, consultez son détail : un règlement peut être nécessaire pour terminer. "
         "Appelez-nous si vous ne comprenez pas le montant."),
    ]
    intro = ("Nous vous informons que nous avons accepté votre demande d’inscription en formation Chauffeur VTC. "
             "Pour finaliser votre inscription, il vous reste à confirmer votre inscription dans votre espace Mon Compte Formation. "
             "Voici comment faire, étape par étape.")
    final_step = ("Votre inscription est confirmée lorsque vous avez terminé le parcours de validation "
                  "et que la confirmation apparaît dans votre dossier. Ouvrir le devis ou lire ce mail ne suffit pas.")
    deadline = "Pensez à terminer ces étapes avant la date limite indiquée dans votre dossier Mon Compte Formation."
    help_text = ("Vous ne trouvez pas votre dossier ou la rubrique « Devis à valider » ? "
                 "Vérifiez que vous utilisez le même compte que lors de votre demande, puis appelez-nous. "
                 "Nous vous guiderons par téléphone, étape par étape, pendant que vous effectuez les démarches sur votre écran.")
    already_done = ("Vous avez déjà confirmé votre inscription sur Mon Compte Formation ? "
                    "Aucune nouvelle validation n’est nécessaire. En cas de doute, nous pouvons faire le point ensemble.")
    text = "\n\n".join([
        greeting, intro,
        *[f"{index}. {title}\n{body}" for index, (title, body) in enumerate(steps, 1)],
        f"Accéder à Mon Compte Formation : {account_url}",
        "Comment savoir si c’est terminé ?\n" + final_step,
        deadline,
        "Besoin d’aide ? Appelez-nous au 04 22 47 07 68.\n" + help_text,
        already_done, "À très bientôt,\nL’équipe Intégrale Academy",
    ])
    step_rows = "".join(
        f'<tr><td style="width:32px;vertical-align:top;padding:0 10px 20px 0;">'
        f'<span style="display:inline-block;background:#ede9fe;color:#6d28d9;border-radius:50%;'
        f'width:30px;line-height:30px;text-align:center;font-weight:700;">{index}</span></td>'
        f'<td style="vertical-align:top;padding:0 0 20px;">'
        f'<h3 style="font-size:17px;line-height:1.4;margin:2px 0 6px;color:#17152f;">{html.escape(title)}</h3>'
        f'<p style="margin:0;font-size:15px;line-height:1.65;color:#454154;">{html.escape(body)}</p></td></tr>'
        for index, (title, body) in enumerate(steps, 1)
    )
    body = f"""
      <div style="color:#292536;font-size:16px;line-height:1.65;">
        <p style="margin:0 0 8px;color:#6d28d9;font-size:12px;font-weight:700;letter-spacing:1px;text-align:center;">VOTRE INSCRIPTION VTC</p>
        <h2 style="margin:0 0 24px;color:#17152f;font-size:25px;line-height:1.3;text-align:center;">Confirmez votre inscription CPF,<br>nous vous guidons pas à pas</h2>
        <p>{html.escape(greeting)}</p>
        <p>{html.escape(intro)}</p>
        <p style="text-align:center;margin:24px 0 30px;">
          <a href="{html.escape(account_url, quote=True)}" style="display:inline-block;background:#6d28d9;color:#fff;text-decoration:none;font-weight:700;padding:13px 18px;border-radius:10px;font-size:15px;">Accéder à Mon Compte Formation</a>
        </p>
        <table role="presentation" style="border-collapse:collapse;width:100%;"><tbody>{step_rows}</tbody></table>
        <div style="background:#f5f3ff;border:1px solid #ddd6fe;border-radius:12px;padding:16px;margin:4px 0 22px;">
          <strong style="color:#4c1d95;">Comment savoir si c’est terminé ?</strong>
          <p style="margin:8px 0 0;font-size:15px;">{html.escape(final_step)}</p>
        </div>
        <p style="font-size:14px;color:#625c70;">{html.escape(deadline)}</p>
        <div style="border-top:1px solid #e8e5ed;padding-top:20px;margin-top:24px;">
          <h3 style="margin:0 0 8px;font-size:19px;color:#17152f;">Besoin d’un coup de main ?</h3>
          <p style="margin:0 0 12px;font-size:15px;">{html.escape(help_text)}</p>
          <p style="margin:0 0 16px;"><a href="tel:+33422470768" style="color:#6d28d9;font-size:20px;font-weight:700;text-decoration:none;">04 22 47 07 68</a></p>
          <p style="font-size:14px;color:#625c70;">{html.escape(already_done)}</p>
          <p style="margin-bottom:0;">À très bientôt,<br><strong>L’équipe Intégrale Academy</strong></p>
        </div>
      </div>
    """
    return {"subject": subject, "html": body, "text": text}
