// Measures whether an ongoing call survives a disruption.
//   signaling: the caller's WebSocket closes mid-call (real close).
//   media:     the caller's RTCPeerConnection reports "failed" (injected state event;
//              headless browsers cannot cut the media path itself).
// A trial counts as kept when, after the disruption, the same partner still receives chat
// within 15 s and never sees the "partner left" state.
// Usage: node tests/resilience.cjs [trials=5] [--assert]   (prints one JSON summary)
const { chromium } = require("playwright");
const { begin } = require("./helpers.cjs");

const trials = Number(process.argv.find((a) => /^\d+$/.test(a)) || 5);
const mustPass = process.argv.includes("--assert");
const url = process.env.BASE_URL || "http://127.0.0.1:8017/chat/";

const instrument = () => {
  const OriginalSocket = window.WebSocket;
  window.testSockets = [];
  window.WebSocket = class extends OriginalSocket {
    constructor(...args) {
      super(...args);
      window.testSockets.push(this);
    }
  };
  const OriginalPeer = window.RTCPeerConnection;
  window.testPeers = [];
  window.RTCPeerConnection = class extends OriginalPeer {
    constructor(...args) {
      super(...args);
      window.testPeers.push(this);
      const real = Object.getOwnPropertyDescriptor(OriginalPeer.prototype, "connectionState").get;
      Object.defineProperty(this, "connectionState", {
        get: () => this.fakeState || real.call(this),
      });
    }
    // An ICE restart (sent or received) ends the injected failure, like a recovered path.
    async createOffer(options) {
      if (options?.iceRestart) this.fakeState = null;
      return super.createOffer(options);
    }
    async setRemoteDescription(description) {
      if (description?.type === "offer") this.fakeState = null;
      return super.setRemoteDescription(description);
    }
  };
  window.breakMedia = () => {
    const pc = window.testPeers.at(-1);
    pc.fakeState = "failed";
    pc.dispatchEvent(new Event("connectionstatechange"));
  };
};

const statusText = (page) => page.locator("#status").textContent();

async function connected(pages) {
  for (const p of pages)
    await p
      .waitForFunction(
        () =>
          !document.querySelector("#send-button").disabled &&
          document.querySelector("#remoteVideo").videoWidth > 0,
        null,
        { timeout: 30000 },
      )
      .catch(async (error) => {
        const states = await Promise.all(
          pages.map((q) =>
            q.evaluate(() =>
              ["#status", "#notice"].map((s) => document.querySelector(s).textContent).join(" | "),
            ),
          ),
        );
        throw new Error(`call never connected: ${states.join(" // ")}`, { cause: error });
      });
}

async function trial(a, b, scenario, index) {
  await begin(a);
  await a.waitForFunction(() => document.querySelector("#status").textContent.includes("찾고"));
  await begin(b);
  await connected([a, b]);
  await b.evaluate(() => {
    window.sawLeft = false;
    new MutationObserver(() => {
      if (document.querySelector("#status").textContent.includes("종료")) window.sawLeft = true;
    }).observe(document.querySelector("#status"), { childList: true, characterData: true, subtree: true });
  });
  const started = Date.now();
  if (scenario === "signaling") await a.evaluate(() => window.testSockets.at(-1).close());
  else await a.evaluate(() => window.breakMedia());
  const probe = `probe-${scenario}-${index}`;
  let kept = false;
  // Keep trying to chat: success means the same partner gets it without having been told we left.
  while (Date.now() - started < 15000 && !kept) {
    await a.waitForTimeout(500);
    const canSend = await a.evaluate(() => !document.querySelector("#send-button").disabled);
    if (canSend) {
      await a.locator("#message").fill(probe);
      await a.getByRole("button", { name: "메시지 전송" }).click();
      kept = await b
        .getByText(`상대방: ${probe}`, { exact: true })
        .waitFor({ timeout: 2000 })
        .then(() => true, () => false);
    }
  }
  // Chat alone travels through the server; also require the media path to be back.
  const mediaBack = (p) =>
    p
      .waitForFunction(
        () =>
          document.querySelector("#status").textContent.includes("연결됐어요") &&
          document.querySelector("#remoteVideo").videoWidth > 0,
        null,
        { timeout: Math.max(1000, 15000 - (Date.now() - started)) },
      )
      .then(() => true, () => false);
  kept = kept && (await mediaBack(a)) && (await mediaBack(b)) && !(await b.evaluate(() => window.sawLeft));
  const result = { kept, ms: kept ? Date.now() - started : null, a: await statusText(a), b: await statusText(b) };
  for (const p of [a, b]) await p.getByRole("button", { name: "종료", exact: true }).click();
  await a.waitForTimeout(300);
  return result;
}

(async () => {
  const browser = await chromium.launch({
    headless: true,
    args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"],
  });
  const summary = {};
  try {
    const contexts = await Promise.all(
      [0, 1].map(() => browser.newContext({ permissions: ["camera", "microphone"] })),
    );
    const [a, b] = await Promise.all(contexts.map((c) => c.newPage()));
    for (const p of [a, b]) {
      await p.addInitScript(instrument);
      await p.goto(url);
    }
    for (const scenario of ["signaling", "media"]) {
      const runs = [];
      for (let i = 0; i < trials; i++) runs.push(await trial(a, b, scenario, i));
      const kept = runs.filter((r) => r.kept);
      summary[scenario] = {
        trials,
        kept: kept.length,
        kept_pct: Math.round((100 * kept.length) / trials),
        recovery_ms: kept.map((r) => r.ms),
        failed_states: runs.filter((r) => !r.kept).map((r) => `${r.a} / ${r.b}`),
      };
    }
  } finally {
    await browser.close();
  }
  console.log(JSON.stringify(summary));
  if (mustPass && Object.values(summary).some((s) => s.kept !== s.trials)) process.exitCode = 1;
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
