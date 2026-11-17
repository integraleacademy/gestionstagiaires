(() => {
  const pendingKeys = new Map();

  function requestKey(storageKey) {
    let key = pendingKeys.get(storageKey);
    try { key ||= sessionStorage.getItem(storageKey); } catch {}
    if (!key) key = crypto.randomUUID();
    pendingKeys.set(storageKey, key);
    try { sessionStorage.setItem(storageKey, key); } catch {}
    return key;
  }

  function forget(storageKey) {
    if (!storageKey) return;
    pendingKeys.delete(storageKey);
    try { sessionStorage.removeItem(storageKey); } catch {}
  }

  async function read(response, storageKey) {
    const result = await response.json().catch(() => null);
    if (!result) throw new Error("Suivi interrompu. Réessayez pour vérifier cette même demande.");
    if (!response.ok || result.ok !== true) {
      const finished = response.headers.get("X-Convocation-Job-State") === "finished";
      if (finished || (response.status < 500 && response.status !== 429)) forget(storageKey);
      throw new Error(result.error || "Le traitement de la convocation a échoué.");
    }
    if (response.status !== 202) forget(storageKey);
    return result;
  }

  async function submit(url, payload = {}) {
    const storageKey = "convocation-job:" + new URL(url, location.href).pathname;
    const response = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Prefer": "respond-async",
        "Idempotency-Key": requestKey(storageKey),
      },
      body: JSON.stringify(payload),
    }).catch(() => { throw new Error("Connexion interrompue. Réessayez pour vérifier cette même demande."); });
    const result = await read(response, storageKey);
    if (response.status !== 202) return { result };
    const statusUrl = result.status_url && new URL(result.status_url, location.href);
    if (!statusUrl || statusUrl.origin !== location.origin) throw new Error("Le suivi de la convocation est indisponible.");
    return { storageKey, statusUrl, result };
  }

  async function wait(job, onStatus) {
    let result = job.result;
    if (!job.statusUrl) return result;
    let delay = 1500;
    let retries = 0;
    while (true) {
      onStatus?.(result.status);
      await new Promise(resolve => setTimeout(resolve, delay));
      const response = await fetch(job.statusUrl, { cache: "no-store", headers: { Accept: "application/json" } })
        .catch(() => null);
      if (!response || [429, 502, 503, 504].includes(response.status)) {
        if (++retries <= 3) { delay = 4000; continue; }
        throw new Error("Suivi interrompu. Réessayez pour vérifier cette même demande.");
      }
      retries = 0;
      result = await read(response, job.storageKey);
      if (response.status !== 202) return result;
      delay = Math.min(delay + 500, 4000);
    }
  }

  window.convocationJobs = { submit, wait };
})();
