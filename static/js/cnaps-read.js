(function () {
  "use strict";

  // Only the initial request may start a check. Polling never resubmits a POST.
  window.cnapsRead = async function (url, options = {}) {
    const headers = new Headers(options.headers);
    headers.set("Prefer", "respond-async");
    headers.set("Accept", "application/json");
    let response = await fetch(url, { ...options, headers, cache: "no-store" });
    if (response.status !== 202) return response;

    const job = await response.json();
    if (!job.status_url) throw new Error("Vérification CNAPS introuvable.");
    const statusUrl = new URL(job.status_url, window.location.href);
    if (statusUrl.origin !== window.location.origin) throw new Error("Adresse de vérification CNAPS invalide.");
    while (response.status === 202) {
      const retry = Number(response.headers.get("Retry-After")) || 2;
      await new Promise(resolve => setTimeout(resolve, Math.max(1, Math.min(5, retry)) * 1000));
      response = await fetch(statusUrl, {
        headers: { Accept: "application/json" },
        cache: "no-store",
        signal: options.signal
      });
    }
    return response;
  };
})();
