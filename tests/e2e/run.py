#!/usr/bin/env python3
"""End-to-end check: a headless Firefox with a throwaway profile loads the extension, plays two local
pages, and this script talks to the resulting players over D-Bus as a desktop would.

  make e2e          (needs firefox, node/npx for web-ext, ffmpeg, a session bus and the built helper)

Registers the built helper for the current Firefox-family browser for the duration of the run (restoring any
manifest it found), exits non-zero on the first failed expectation, and prints the memory the processes use.
"""
import http.server
import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.parse

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SITE = os.path.join(os.path.dirname(__file__), "site")
PORT = int(os.environ.get("E2E_PORT", "8123"))
PREFIX = "org.mpris.MediaPlayer2.firefox_bridge."
PLAYER = "org.mpris.MediaPlayer2.Player"
ROOTIF = "org.mpris.MediaPlayer2"
LOG = []
COMMANDS = {}  # who -> [command, ...], fetched by the pages themselves
HOST_BIN = os.path.join(ROOT, "host", "target", "release", "mpris-bridge-host")
HOST_MANIFEST = os.path.expanduser("~/.mozilla/native-messaging-hosts/mpris_bridge.json")
EXT_ID = "mpris-bridge@totti786.github.io"


def command(who, cmd):
    COMMANDS.setdefault(who, []).append(cmd)


class Site(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=SITE, **kw)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        if url.path == "/log":
            q = urllib.parse.parse_qs(url.query)
            LOG.append((q.get("k", [""])[0], q.get("v", [""])[0]))
            self.send_response(204)
            self.end_headers()
            return
        if url.path == "/cmd":
            who = urllib.parse.parse_qs(url.query).get("who", [""])[0]
            queue = COMMANDS.get(who) or []
            if queue:
                body = queue.pop(0).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(204)
                self.end_headers()
            return
        super().do_GET()

    def log_message(self, *a):
        pass


bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)


def call(name, iface, method, params=None, path="/org/mpris/MediaPlayer2"):
    return bus.call_sync(name, path, iface, method, params, None, Gio.DBusCallFlags.NONE, 5000, None)


def get(name, prop, iface=PLAYER):
    return call(name, "org.freedesktop.DBus.Properties", "Get", GLib.Variant("(ss)", (iface, prop))).unpack()[0]


def players():
    """Players of the Firefox this script started; a browser already open on the same bus is not ours."""
    mine = {pid for pid, _ in children(proc.pid)} if proc else set()
    names = bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "ListNames",
                          None, None, Gio.DBusCallFlags.NONE, -1, None).unpack()[0]
    ours = [n for n in names if n.startswith(PREFIX) and int(n[len(PREFIX) + 1:].split("t")[0]) in mine]
    return {get(n, "Metadata").get("xesam:title", ""): n for n in ours}


