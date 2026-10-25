const { chromium } = require("playwright");
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
      "--autoplay-policy=no-user-gesture-required",
    ],
  });
  const errors = [];
  const contexts = [];
  let pages = [];
  try {
    for (let i = 0; i < 3; i++)
      contexts.push(
        await browser.newContext({
          permissions: ["camera", "microphone"],
          viewport: { width: 1440, height: 1000 },
        }),
      );
    pages = await Promise.all(contexts.map((c) => c.newPage()));
    for (const page of pages)
      await page.addInitScript(() => {
        const OriginalSocket = window.WebSocket;
        window.testSockets = [];
        window.WebSocket = class extends OriginalSocket {
          constructor(...args) {
            super(...args);
            window.testSockets.push(this);
          }
        };
      });
    for (const page of pages)
      page.on("pageerror", (error) => errors.push(error.message));
    await Promise.all(
      pages.map((p) =>
        p.goto(process.env.BASE_URL || "http://127.0.0.1:8017/chat/"),
      ),
    );
    await pages[0].screenshot({
      path: "test-results/lobby-desktop.png",
      fullPage: true,
    });
    await pages[0].getByRole("button", { name: "대화 시작" }).click();
    await pages[0].waitForFunction(() =>
      document.querySelector("#status").textContent.includes("찾고"),
    );
    await pages[1].getByRole("button", { name: "대화 시작" }).click();
    for (const p of pages.slice(0, 2)) {
      await p.waitForFunction(
        () => !document.querySelector("#send-button").disabled,
        { timeout: 30000 },
      );
      await p.waitForFunction(
        () => document.querySelector("#remoteVideo").videoWidth > 0,
      );
      await p.waitForFunction(() => {
        const audio = document
          .querySelector("#remoteVideo")
          .srcObject?.getAudioTracks()[0];
        return audio?.readyState === "live";
      });
    }
    await pages[0].locator("#message").fill('<script>alert("test")</script>');
    await pages[0].getByRole("button", { name: "메시지 전송" }).click();
    await pages[1]
      .getByText('상대방: <script>alert("test")</script>', { exact: true })
      .waitFor();
    await pages[0].getByRole("button", { name: "카메라 끄기" }).click();
    await pages[1].waitForFunction(() =>
      document.querySelector("#peer-label").textContent.includes("카메라 꺼짐"),
    );
    await pages[0].getByRole("button", { name: "카메라 켜기" }).click();
    await pages[0].getByRole("button", { name: "마이크 끄기" }).click();
    await pages[1].waitForFunction(() =>
      document.querySelector("#peer-label").textContent.includes("음소거"),
    );
    await pages[0].screenshot({
      path: "test-results/connected-desktop.png",
      fullPage: true,
    });
    await pages[2].bringToFront();
    await pages[2].getByRole("button", { name: "대화 시작" }).click();
    await pages[2].waitForFunction(() =>
      document.querySelector("#status").textContent.includes("찾고"),
    );
    await pages[0].getByRole("button", { name: "다음 상대" }).click();
    await pages[2].waitForFunction(
      () => !document.querySelector("#send-button").disabled,
    );
    await pages[1].waitForFunction(() =>
      document.querySelector("#status").textContent.includes("종료"),
    );
    await pages[0].getByRole("button", { name: "종료", exact: true }).click();
    assert.equal(
      await pages[0].locator("#localVideo").evaluate((v) => v.srcObject),
      null,
    );
    await pages[2].waitForFunction(() =>
      document.querySelector("#status").textContent.includes("종료"),
    );
    await pages[2].getByRole("button", { name: "종료", exact: true }).click();
    await pages[1].getByRole("button", { name: "종료", exact: true }).click();
    await pages[1].getByRole("button", { name: "대화 시작" }).click();
    await pages[1].waitForFunction(() =>
      document.querySelector("#status").textContent.includes("찾고"),
    );
    const socketCount = await pages[1].evaluate(
      () => window.testSockets.length,
    );
    await pages[1].evaluate(() => window.testSockets.at(-1).close());
    await pages[1].waitForFunction(
      (count) =>
        window.testSockets.length > count &&
        document.querySelector("#status").textContent.includes("찾고"),
      socketCount,
    );
    await pages[1].getByRole("button", { name: "종료", exact: true }).click();

    await pages[2].evaluate(() => {
      navigator.mediaDevices.getUserMedia = async () => {
        throw new DOMException("Denied", "NotAllowedError");
      };
    });
    const beforeDenied = await pages[2].evaluate(
      () => window.testSockets.length,
    );
    await pages[2].getByRole("button", { name: "대화 시작" }).click();
    await pages[2]
      .getByText("카메라와 마이크 권한을 허용한 후 다시 시작해 주세요.", {
        exact: true,
      })
      .waitFor();
    assert.equal(
      await pages[2].evaluate(() => window.testSockets.length),
      beforeDenied,
    );
    await pages[0].reload();
    await pages[0].setViewportSize({ width: 390, height: 844 });
    await pages[0].screenshot({
      path: "test-results/lobby-mobile.png",
      fullPage: true,
    });
    assert.equal(
      await pages[0].evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      ),
      false,
    );
    assert.deepEqual(errors, []);
    console.log(
      "PASS: audio/video tracks, chat, camera/mic toggles, three-client next, stop, reconnect, denied media, mobile width, no page errors",
    );
  } catch (error) {
    for (const page of pages)
      console.log(await page.locator("body").innerText());
    throw error;
  } finally {
    await Promise.all(contexts.map((c) => c.close()));
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
