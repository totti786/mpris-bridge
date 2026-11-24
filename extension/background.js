// Collects what each tab's frames report and hands one state per tab to the native helper, which
// publishes it as an MPRIS player. Commands from the desktop come back the same way.
const HOST = "mpris_bridge";
// A frame that has said nothing for this long is gone. Media sends at least every 5 seconds, so this
// only catches a frame whose document disappeared without an event (an iframe removed from the page).
const STALE_MS = 20000;
const tabs = new Map(); // tabId -> { frames: Map(frameId -> state), active: frameId, windowId, url }
let ignoreList = [];
let ignoreWasUsed = false;
let port = null;
let retry = 5000;

// ---- ignore list -------------------------------------------------------------------------------

MprisIgnore.load().then(list => { ignoreList = list; applyIgnoreList(); }, () => {});
browser.storage.onChanged.addListener((changes, area) => {
  if (area !== "local" || !changes.ignored) return;
  ignoreList = changes.ignored.newValue || [];
  applyIgnoreList();
});

function ignored(url) {
  return MprisIgnore.matches(url, ignoreList);
}

/// Tell a frame (or every frame of a tab) whether its tab is ignored, so it can stop or resume.
function tell(tabId, frameId, value) {
  const options = frameId == null ? {} : { frameId };
  browser.tabs.sendMessage(tabId, { cmd: "Ignore", value }, options).catch(() => {});
}

/// Drop the players of sites that have just been ignored, and tell the other tabs they may play again.
function applyIgnoreList() {
  for (const [id, t] of [...tabs]) {
    if (ignored(t.url)) {
      tabs.delete(id);
      post({ tab: id, gone: true });
      tell(id, null, true);
    } else {
      tell(id, null, false);
    }
  }
  // Tabs whose players were dropped earlier are no longer in the map, so ask every tab as well
  // (but not on startup when nothing is ignored, which is the common case).
  if (!ignoreList.length && !ignoreWasUsed) return;
  ignoreWasUsed = ignoreList.length > 0;
  browser.tabs.query({}).then(all => {
    for (const tab of all) {
      if (tab.id != null && !tab.incognito) tell(tab.id, null, ignored(tab.url));
    }
  }, () => {});
}

// ---- native helper -----------------------------------------------------------------------------

function connect() {
  try {
    port = browser.runtime.connectNative(HOST);
  } catch (e) {
    port = null;
    setTimeout(connect, retry); // e.g. nativeMessaging not permitted yet
    retry = Math.min(retry * 2, 300000);
    return;
  }
  port.onMessage.addListener(msg => {
    retry = 5000;
    onCommand(msg);
  });
  port.onDisconnect.addListener(() => {
    port = null;
    // Helper missing or crashed: try again, less and less often
    setTimeout(connect, retry);
    retry = Math.min(retry * 2, 300000);
  });
  // A restarted helper knows nothing: tell it about every tab again
  for (const id of tabs.keys()) publish(id);
}

function post(msg) {
  if (port) port.postMessage(msg);
}

function publish(tabId) {
  const t = tabs.get(tabId);
  if (!t) return;
  let best = null;
  for (const [frame, s] of t.frames) {
    if (!best || (s.playing && !best.s.playing) || (s.playing === best.s.playing && s.at > best.s.at))
      best = { frame, s };
  }
  if (!best) {
    tabs.delete(tabId);
    post({ tab: tabId, gone: true });
    return;
  }
  t.active = best.frame;
  post(Object.assign({}, best.s, { tab: tabId }));
}

browser.runtime.onMessage.addListener((msg, sender) => {
  const tab = sender.tab;
  if (!tab || tab.incognito || typeof msg !== "object") return;
  if (ignored(tab.url)) {
    if (tabs.delete(tab.id)) post({ tab: tab.id, gone: true });
    tell(tab.id, sender.frameId, true);
    return;
  }
  let t = tabs.get(tab.id);
  if (msg.gone) {
    if (t) {
      t.frames.delete(sender.frameId);
      publish(tab.id);
    }
    return;
  }
  if (!t) tabs.set(tab.id, (t = { frames: new Map(), active: 0, windowId: tab.windowId, url: "" }));
  t.windowId = tab.windowId;
  t.url = tab.url || "";
  msg.at = Date.now();
  if (!msg.title) msg.title = tab.title || "";
  t.frames.set(sender.frameId, msg);
  publish(tab.id);
});

browser.tabs.onRemoved.addListener(id => {
  if (tabs.delete(id)) post({ tab: id, gone: true });
});
// A navigation drops the old page's frames; the new page reports for itself
browser.tabs.onUpdated.addListener((id, change) => {
  if (change.status === "loading" && change.url && tabs.has(id)) {
    tabs.delete(id);
    post({ tab: id, gone: true });
  }
});

// A removed iframe sends nothing (Firefox has no event for it), so let silence do the work.
setInterval(() => {
  const now = Date.now();
  for (const [id, t] of [...tabs]) {
    let lost = false;
    for (const [frame, s] of t.frames) {
      if (now - s.at > STALE_MS) { t.frames.delete(frame); lost = true; }
    }
    if (lost) publish(id);
  }
}, 5000);

function onCommand(msg) {
  const t = tabs.get(msg.tab);
  if (!t) return;
  if (msg.cmd === "Raise") {
    browser.tabs.update(msg.tab, { active: true });
    browser.windows.update(t.windowId, { focused: true });
    return;
  }
  browser.tabs.sendMessage(msg.tab, { cmd: msg.cmd, value: msg.value }, { frameId: t.active }).catch(() => {});
}

connect();