def wait(what, cond, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        try:
            v = cond()
        except Exception:
            v = None
        if v:
            return v
        time.sleep(0.25)
    fail("timed out waiting for %s (page log: %s)" % (what, LOG[-6:]))


failures = []


def fail(msg):
    print("FAIL", msg)
    failures.append(msg)
    raise SystemExit(cleanup(1))


def check(what, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + what + ("" if ok else "  -> " + str(detail)))
    if not ok:
        failures.append(what)


def rss(pid):
    try:
        for line in open("/proc/%d/status" % pid):
            if line.startswith("VmRSS"):
                return int(line.split()[1])
    except OSError:
        pass
    return 0


proc = None
host_backup = None
host_restored = False


def register_host():
    """Firefox reads native-messaging manifests from the home directory, not from a throwaway profile.

    Returns the previous manifest contents, or None if there was none; cleanup() puts them back.
    """
    if not os.path.exists(HOST_BIN):
        raise SystemExit("build the helper first: make build")
    os.makedirs(os.path.dirname(HOST_MANIFEST), exist_ok=True)
    previous = None
    if os.path.exists(HOST_MANIFEST):
        with open(HOST_MANIFEST) as f:
            previous = f.read()
    with open(HOST_MANIFEST, "w") as f:
        json.dump({"name": "mpris_bridge", "description": "MPRIS Bridge helper (end-to-end test)",
                   "path": HOST_BIN, "type": "stdio", "allowed_extensions": [EXT_ID]}, f, indent=2)
    return previous


def restore_host():
    global host_restored
    if host_restored or host_backup is None and not os.path.exists(HOST_MANIFEST):
        return
    host_restored = True
    if host_backup is None:
        try:
            os.unlink(HOST_MANIFEST)
        except OSError:
            pass
    else:
        with open(HOST_MANIFEST, "w") as f:
            f.write(host_backup)


def cleanup(code=0):
    if proc and proc.poll() is None:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(10)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
    restore_host()
    return code or (1 if failures else 0)


def children(pid_root):
    """Every process in the session we started, as (pid, cmdline)."""
    out = []
    sid = os.getsid(pid_root)
    for p in os.listdir("/proc"):
        if p.isdigit():
            try:
                if os.getsid(int(p)) == sid:
                    out.append((int(p), open("/proc/%s/cmdline" % p).read().replace("\0", " ")))
            except OSError:
                pass
    return out


def main():
    global proc, host_backup
    host_backup = register_host()
    tone = os.path.join(SITE, "tone.ogg")
    if not os.path.exists(tone):
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=300",
                        "-c:a", "libvorbis", "-q:a", "0", tone], check=True)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Site)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % PORT

    proc = subprocess.Popen(
        ["npx", "--yes", "web-ext", "run", "--source-dir", os.path.join(ROOT, "extension"), "--firefox",
         os.environ.get("FIREFOX", "firefox"), "--arg=-headless", "--no-input", "--no-reload", "--no-config-discovery",
         "--pref", "media.autoplay.default=0", "--pref", "media.autoplay.blocking_policy=0",
         "--pref", "media.block-autoplay-until-in-foreground=false",
         "--pref", "media.cubeb.force_null_context=true",  # no sound card needed (CI), playback still advances
         "--start-url", base + "/a.html", "--start-url", base + "/b.html",
         "--start-url", base + "/frame.html?who=remove&mode=remove&t=Embed Removed",
         "--start-url", base + "/frame.html?who=nav&mode=nav&t=Embed Nav"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)

    time.sleep(5)
    wanted = {"Tone A", "Plain Page", "Embed Removed", "Embed Nav"}
    found = wait("every page to appear as a player",
                 lambda: (lambda p: p if wanted <= set(p) else None)(players()), 120)
    print("players:", {t: n.split(".")[-1] for t, n in found.items()}, "log:", LOG[:6])
    a = found.get("Tone A")
    b = found.get("Plain Page")
    check("page A published under its MediaSession title", a is not None, list(found))
    check("page B title cleaned of '(3)' and ' - YouTube'", b is not None, list(found))
    check("a page's iframe is published as a player too", "Embed Removed" in found, list(found))
    if not (a and b and "Embed Removed" in found and "Embed Nav" in found):
        raise SystemExit(cleanup(1))

    wait("A to play", lambda: get(a, "PlaybackStatus") == "Playing", 15)
    meta = get(a, "Metadata")
    check("A artist", meta.get("xesam:artist") == ["Artist A"], meta.get("xesam:artist"))
    check("A album", meta.get("xesam:album") == "Album A", meta.get("xesam:album"))
    check("A art is the largest artwork", meta.get("mpris:artUrl", "").endswith("/art512.png"), meta.get("mpris:artUrl"))
    check("A length is the media's", abs(meta.get("mpris:length", 0) - 300e6) < 2e6, meta.get("mpris:length"))
    check("A can seek / next / previous", get(a, "CanSeek") and get(a, "CanGoNext") and get(a, "CanGoPrevious"))
    check("A url", meta.get("xesam:url", "").endswith("/a.html"), meta.get("xesam:url"))

    bm = get(b, "Metadata")
    check("B artist empty", bm.get("xesam:artist") == [], bm.get("xesam:artist"))
    check("B album falls back to the host", bm.get("xesam:album") == "127.0.0.1", bm.get("xesam:album"))
    check("B art falls back to og:image", bm.get("mpris:artUrl", "").endswith("/art512.png"), bm.get("mpris:artUrl"))
    check("B has no next/previous", not get(b, "CanGoNext") and not get(b, "CanGoPrevious"))

    # Commands
    call(a, PLAYER, "Pause")
    wait("pause to take effect", lambda: get(a, "PlaybackStatus") == "Paused", 10)
    check("Pause went through the page's own handler", ("handler", "pause") in LOG, LOG[-5:])
    call(a, PLAYER, "Play")
    wait("play to take effect", lambda: get(a, "PlaybackStatus") == "Playing", 10)
    track = get(a, "Metadata")["mpris:trackid"]
    call(a, PLAYER, "SetPosition", GLib.Variant("(ox)", (track, 120_000_000)))
    wait("seek to be seen by the page", lambda: ("seeked", "120") in LOG, 10)
    pos = wait("position near 120s", lambda: (lambda p: p if 119e6 < p < 126e6 else None)(get(a, "Position")), 10)
    check("SetPosition lands", True)
    at = get(a, "Position") / 1e6
    mark = len(LOG)
    call(a, PLAYER, "Seek", GLib.Variant("(x)", (-30_000_000,)))
    wait("relative seek", lambda: any(k == "seeked" and abs(int(v) - (at - 30)) <= 6 for k, v in LOG[mark:]), 10)
    check("Seek is relative", True)
    call(a, PLAYER, "Next")
    wait("next handler", lambda: ("handler", "nexttrack") in LOG, 10)
    check("Next reaches the page's handler", True)
    call(a, PLAYER, "Previous")
    wait("previous handler", lambda: ("handler", "previoustrack") in LOG, 10)
    check("Previous reaches the page's handler", True)
    bus.call_sync(a, "/org/mpris/MediaPlayer2", "org.freedesktop.DBus.Properties", "Set",
                  GLib.Variant("(ssv)", (PLAYER, "Volume", GLib.Variant("d", 0.5))), None, Gio.DBusCallFlags.NONE, 5000, None)
    wait("volume", lambda: ("volume", "0.50") in LOG, 10)
    check("Volume is applied", True)
    bus.call_sync(a, "/org/mpris/MediaPlayer2", "org.freedesktop.DBus.Properties", "Set",
                  GLib.Variant("(ssv)", (PLAYER, "Rate", GLib.Variant("d", 1.5))), None, Gio.DBusCallFlags.NONE, 5000, None)
    wait("rate", lambda: ("rate", "1.5") in LOG, 10)
    check("Rate is applied", True)

    # The page changes its own metadata, with no media event to announce it: the player follows, with a new track id
    before = get(a, "Metadata")["mpris:trackid"]
    command("tone", "next")
    wait("a page's own metadata change to arrive", lambda: get(a, "Metadata").get("xesam:title") == "Tone B", 10)
    title = get(a, "Metadata").get("xesam:title")
    after = get(a, "Metadata")["mpris:trackid"]
    check("a page's own metadata change is picked up", title == "Tone B", title)
    check("the new track got a new track id", after != before, (before, after))

    # A frame that goes away must take its player with it: one is removed from the DOM (no event at
    # all, caught by the background's staleness sweep), the other is navigated away (pagehide).
    command("remove", "remove-frame")
    command("nav", "navigate-frame")
    wait("the removed iframe's player to go", lambda: "Embed Removed" not in players(), 40)
    check("a removed iframe loses its player", True)
    wait("the navigated iframe's player to go", lambda: "Embed Nav" not in players(), 15)
    check("a navigated iframe loses its player", True)
    return a, b, before


if __name__ == "__main__":
    try:
        a, b, before = main()
        time.sleep(2)
        procs = children(proc.pid)
        print("\nmemory (RSS, kB):")
        total = 0
        for pid, cmd in procs:
            r = rss(pid)
            total += r
            kind = "helper" if "mpris-bridge-host" in cmd else ("main" if "-headless" in cmd and "contentproc" not in cmd and "firefox" in cmd.split()[0] else
                    ("tab/ext" if "contentproc" in cmd else "other"))
            print("  %-8s %-8d %s" % (kind, r, cmd[:90].strip()))
        print("  total", total)
    finally:
        code = cleanup()
    print("\n%s" % ("PASSED" if not failures else "FAILED: " + ", ".join(failures)))
    sys.exit(code or (1 if failures else 0))
