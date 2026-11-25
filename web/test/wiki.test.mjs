// The help-page renderer, on a synthetic page using every construct the
// shipped doc/*.wiki pages use.
import { test } from "node:test";
import assert from "node:assert/strict";
import { decodeText, renderWiki } from "../src/wiki.ts";

const page = [
  "(:title Exposure <Menu>:)",
  "(:redmessageid 20514:) ",
  "Intro line one",
  "line two with '''bold''' and ''italic'' and &red1over;48&redsec; at 3200&redkelvin;.",
  "",
  "!! Modes",
  "* '''Off''': off",
  "** nested [[RedUiWBDialog#Presets | White balance]]",
  "(:if equal {$SensorFamily} Helium:)# Helium step(:ifend:)",
  "(:rednote Note text :)",
  "(:redwarning Careful:)",
  "%center%Attach: guys.png",
  "* %gray%'''Grey'''%%: no signal [[#anchor]]",
  "----",
].join("\r\n");

test("renders RED's PmWiki subset", () => {
  const { title, html } = renderWiki(page, (n) => (n === "guys.png" ? "blob:x" : undefined));
  assert.equal(title, "Exposure <Menu>");
  assert.match(html, /<p>Intro line one line two with <b>bold<\/b> and <i>italic<\/i> and 1\/48 s at 3200K\.<\/p>/);
  assert.match(html, /<h4>Modes<\/h4>/);
  assert.match(html, /<ul>\n<li><b>Off<\/b>: off\n<ul>\n<li>nested <a href="#" data-page="RedUiWBDialog" data-anchor="Presets">White balance<\/a>/);
  assert.match(html, /<ol>\n<li><span class="wk-cond">SensorFamily = Helium<\/span>Helium step/);
  assert.match(html, /<div class="wk-note">Note text<\/div>/);
  assert.match(html, /<div class="wk-warning">Careful<\/div>/);
  assert.match(html, /<p class="wk-center"><img src="blob:x" alt="guys.png" data-image="guys.png"><\/p>/);
  assert.match(html, /<span style="color:gray"><b>Grey<\/b><\/span>: no signal <a id="wk-anchor"><\/a>/);
  assert.match(html, /<hr>/);
  assert.doesNotMatch(html, /\(:|'''|\[\[|<Menu>/);
});

test("escapes markup in page text", () => {
  const { html } = renderWiki('<script>alert(1)</script> "x"', () => undefined);
  assert.equal(html, "<p>&lt;script&gt;alert(1)&lt;/script&gt; &quot;x&quot;</p>");
});

test("decodeText: UTF-8, Windows-1252 fallback, binary", () => {
  assert.equal(decodeText(new TextEncoder().encode("“ok” °")), "“ok” °");
  assert.equal(decodeText(new Uint8Array([0x93, 0x6f, 0x6b, 0x94, 0xb0])), "“ok”°");
  assert.equal(decodeText(new Uint8Array([1, 0, 2])), null);
});
