// Cross-browser WebRTC: a Chromium user and a Firefox user must negotiate media and chat.
const { chromium, firefox } = require("playwright");
const assert = require("node:assert/strict");

(async () => {
  const chrome = await chromium.launch({
    headless: true,
    args: [
      "--use-fake-ui-for-media-stream",
      "--use-fake-device-for-media-stream",
    ],
  });
  const gecko = await firefox.launch({
    headless: true,
    firefoxUserPrefs: {
      "media.navigator.streams.fake": true,
      "media.navigator.permission.disabled": true,
      "media.autoplay.default": 0,
    },
  });
  let pages = [];
  try {
    const a = await (
      await chrome.newContext({ permissions: ["camera", "microphone"] })
    ).newPage();
    const b = await (await gecko.newContext()).newPage();
    pages = [a, b];
    const errors = [];
    for (const page of pages)
      page.on("pageerror", (error) => errors.push(error.message));
    const url = process.env.BASE_URL || "http://127.0.0.1:8017/chat/";
    await Promise.all(pages.map((p) => p.goto(url)));
    await a.getByRole("button", { name: "대화 시작" }).click();
    await a.waitForFunction(() =>
      document.querySelector("#status").textContent.includes("찾고"),
    );
    await b.getByRole("button", { name: "대화 시작" }).click();
    for (const p of pages) {
      await p.waitForFunction(
        () => !document.querySelector("#send-button").disabled,
        { timeout: 30000 },
      );
      await p.waitForFunction(
        () => document.querySelector("#remoteVideo").videoWidth > 0,
      );
    }
    await a.locator("#message").fill("hello from chromium");
    await a.getByRole("button", { name: "메시지 전송" }).click();
    await b.getByText("상대방: hello from chromium", { exact: true }).waitFor();
    await b.locator("#message").fill("hello from firefox");
    await b.getByRole("button", { name: "메시지 전송" }).click();
    await a.getByText("상대방: hello from firefox", { exact: true }).waitFor();
    await b.getByRole("button", { name: "종료", exact: true }).click();
    await a.waitForFunction(() =>
      document.querySelector("#status").textContent.includes("종료"),
    );
    await a.getByRole("button", { name: "종료", exact: true }).click();
    assert.deepEqual(errors, []);
    console.log(
      "PASS: Chromium <-> Firefox media negotiation, both-way chat, departure notice",
    );
  } catch (error) {
    for (const page of pages)
      console.log(await page.locator("body").innerText());
    throw error;
  } finally {
    await chrome.close();
    await gecko.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
