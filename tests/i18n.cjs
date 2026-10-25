// Switching the display language to English changes both server-rendered and script messages.
const { chromium } = require("playwright");
const assert = require("node:assert/strict");

(async () => {
  const browser = await chromium.launch({
    headless: true,
    args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"],
  });
  let page;
  try {
    const context = await browser.newContext({ permissions: ["camera", "microphone"] });
    page = await context.newPage();
    await page.goto(process.env.BASE_URL || "http://127.0.0.1:8017/chat/");
    await Promise.all([page.waitForNavigation(), page.locator("#ui-language").selectOption("en")]);
    assert.equal(await page.locator("html").getAttribute("lang"), "en");
    await page.getByRole("button", { name: "Start chatting" }).click();
    const dialog = page.getByRole("dialog", { name: "Before you start" });
    await dialog.getByLabel(/I am \d+ or older/).check();
    await dialog.locator('input[name="rules"]').check();
    await dialog.getByRole("button", { name: "Agree and start" }).click();
    await page.waitForFunction(() =>
      document.querySelector("#status").textContent.includes("Looking for someone to talk to"),
    );
    assert.equal(await page.getByRole("button", { name: "Camera off" }).isVisible(), true);
    await page.screenshot({ path: "test-results/english.png" });
    await page.getByRole("button", { name: "End", exact: true }).click();
    console.log("PASS: English UI from the language switch, including script-driven status text");
  } catch (error) {
    if (page) console.log(await page.locator("body").innerText());
    throw error;
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
