# Changelog

## 1.1.0

- Ignore list: a toolbar button ignores the site you are on, and an options page keeps the list. An entry covers the site and
  its subdomains, and ignored sites publish nothing.
- Players are named after their tab (`Firefox — <title>`) instead of all being called "Firefox".
- A navigating frame, and a page put in the bfcache, take their player with them at once; a frame removed from the page without
  any event is noticed within about 20 seconds.
- `Stop` now stops at the beginning instead of only pausing, and `SetPosition` ignores a stale track id, as the MPRIS spec says.
- Silent background videos (muted, no controls, no media session of their own) no longer appear as players.
- The end-to-end suite registers the helper itself, checks a page changing its own metadata, and covers both ways an iframe can
  lose its player. It now runs in CI.

## 1.0.0

First release. Every Firefox tab with media becomes its own MPRIS player, with title, artist, album and cover art from the page, seeking, volume, speed, next and previous where the page offers them, and a paused state while a stream is buffering. The helper is a small Rust binary; the extension is plain JavaScript.
