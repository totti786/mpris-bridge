// Shared by the background page, the content script and the popup/options pages.
// The ignore list is a plain array of hostnames in browser.storage.local; an entry covers the host
// itself and every subdomain of it.
globalThis.MprisIgnore = (() => {
  const MAX = 200;

  /** Turn whatever the user typed (a URL, a host, a *.host) into a bare hostname, or "" if it cannot be one. */
  function normalize(entry) {
    if (typeof entry !== "string") return "";
    let s = entry.trim().toLowerCase();
    if (!s) return "";
    if (s.startsWith("*.")) s = s.slice(2);
    if (/^[a-z0-9.-]+$/.test(s)) {
      const host = s.replace(/^www\./, "").replace(/\.$/, "");
      return valid(host) ? host : "";
    }
    if (!/^[a-z][a-z0-9+.-]*:\/\//.test(s)) s = "http://" + s;
    try {
      const host = new URL(s).hostname.toLowerCase().replace(/^www\./, "").replace(/\.$/, "");
      return valid(host) ? host : "";
    } catch (e) {
      return "";
    }
  }

  function valid(host) {
    return !!host && !host.includes("..") && /^[a-z0-9.-]+$/.test(host) && /\.[a-z0-9-]+$|^[a-z0-9-]+$/.test(host);
  }

  /** The hostname a URL points at, without a leading www. */
  function hostOf(url) {
    try {
      return new URL(url).hostname.toLowerCase().replace(/^www\./, "").replace(/\.$/, "");
    } catch (e) {
      return "";
    }
  }

  /** Does this URL belong to one of the ignored sites (that host or a subdomain of it)? */
  function matches(url, list) {
    const host = hostOf(url);
    if (!host) return false;
    for (const raw of list || []) {
      const entry = normalize(raw);
      if (entry && (host === entry || host.endsWith("." + entry))) return true;
    }
    return false;
  }

  async function load() {
    const stored = await browser.storage.local.get({ ignored: [] });
    const list = Array.isArray(stored.ignored) ? stored.ignored : [];
    return [...new Set(list.map(normalize).filter(Boolean))].slice(0, MAX);
  }

  async function save(list) {
    const out = [...new Set((list || []).map(normalize).filter(Boolean))].slice(0, MAX);
    await browser.storage.local.set({ ignored: out });
    return out;
  }

  return { normalize, hostOf, matches, load, save };
})();
