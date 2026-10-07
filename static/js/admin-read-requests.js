// Share simultaneous navigation-badge reads without caching stale business data.
(() => {
  const pending = new Map();
  window.adminReadFetch = (url) => {
    if(!pending.has(url)) {
      const promise = fetch(url, {headers: {Accept: 'application/json'}})
        .finally(() => pending.delete(url));
      pending.set(url, promise);
    }
    // Each consumer gets an independently readable body.
    return pending.get(url).then(response => response.clone());
  };
})();
