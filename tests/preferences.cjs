// Interest chips: max three, remembered across reloads, and a shared interest is shown on match.
const { chromium } = require("playwright");
const { begin } = require("./helpers.cjs");
const assert = require("node:assert/strict");
const fs = require("node:fs");

(async () => {
  fs.mkdirSync("test-results", { recursive: true });
  const browser = await chromium.launch({
    headless: true,
    args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"],
  });
  let pages = [];
  try {
    const contexts = await Promise.all(
      [0, 1].map(() =>
        browser.newContext({
          permissions: ["camera", "microphone"],
          viewport: { width: 1440, height: 1000 },
        }),
      ),
    );
    pages = await Promise.all(contexts.map((c) => c.newPage()));
    const [a, b] = pages;
    const url = process.env.BASE_URL || "http://127.0.0.1:8017/chat/";
    await Promise.all(pages.map((p) => p.goto(url)));

    for (const label of ["음악", "게임", "영화", "운동"]) await a.getByText(label, { exact: true }).click();
    assert.equal(await a.locator('input[name="interests"]:checked').count(), 3);
    await a.getByText("3개까지", { exact: false }).waitFor();
    await a.locator("#pref-lang").selectOption("ko");
    await a.reload();
    assert.deepEqual(
      await a.locator('input[name="interests"]:checked').evaluateAll((els) => els.map((e) => e.value)),
      ["music", "games", "movies"],
    );
    assert.equal(await a.locator("#pref-lang").inputValue(), "ko");

    await b.getByText("영화", { exact: true }).click();
    await b.locator("#pref-lang").selectOption("ko");
    await a.getByLabel("연결 직후 상대 영상 흐리게").uncheck(); // a opts out; b keeps the default
    await begin(a);
    await a.waitForFunction(() => document.querySelector("#status").textContent.includes("찾고"));
    await begin(b);
    for (const p of pages) await p.getByText("공통 관심사: 영화", { exact: true }).waitFor({ timeout: 15000 });
    assert.match(await b.locator("#peer-label").textContent(), /영화/);
    // Safety veil: b sees a blurred partner until choosing to look; a opted out.
    const veiled = (p) => p.locator("#remoteVideo").evaluate((v) => v.classList.contains("veiled"));
    assert.equal(await veiled(b), true);
    assert.equal(await veiled(a), false);
    await b.screenshot({ path: "test-results/veiled.png" });
    await b.getByRole("button", { name: /영상 보기/ }).click();
    assert.equal(await veiled(b), false);
    assert.equal(await b.locator("#reveal").isHidden(), true);
    await a.screenshot({ path: "test-results/preferences.png" });
    for (const p of pages) await p.getByRole("button", { name: "종료", exact: true }).click();
    console.log(
      "PASS: interest limit, preferences persisted, shared interest shown to both, partner video veiled until revealed",
    );
  } catch (error) {
    for (const page of pages) console.log(await page.locator("body").innerText());
    throw error;
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
