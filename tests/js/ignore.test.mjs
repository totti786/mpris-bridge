// The ignore list rules, as the extension loads them in common.js.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const context = vm.createContext({ URL });
vm.runInContext(readFileSync(join(root, "extension", "common.js"), "utf8"), context);
const { normalize, hostOf, matches } = context.MprisIgnore;

test("normalize accepts what a person is likely to type", () => {
  assert.equal(normalize("https://www.Example.com/watch?v=1"), "example.com");
  assert.equal(normalize("example.com/path"), "example.com");
  assert.equal(normalize("*.YouTube.com"), "youtube.com");
  assert.equal(normalize("  example.com.  "), "example.com");
  assert.equal(normalize("http://user:pass@example.com:8080/x"), "example.com");
  assert.equal(normalize("127.0.0.1:8123"), "127.0.0.1");
  assert.equal(normalize("localhost"), "localhost");
});

test("normalize rejects things that are not a site", () => {
  for (const junk of ["", "   ", "not a host", "http://", "javascript:alert(1)", null, 42]) {
    assert.equal(normalize(junk), "", JSON.stringify(junk));
  }
});

test("hostOf ignores www and ports", () => {
  assert.equal(hostOf("https://www.example.com:8443/a"), "example.com");
  assert.equal(hostOf("about:blank"), "");
  assert.equal(hostOf(undefined), "");
});

test("matches covers the site and its subdomains, and nothing else", () => {
  const list = ["example.com"];
  assert.equal(matches("https://example.com/", list), true);
  assert.equal(matches("https://music.example.com/x", list), true);
  assert.equal(matches("https://www.example.com/x", list), true);
  assert.equal(matches("https://example.com.evil.test/", list), false);
  assert.equal(matches("https://notexample.com/", list), false);
  assert.equal(matches("https://example.com/", []), false);
  assert.equal(matches("about:blank", list), false);
});

test("a wildcard entry and a bare entry mean the same thing", () => {
  assert.equal(matches("https://m.youtube.com/watch", ["*.youtube.com"]), true);
  assert.equal(matches("https://m.youtube.com/watch", ["youtube.com"]), true);
});
