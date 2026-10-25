// Start a chat the way a user does, answering the first-visit age/rules consent dialog.
async function begin(page) {
  await page.getByRole("button", { name: "대화 시작" }).click();
  await page.waitForFunction(
    () => document.querySelector("#consent-dialog").open || document.querySelector("#start").hidden,
  );
  if (await page.evaluate(() => document.querySelector("#consent-dialog").open)) {
    const dialog = page.getByRole("dialog", { name: "시작하기 전에 확인해 주세요" });
    await dialog.getByLabel(/만 \d+세 이상입니다/).check();
    await dialog.locator('input[name="rules"]').check();
    await dialog.getByRole("button", { name: "동의하고 시작" }).click();
    await page.waitForFunction(() => document.querySelector("#start").hidden);
  }
}

module.exports = { begin };
