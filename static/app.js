const qs = (sel, root=document) => root.querySelector(sel);
const qsa = (sel, root=document) => Array.from(root.querySelectorAll(sel));

function toast(msg, ok=true) {
  const t = qs("#toast");
  if (!t) return;
  t.textContent = msg;
  t.classList.remove("show", "ok", "bad");
  t.classList.add("show", ok ? "ok" : "bad");
  setTimeout(() => t.classList.remove("show"), 2200);
}

function openModal(id) {
  const el = qs(`#${id}`);
  if (!el) return;
  el.setAttribute("aria-hidden", "false");
  el.classList.add("open");
}
function closeModal(id) {
  const el = qs(`#${id}`);
  if (!el) return;
  el.setAttribute("aria-hidden", "true");
  el.classList.remove("open");
}

function withAdminKey(url) {
  const qsKey = window.__ADMIN_KEY_QS || "";
  if (!qsKey) return url;
  return url.includes("?") ? `${url}&${qsKey}` : `${url}?${qsKey}`;
}

async function api(url, method="GET", body=null) {
  const opts = { method, headers: {} };
  if (body) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(withAdminKey(url), opts);
  const data = await res.json().catch(()=> ({}));
  if (!res.ok || data.ok === false) {
    throw new Error(data.error || `Erreur HTTP ${res.status}`);
  }
  return data;
}

/* ------------------------
   SESSIONS PAGE
------------------------- */
(function initSessions(){
  const btnOpen = qs("#btnOpenCreateSession");
  const modalId = "createSessionModal";
  if (btnOpen) {
    btnOpen.addEventListener("click", () => openModal(modalId));
  }
  qsa("[data-close-modal]").forEach(b => {
    b.addEventListener("click", () => closeModal(b.getAttribute("data-close-modal")));
  });

  const btnCreate = qs("#btnCreateSession");
  if (btnCreate) {
    btnCreate.addEventListener("click", async () => {
      const payload = {
        name: (qs("#sessionName")?.value || "").trim(),
        training_type: (qs("#sessionType")?.value || "").trim(),
        date_start: qs("#dateStart")?.value,
        date_end: qs("#dateEnd")?.value,
        exam_date: qs("#examDate")?.value
      };
      try {
        await api("/admin/sessions/create", "POST", payload);
        toast("Session créée ✅");
        closeModal(modalId);
        window.location.reload();
      } catch (e) {
        toast(e.message, false);
      }
    });
  }

  qsa("[data-delete-session]").forEach(btn => {
    btn.addEventListener("click", async () => {
      const id = btn.getAttribute("data-delete-session");
      if (!confirm("Supprimer cette session ? (stagiaires inclus)")) return;
      try {
        await api(`/admin/sessions/${id}/delete`, "POST");
        toast("Session supprimée");
        window.location.reload();
      } catch (e) {
        toast(e.message, false);
      }
    });
  });
})();

/* ------------------------
   TRAINEES PAGE
------------------------- */
(function initTrainees(){
  const table = qs("#traineesTable");
  if (!table) return;

  const sessionId = table.getAttribute("data-session-id");
  const modalId = "createTraineeModal";

  const btnOpen = qs("#btnOpenCreateTrainee");
  if (btnOpen) btnOpen.addEventListener("click", () => openModal(modalId));
  qsa("[data-close-modal]").forEach(b => b.addEventListener("click", () => closeModal(b.getAttribute("data-close-modal"))));

  const btnCreate = qs("#btnCreateTrainee");
  if (btnCreate) {
    btnCreate.addEventListener("click", async () => {
      const payload = {
        session_id: sessionId,
        last_name: (qs("#tLastName")?.value || "").trim(),
        first_name: (qs("#tFirstName")?.value || "").trim(),
        email: (qs("#tEmail")?.value || "").trim(),
        phone: (qs("#tPhone")?.value || "").trim()
      };
      try {
        await api("/api/trainees/add", "POST", payload);
        toast("Stagiaire ajouté + message envoyé ✅");
        closeModal(modalId);
        window.location.reload();
      } catch (e) {
        toast(e.message, false);
      }
    });
  }

  // Autosave (selects + input commentaire)
  let saveTimer = null;
  function scheduleSave(fn) {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(fn, 250);
  }

  async function saveField(row, field, value) {
    const traineeId = row.getAttribute("data-trainee-id");
    await api("/api/trainees/update", "POST", { trainee_id: traineeId, field, value });
  }

  function applyBadges(row) {
    // Convention
    const conv = qs(".sel-convention", row)?.value;
    const test = qs(".sel-testfr", row)?.value;
    const dos = qs(".sel-dossier", row)?.value;
    const fin = qs(".sel-finance", row)?.value;

    const badge = (kind, val) => {
      const el = qsa(`[data-badge="${kind}"]`, row)[0];
      if (!el) return;
      el.className = "badge " + statusClass(kind, val);
    };

    badge("convention_status", conv);
    badge("test_fr_status", test);
    badge("dossier_status", dos);
    badge("financement_status", fin);
  }

  function statusClass(kind, val) {
    // mapping couleurs
    const map = {
      convention_status: { soon:"red", signing:"yellow", signed:"green" },
      test_fr_status: { soon:"red", in_progress:"yellow", validated:"green", relance:"orange" },
      dossier_status: { complete:"green", incomplete:"red" },
      financement_status: { soon:"red", in_review:"orange", validated:"green" }
    };
    return (map[kind] && map[kind][val]) ? map[kind][val] : "neutral";
  }

  qsa("tbody tr", table).forEach(row => {
    applyBadges(row);

    qsa("select.status", row).forEach(sel => {
