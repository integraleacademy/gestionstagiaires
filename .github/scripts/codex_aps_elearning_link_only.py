from pathlib import Path


def block(*lines: str) -> str:
    return "\n".join(lines) + "\n"


def replace_exact(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: remplacement attendu 1 fois, trouvé {count}")
    return text.replace(old, new, 1)


def replace_section(
    text: str,
    start_marker: str,
    end_marker: str,
    replacement: str,
    label: str,
) -> str:
    start_count = text.count(start_marker)
    if start_count != 1:
        raise SystemExit(
            f"{label}: marqueur de début attendu 1 fois, trouvé {start_count}"
        )
    start = text.index(start_marker)
    end = text.find(end_marker, start + len(start_marker))
    if end < 0:
        raise SystemExit(f"{label}: marqueur de fin introuvable")
    return text[:start] + replacement + text[end:]


admin_path = Path("templates/admin_trainee.html")
admin = admin_path.read_text(encoding="utf-8")
admin = replace_section(
    admin,
    '  <div style="font-weight:900;font-size:18px;">🎓 Identifiants e-learning APS</div>\n',
    '  {% set aps_tracking = trainee.aps_elearning_tracking or {} %}\n',
    block(
        '  <div style="font-weight:900;font-size:18px;">🔗 Lien e-learning APS</div>',
        '  <div class="hint" style="margin-top:6px;">',
        '    Ce lien personnel sera visible dans l’espace stagiaire uniquement à partir du premier jour de formation ({{ session.date_start|frdate }}).',
        '  </div>',
        '  <div style="display:grid;grid-template-columns:minmax(260px,840px);gap:12px;margin-top:14px;">',
        '    <label>',
        '      <div class="label">Lien d’accès e-learning</div>',
        '      <input id="editApsElearningLogin"',
        '             type="url"',
        '             value="{{ trainee.aps_elearning_login or \'\' }}"',
        '             placeholder="https://..."',
        '             inputmode="url"',
        '             autocomplete="url"',
        '             {{ read_only_attr }}>',
        '    </label>',
        '  </div>',
        '  <div class="hint" style="margin-top:8px;">Collez le lien personnel complet fourni par la plateforme. Sauvegarde automatique.</div>',
        '',
    ),
    "bloc administrateur APS",
)
admin_path.write_text(admin, encoding="utf-8")


public_path = Path("templates/public_trainee.html")
public = public_path.read_text(encoding="utf-8")
public = replace_section(
    public,
    "    {% if aps_elearning_enabled %}\n",
    "    {% if is_vtc_training %}\n",
    block(
        "    {% if aps_elearning_enabled %}",
        "      {% set aps_link = (trainee.aps_elearning_login or '')|trim %}",
        "      {% set aps_link_is_valid = aps_link[:8] == 'https://' %}",
        '      <section class="card aps-elearning-card" aria-labelledby="apsElearningTitle">',
        '        <div class="aps-elearning-icon" aria-hidden="true">',
        '          <svg viewBox="0 0 24 24" fill="none" role="img">',
        '            <path d="M5 6.5A2.5 2.5 0 0 1 7.5 4H19v13H7.5A2.5 2.5 0 0 0 5 19.5v-13Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>',
        '            <path d="M5 19.5A2.5 2.5 0 0 1 7.5 17H19" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>',
        '            <path d="M9 8h6M9 11h4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>',
        "          </svg>",
        "        </div>",
        '        <div class="aps-elearning-content">',
        '          <h2 id="apsElearningTitle">Espace e-learning APS</h2>',
        '          <p class="aps-elearning-subtitle">Votre lien personnel vers la plateforme de formation à distance sera activé au démarrage de la formation.</p>',
        '          <div class="aps-elearning-badge">Accès disponible le {{ session.date_start|frdate }}</div>',
        '          <p class="aps-elearning-note">Votre progression restera suivie pendant toute la formation, sans identifiant ni mot de passe à saisir.</p>',
        "        {% if not aps_elearning_available %}",
        '          <div class="aps-elearning-pending">',
        "            Votre lien d’accès sera affiché ici le premier jour de formation.",
        "          </div>",
        "        {% elif aps_link_is_valid %}",
        '          <div class="aps-elearning-actions">',
        '            <a class="btn" href="{{ aps_link }}" target="_blank" rel="noopener noreferrer">🚀 Accéder au e-learning</a>',
        '            <span class="aps-elearning-copy-status">Lien personnel sécurisé</span>',
        "          </div>",
        "        {% elif aps_link %}",
        '          <div class="aps-elearning-pending">Le lien enregistré n’est pas valide. Merci de contacter l’équipe pédagogique.</div>',
        "        {% else %}",
        '          <div class="aps-elearning-pending">Votre lien personnel est en cours de préparation. Il apparaîtra ici dès qu’il sera disponible.</div>',
        "        {% endif %}",
        "        </div>",
        "      </section>",
        "    {% endif %}",
        "",
    ),
    "bloc espace stagiaire APS",
)
public_path.write_text(public, encoding="utf-8")


app_path = Path("app.py")
app_text = app_path.read_text(encoding="utf-8")
app_text = replace_exact(
    app_text,
    block(
        '        "aps_elearning_login",',
        '        "aps_elearning_password",',
    ),
    block(
        '        "aps_elearning_login",',
    ),
    "liste des champs modifiables APS",
)
app_text = replace_exact(
    app_text,
    block(
        '        if k in ("aps_elearning_login", "aps_elearning_password") and not aps_elearning_fields_enabled:',
        "            continue",
        "",
        '        if k == "ssiap_exam_status":',
    ),
    block(
        '        if k == "aps_elearning_login" and not aps_elearning_fields_enabled:',
        "            continue",
        "",
        '        if k == "aps_elearning_login":',
        '            link = str(v or "").strip()',
        "            parsed_link = urlparse(link)",
        '            if link and (parsed_link.scheme.lower() != "https" or not parsed_link.netloc):',
        '                return jsonify({"ok": False, "error": "aps_elearning_link_invalid"}), 400',
        "            t[k] = link",
        '            t.pop("aps_elearning_password", None)',
        "            continue",
        "",
        '        if k == "ssiap_exam_status":',
    ),
    "validation du lien APS",
)
app_path.write_text(app_text, encoding="utf-8")


tests_path = Path("tests/test_aps_elearning.py")
tests = tests_path.read_text(encoding="utf-8")
tests = replace_exact(
    tests,
    block(
        '                            "aps_elearning_login": "alice.aps",',
        '                            "aps_elearning_password": "Secret-123",',
    ),
    block(
        '                            "aps_elearning_login": "https://ediser.elmg.net/access/alice-aps",',
    ),
    "données de test APS",
)
tests = replace_section(
    tests,
    "    def test_admin_trainee_credentials_are_available_only_for_enabled_aps_session(self):\n",
    "    def test_complete_digiforma_pdf_is_imported_and_downloadable(self):\n",
    block(
        "    def test_admin_trainee_link_is_available_only_for_enabled_aps_session(self):",
        "        self._admin_login()",
        '        data = self._data("2026-06-15")',
        "",
        '        with patch.object(gestion_app, "load_data", return_value=data), patch.object(',
        '            gestion_app, "save_data"',
        "        ):",
        '            response = self.client.get("/admin/sessions/S-APS/stagiaires/T-APS")',
        "",
        "        self.assertEqual(response.status_code, 200)",
        "        html = response.get_data(as_text=True)",
        '        self.assertIn("Lien e-learning APS", html)',
        '        self.assertRegex(html, r\'id="editApsElearningLogin"\\s+type="url"\')',
        "        self.assertIn(",
        '            \'value="https://ediser.elmg.net/access/alice-aps"\',',
        "            html,",
        "        )",
        '        self.assertNotIn(\'id="editApsElearningPassword"\', html)',
        '        self.assertIn("Suivi du e-learning", html)',
        '        self.assertIn("Importer le relevé complet", html)',
        '        self.assertIn("TABLEAU DE SUIVI DE LA FORMATION À DISTANCE", html)',
        '        self.assertIn(\'disabled aria-disabled="true">⬇️ Dossier CNAPS non disponible\', html)',
        "",
        '        data["sessions"][0]["aps_elearning_enabled"] = False',
        '        with patch.object(gestion_app, "load_data", return_value=data), patch.object(',
        '            gestion_app, "save_data"',
        "        ):",
        '            response = self.client.get("/admin/sessions/S-APS/stagiaires/T-APS")',
        '        self.assertNotIn("Lien e-learning APS", response.get_data(as_text=True))',
        '        self.assertNotIn("Suivi du e-learning", response.get_data(as_text=True))',
        "",
    ),
    "test administrateur APS",
)
tests = replace_section(
    tests,
    "    def test_trainee_api_saves_credentials_only_when_aps_elearning_is_enabled(self):\n",
    'if __name__ == "__main__":\n',
    block(
        "    def test_trainee_api_saves_link_only_when_aps_elearning_is_enabled(self):",
        "        self._admin_login()",
        '        data = self._data("2026-06-15")',
        "",
        '        with patch.object(gestion_app, "load_data", return_value=data), patch.object(',
        '            gestion_app, "save_data"',
        "        ):",
        "            response = self.client.post(",
        '                "/api/sessions/S-APS/stagiaires/T-APS/update",',
        "                json={",
        '                    "aps_elearning_login": "https://ediser.elmg.net/access/nouveau-lien",',
        '                    "aps_elearning_password": "doit-etre-ignore",',
        "                },",
        "            )",
        "",
        "        self.assertEqual(response.status_code, 200)",
        '        trainee = data["sessions"][0]["trainees"][0]',
        "        self.assertEqual(",
        '            trainee["aps_elearning_login"],',
        '            "https://ediser.elmg.net/access/nouveau-lien",',
        "        )",
        '        self.assertNotIn("aps_elearning_password", trainee)',
        "",
        '        with patch.object(gestion_app, "load_data", return_value=data), patch.object(',
        '            gestion_app, "save_data"',
        "        ):",
        "            invalid = self.client.post(",
        '                "/api/sessions/S-APS/stagiaires/T-APS/update",',
        '                json={"aps_elearning_login": "pas-un-lien"},',
        "            )",
        "        self.assertEqual(invalid.status_code, 400)",
        "        self.assertEqual(",
        '            invalid.get_json()["error"],',
        '            "aps_elearning_link_invalid",',
        "        )",
        "        self.assertEqual(",
        '            trainee["aps_elearning_login"],',
        '            "https://ediser.elmg.net/access/nouveau-lien",',
        "        )",
        "",
        '        data["sessions"][0]["aps_elearning_enabled"] = False',
        '        with patch.object(gestion_app, "load_data", return_value=data), patch.object(',
        '            gestion_app, "save_data"',
        "        ):",
        "            response = self.client.post(",
        '                "/api/sessions/S-APS/stagiaires/T-APS/update",',
        "                json={",
        '                    "aps_elearning_login": "https://ediser.elmg.net/access/doit-etre-ignore"',
        "                },",
        "            )",
        "",
        "        self.assertEqual(response.status_code, 200)",
        "        self.assertEqual(",
        '            trainee["aps_elearning_login"],',
        '            "https://ediser.elmg.net/access/nouveau-lien",',
        "        )",
        "",
        "    def test_public_space_hides_link_before_first_training_day(self):",
        "        self._public_login()",
        "        tomorrow = datetime.date.today() + datetime.timedelta(days=1)",
        "        data = self._data(tomorrow.isoformat())",
        "",
        '        with patch.object(gestion_app, "load_data", return_value=data), patch.object(',
        '            gestion_app, "save_data"',
        "        ):",
        '            response = self.client.get("/espace/PUBLIC-TOKEN")',
        "",
        "        self.assertEqual(response.status_code, 200)",
        "        html = response.get_data(as_text=True)",
        '        self.assertIn(f"Accès disponible le {tomorrow.strftime(\'%d/%m/%Y\')}", html)',
        '        self.assertNotIn("https://ediser.elmg.net/access/alice-aps", html)',
        '        self.assertNotIn("Accéder au e-learning", html)',
        '        self.assertNotIn(\'id="apsElearningPassword"\', html)',
        "",
        "    def test_public_space_shows_personal_link_from_first_day(self):",
        "        self._public_login()",
        "        data = self._data(datetime.date.today().isoformat())",
        "",
        '        with patch.object(gestion_app, "load_data", return_value=data), patch.object(',
        '            gestion_app, "save_data"',
        "        ):",
        '            response = self.client.get("/espace/PUBLIC-TOKEN")',
        "",
        "        self.assertEqual(response.status_code, 200)",
        "        html = response.get_data(as_text=True)",
        "        self.assertIn(",
        '            \'href="https://ediser.elmg.net/access/alice-aps"\',',
        "            html,",
        "        )",
        '        self.assertIn("Accéder au e-learning", html)',
        '        self.assertNotIn(\'data-copy-target="apsElearningLogin"\', html)',
        '        self.assertNotIn(\'data-copy-target="apsElearningPassword"\', html)',
        '        self.assertNotIn(\'id="apsElearningPassword"\', html)',
        "",
        "    def test_public_space_does_not_make_legacy_login_clickable(self):",
        "        self._public_login()",
        "        data = self._data(datetime.date.today().isoformat())",
        '        data["sessions"][0]["trainees"][0]["aps_elearning_login"] = "alice.aps"',
        "",
        '        with patch.object(gestion_app, "load_data", return_value=data), patch.object(',
        '            gestion_app, "save_data"',
        "        ):",
        '            response = self.client.get("/espace/PUBLIC-TOKEN")',
        "",
        "        self.assertEqual(response.status_code, 200)",
        "        html = response.get_data(as_text=True)",
        '        self.assertIn("Le lien enregistré n’est pas valide", html)',
        '        self.assertNotIn(\'href="alice.aps"\', html)',
        '        self.assertNotIn("Accéder au e-learning", html)',
        "",
        "    def test_public_space_does_not_show_aps_card_for_vtc_or_disabled_session(self):",
        "        self._public_login()",
        '        for training_type, enabled in (("VTC", True), ("APS", False)):',
        "            data = self._data(",
        "                datetime.date.today().isoformat(),",
        "                enabled=enabled,",
        "                training_type=training_type,",
        "            )",
        '            with patch.object(gestion_app, "load_data", return_value=data), patch.object(',
        '                gestion_app, "save_data"',
        "            ):",
        '                response = self.client.get("/espace/PUBLIC-TOKEN")',
        "            html = response.get_data(as_text=True)",
        '            self.assertNotIn("Espace e-learning APS", html)',
        '            self.assertNotIn("https://ediser.elmg.net/access/alice-aps", html)',
        '            self.assertNotIn(\'id="apsElearningPassword"\', html)',
        "",
        "",
    ),
    "tests API et espace stagiaire APS",
)
tests_path.write_text(tests, encoding="utf-8")
