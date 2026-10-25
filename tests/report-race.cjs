// A report dialog opened for the previous partner must still report that partner, even if a new
// partner is matched while the reason is being chosen (code review finding #3).
const { chromium } = require("playwright");
const assert = require("node:assert/strict");

(async () => {
  const browser = await chromium.launch({
    headless: true,
    args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"],
  });
  let pages = [];
  try {
    const contexts = await Promise.all(
      [0, 1, 2].map(() => browser.newContext({ permissions: ["camera", "microphone"] })),
    );
    pages = await Promise.all(contexts.map((c) => c.newPage()));
    const [a, b, c] = pages;
    const url = process.env.BASE_URL || "http://127.0.0.1:8017/chat/";
    await Promise.all(pages.map((p) => p.goto(url)));
    const statusIncludes = (page, text) =>
      page.waitForFunction((t) => document.querySelector("#status").textContent.includes(t), text);
    const inCall = (page) =>
      page.waitForFunction(() => !document.querySelector("#send-button").disabled, null, { timeout: 30000 });

    await a.getByRole("button", { name: "대화 시작" }).click();
    await statusIncludes(a, "찾고");
    await b.getByRole("button", { name: "대화 시작" }).click();
    await Promise.all([inCall(a), inCall(b)]);

    await a.waitForTimeout(1300);
    await a.getByRole("button", { name: "다음 상대" }).click(); // leave b, search again
    await statusIncludes(b, "종료");
    await a.getByRole("button", { name: "신고", exact: true }).click(); // still about b
    const dialog = a.getByRole("dialog", { name: "이 상대를 신고할까요?" });
    await dialog.getByLabel("스팸·광고").check();

    await c.getByRole("button", { name: "대화 시작" }).click(); // a is matched with c meanwhile
    await Promise.all([inCall(a), inCall(c)]);
    await dialog.getByRole("button", { name: "신고하기" }).click();
    await a.getByText("신고가 접수되었습니다.", { exact: true }).waitFor();
    await c.waitForTimeout(1500);
    assert.doesNotMatch(await c.locator("#status").textContent(), /종료/);
    assert.equal(await a.locator("#send-button").isDisabled(), false); // a's call with c continues
    for (const p of [a, b, c]) await p.getByRole("button", { name: "종료", exact: true }).click();
    console.log("PASS: report submitted after a new match still targets the previous partner");
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
