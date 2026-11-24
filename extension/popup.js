const site = document.getElementById("site");
const toggle = document.getElementById("toggle");
const note = document.getElementById("note");
let tabUrl = "";
let list = [];

function webPage(url) {
  try {
    const u = new URL(url);
    return u.protocol === "http:" || u.protocol === "https:";
  } catch (e) {
    return false;
  }
}

/// The ignore-list entry that covers this tab, if any (its own host or a parent domain).
function coveringEntry() {
  return list.find(entry => MprisIgnore.matches(tabUrl, [entry])) || "";
}

async function render() {
  const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
  tabUrl = (tab && tab.url) || "";
  list = await MprisIgnore.load();

  if (!webPage(tabUrl)) {
    site.textContent = "This page can't be ignored";
    toggle.disabled = true;
    toggle.textContent = "Ignore this site";
    toggle.classList.remove("on");
    note.textContent = "Only http and https pages can be ignored.";
    return;
  }

  const host = MprisIgnore.hostOf(tabUrl);
  const entry = coveringEntry();
  site.textContent = host;
  toggle.disabled = false;
  toggle.textContent = entry ? "Stop ignoring this site" : "Ignore this site";
  toggle.classList.toggle("on", !!entry);
  note.textContent = entry && entry !== host ? "Ignored by the rule for " + entry : "";
}

toggle.addEventListener("click", async () => {
  const entry = coveringEntry();
  list = entry ? list.filter(e => e !== entry) : [...list, MprisIgnore.hostOf(tabUrl)];
  await MprisIgnore.save(list);
  render();
});

document.getElementById("options").addEventListener("click", e => {
  e.preventDefault();
  browser.runtime.openOptionsPage();
});

render();
