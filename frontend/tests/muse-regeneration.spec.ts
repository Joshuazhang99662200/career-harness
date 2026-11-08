import { test, expect, type Page } from "@playwright/test";

/** Regeneration through an injected synthetic host; no AI, network or external action runs. */
async function openFixture(page: Page, query = "") {
  await page.goto(`/tests/fixtures/muse-sync-host.html${query}`);
  await page.getByRole("button", { name: /^打开岗位详情：数据工程师/ }).click();
  return page.getByRole("dialog");
}

test("a regeneration whose before-text is not recorded is never shown as verified", async ({
  page,
}) => {
  const dialog = await openFixture(page, "?corrupt=1");
  await dialog
    .getByRole("button", { name: "重新生成招呼语", exact: true })
    .click();
  await page.evaluate(() => (window as any).syncFixture.resume());
  await expect(dialog).toContainText("新稿是否保存还不确定");
  await expect(dialog).not.toContainText("已生成新稿");
  await expect(
    dialog.getByRole("button", { name: "重新生成招呼语", exact: true }),
  ).toBeDisabled();
});

test("regeneration keeps the old draft, blocks edits while running and voids the old approval", async ({
  page,
}) => {
  const dialog = await openFixture(page);
  const text = dialog.getByRole("textbox", {
    name: "招呼语（拟发送，可编辑）",
  });
  const before = await text.inputValue();
  await dialog
    .getByRole("button", { name: "重新生成招呼语", exact: true })
    .click();
  await expect(text).toBeDisabled();
  await page.evaluate(() => (window as any).syncFixture.resume());
  await expect(text).toHaveValue(before + " 合成宿主生成的新版全文。");
  await expect(dialog).toContainText("已生成新稿（尚未发送）");
  const state = await page.evaluate(
    async () => await (window as any).syncFixture.state(),
  );
  expect(state.jobs[0].materials).toHaveLength(2);
  expect(
    state.jobs[0].events.filter((e: any) => e.kind === "approve_material"),
  ).toHaveLength(1);
  expect(state.batches).toHaveLength(0);
  await expect(dialog.getByRole("button", { name: "确认发送" })).toHaveCount(0);
  await dialog.getByRole("button", { name: "查看材料与历史" }).click();
  await expect(dialog).toContainText(before);
});
