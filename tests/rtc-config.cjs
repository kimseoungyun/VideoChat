const { chromium } = require("playwright");
const assert = require("node:assert/strict");

(async () => {
  const browser = await chromium.launch({
    headless: true,
    channel: process.env.BROWSER_CHANNEL || undefined,
    args: [
      "--use-fake-ui-for-media-stream",
      "--use-fake-device-for-media-stream",
    ],
  });
  try {
    const contexts = await Promise.all(
      [0, 1].map(() =>
        browser.newContext({ permissions: ["camera", "microphone"] }),
      ),
    );
    const [a, b] = await Promise.all(contexts.map((c) => c.newPage()));
    await a.addInitScript(() => {
      const OriginalPeer = window.RTCPeerConnection;
      window.createdPeers = 0;
      window.RTCPeerConnection = class extends OriginalPeer {
        constructor(...args) {
          super(...args);
          window.createdPeers++;
        }
      };
    });
    await Promise.all(
      [a, b].map((p) =>
        p.goto(process.env.BASE_URL || "http://127.0.0.1:8017/chat/"),
      ),
    );
    const startPair = async () => {
      await a.getByRole("button", { name: "대화 시작" }).click();
      await a.waitForFunction(() =>
        document.querySelector("#status").textContent.includes("찾고"),
      );
      await b.getByRole("button", { name: "대화 시작" }).click();
    };
    const stopPair = () =>
      Promise.all(
        [a, b].map((p) =>
          p.getByRole("button", { name: "종료", exact: true }).click(),
        ),
      );

    await a.route("**/chat/rtc-config/", (route) =>
      route.fulfill({ status: 503, body: "unavailable" }),
    );
    await startPair();
    await a.waitForFunction(() =>
      document.querySelector("#status").textContent.includes("완료하지"),
    );
    assert.equal(await a.evaluate(() => window.createdPeers), 0);
    await stopPair();
    await a.unroute("**/chat/rtc-config/");

    let release;
    const gate = new Promise((resolve) => {
      release = resolve;
    });
    let arrived;
    const requested = new Promise((resolve) => {
      arrived = resolve;
    });
    await a.route("**/chat/rtc-config/", async (route) => {
      arrived();
      await gate;
      await route.fulfill({ json: { iceServers: [] } }).catch(() => {});
    });
    await startPair();
    await requested;
    await stopPair();
    release();
    await a.getByRole("button", { name: "대화 시작" }).waitFor();
    assert.equal(await a.evaluate(() => window.createdPeers), 0);
    assert.equal(
      await a.locator("#localVideo").evaluate((video) => video.srcObject),
      null,
    );
    console.log(
      "PASS: RTC config failure recovers to usable UI; stop aborts pending config without creating a peer",
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
