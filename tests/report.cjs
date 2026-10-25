const { chromium } = require("playwright");
const { begin } = require("./helpers.cjs");
const assert = require("node:assert/strict");
const fs = require("node:fs");

(async () => {
  fs.mkdirSync("test-results", { recursive: true });
  const browser = await chromium.launch({
    headless: true,
    channel: process.env.BROWSER_CHANNEL || undefined,
    args: [
      "--use-fake-ui-for-media-stream",
      "--use-fake-device-for-media-stream",
    ],
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
    const errors = [];
    for (const page of [a, b])
      page.on("pageerror", (error) => errors.push(error.message));
    await Promise.all(
      [a, b].map((p) =>
        p.goto(process.env.BASE_URL || "http://127.0.0.1:8017/chat/"),
      ),
    );
    const statusIncludes = (page, text) =>
      page.waitForFunction(
        (t) => document.querySelector("#status").textContent.includes(t),
        text,
      );
    assert.equal(await a.locator("#report").isDisabled(), true);
    await begin(a);
    await statusIncludes(a, "찾고");
    await begin(b);
    for (const p of [a, b])
      await p.waitForFunction(
        () => !document.querySelector("#send-button").disabled,
        { timeout: 30000 },
      );

    await a.getByRole("button", { name: "신고", exact: true }).click();
    const dialog = a.getByRole("dialog", { name: "이 상대를 신고할까요?" });
    await dialog.waitFor();
    await dialog.getByRole("button", { name: "취소" }).click();
    assert.equal(await dialog.isVisible(), false);
    assert.equal(await a.locator("#send-button").isDisabled(), false);

    await a.getByRole("button", { name: "신고", exact: true }).click();
    await dialog.getByLabel("욕설·괴롭힘").check();
    await a.screenshot({ path: "test-results/report-dialog.png" });
    await dialog.getByRole("button", { name: "신고하기" }).click();
    await statusIncludes(a, "신고가 접수");
    await statusIncludes(b, "종료");
    assert.equal(await a.locator("#report").isDisabled(), true);
    assert.equal(await a.locator("#remoteVideo").evaluate((v) => v.srcObject), null);

    // A reported pair must not be matched again, even when both look for a partner.
    await a.waitForTimeout(1300);
    await a.getByRole("button", { name: "다음 상대" }).click();
    await b.getByRole("button", { name: "다음 상대" }).click();
    await a.waitForTimeout(3000);
    for (const p of [a, b]) {
      assert.match(await p.locator("#status").textContent(), /찾고/);
      assert.equal(await p.locator("#send-button").isDisabled(), true);
    }
    for (const p of [a, b])
      await p.getByRole("button", { name: "종료", exact: true }).click();
    assert.deepEqual(errors, []);
    console.log(
      "PASS: report dialog cancel/submit, peer notified, reported pair never re-matched",
    );
  } catch (error) {
    for (const page of pages)
      console.log(await page.locator("body").innerText());
    throw error;
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
