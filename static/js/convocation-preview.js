(() => {
  const message = document.getElementById("preparation");
  const statusUrl = new URL(location.href);
  statusUrl.searchParams.set("preparation", message.dataset.jobId);
  window.convocationJobs.wait({ statusUrl, result: { status: "queued" } })
    .then(() => location.reload())
    .catch(error => { message.textContent = error.message; });
})();
