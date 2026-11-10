import { test, expect, type Page } from "@playwright/test";
import demo from "../src/demo.json" with { type: "json" };
import { readyProfile } from "./fixtures/readyProfile";

/** Product rules carried over from the retired templates, checked on the default panel. */
async function serve(page: Page, snapshot: object) {
  await readyProfile(page);
  await page.route("**/api/snapshot", (route) =>
    route.fulfill({ json: snapshot }),
  );
  await page.route("**/api/definitions", (route) =>
    route.fulfill({ json: {} }),
  );
  await page.goto("/");
}

async function openDetail(page: Page, title: string) {
  await page
    .getByRole("button", { name: new RegExp(`^打开岗位详情：${title}`) })
    .click();
  await page.getByRole("dialog").waitFor();
}

const openPublic = (page: Page) =>
  page.getByRole("tab", { name: "切换到公开职位补充", exact: true }).click();
const sendingControls = (page: Page) =>
  page.getByRole("button", { name: /发送|投递|批准/ });

test("a missing public source is distinct from a verified empty search", async ({
  page,
}) => {
  await serve(page, demo);
  await openPublic(page);
  await expect(
    page.getByText("公开职位补充尚未接入。", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("本次已完成读取，没有符合条件的补充岗位。", { exact: true }),
  ).toHaveCount(0);
  await expect(page.locator(".public-careers").getByRole("button")).toHaveCount(
    0,
  );
});

const listing = {
  source: "public_careers:greenhouse:synthetic-board",
  source_job_id: "101",
  title: "合成公开岗位",
  company: "合成企业",
  location: "上海",
  url: "https://boards.greenhouse.io/synthetic-board/jobs/101",
};
const record = {
  candidate_id: "CAND_DEMO",
  channel: "public_careers",
  provider: "greenhouse",
  board: "synthetic-board",
  source_job_id: "101",
  job_id: "JOB_AAAAAAAAAAAAAAAA",
  run_id: "SYNTHETIC_RUN",
  listing,
  region_decision: "review",
  observation: {
    completeness: "full",
    jd_raw: "完整合成JD。<script>window.injected=true</script>最后一行。",
  },
};

test("the supplementary channel keeps source and full text without sending controls", async ({
  page,
}) => {
  await serve(page, {
    ...demo,
    public_careers: {
      status: "complete",
      records: [record],
      runs: [
        {
          candidate_id: "CAND_DEMO",
          status: "partial",
          raw_returned: 4,
          taken: 1,
        },
      ],
    },
  });
  await openPublic(page);
  const section = page.locator(".public-careers");
  await expect(
    section.getByRole("heading", { name: "合成公开岗位", exact: true }),
  ).toBeVisible();
  await expect(
    section.getByText("地区条件待核对", { exact: true }),
  ).toBeVisible();
  await section.getByText("查看完整职位说明", { exact: true }).click();
  await expect(
    section.getByText(record.observation.jd_raw, { exact: true }),
  ).toBeVisible();
  await expect(
    section.getByRole("link", { name: "查看原始岗位" }),
  ).toHaveAttribute("href", listing.url);
  expect(
    await page.evaluate(
      () => (window as unknown as { injected?: boolean }).injected,
    ),
  ).toBeUndefined();
  await expect(section.getByRole("button")).toHaveCount(0);
  await expect(
    section.getByText("本轮读取尚未完成，已保存的岗位可继续查看。", {
      exact: true,
    }),
  ).toBeVisible();
});

test("a completed empty run and a failed run have different messages", async ({
  page,
}) => {
  await serve(page, {
    ...demo,
    public_careers: {
      status: "complete",
      records: [],
      runs: [{ candidate_id: "CAND_DEMO", status: "complete" }],
    },
  });
  await openPublic(page);
  await expect(
    page.getByText("本次已完成读取，没有符合条件的补充岗位。", { exact: true }),
  ).toBeVisible();
  await page.unrouteAll();
  await serve(page, {
    ...demo,
    public_careers: {
      status: "complete",
      records: [],
      runs: [{ candidate_id: "CAND_DEMO", status: "failed" }],
    },
  });
  await openPublic(page);
  await expect(
    page.getByText("本轮读取尚未完成，已保存的岗位可继续查看。", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByText("本次已完成读取，没有符合条件的补充岗位。", { exact: true }),
  ).toHaveCount(0);
});

test("another candidate's discovery fails closed", async ({ page }) => {
  await serve(page, {
    ...demo,
    public_careers: {
      status: "complete",
      records: [{ ...record, candidate_id: "CAND_OTHER" }],
      runs: [],
    },
  });
  await expect(page.getByRole("alert")).toContainText("来源尚未接通");
  await expect(page.getByText("合成公开岗位", { exact: true })).toHaveCount(0);
});

test("an unsafe original link is omitted", async ({ page }) => {
  await serve(page, {
    ...demo,
    public_careers: {
      status: "complete",
      records: [
        { ...record, listing: { ...listing, url: "javascript:alert(1)" } },
      ],
      runs: [],
    },
  });
  await openPublic(page);
  await expect(page.getByRole("link", { name: "查看原始岗位" })).toHaveCount(0);
});

test("a Liepin job is delivered with the online resume and shows no greeting steps", async ({
  page,
}) => {
  const snapshot = structuredClone(demo) as typeof demo;
  snapshot.jobs[0].job.platform = "liepin";
  (snapshot.jobs[0].job as Record<string, unknown>).draft_greeting =
    "PRIVATE_GREETING_FOR_AUDIT";
  await serve(page, snapshot);
  await openDetail(page, "数据工程师");
  const dialog = page.getByRole("dialog");
  const workflow = dialog.getByRole("list", { name: "工作流程" });
  await expect(workflow).toContainText("批准投递");
  await expect(workflow).toContainText("投递并核实");
  await expect(workflow).not.toContainText("招呼语");
  await expect(dialog).not.toContainText("PRIVATE_GREETING_FOR_AUDIT");
  await expect(dialog.getByRole("textbox")).toHaveCount(0);
  await expect(dialog.getByRole("button", { name: /发送/ })).toHaveCount(0);
});

test("text already sent is gray italic and cannot be edited", async ({
  page,
}) => {
  await page.goto("/?demo=1");
  await openDetail(page, "交互设计师");
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("button", { name: "查看材料与历史" }).click();
  const sent = dialog
    .getByText("已核验回读的合成历史招呼语", { exact: false })
    .first();
  await expect(sent).toBeVisible();
  await expect(sent).toHaveCSS("font-style", "italic");
  expect(
    await sent.evaluate((el) => el.closest("textarea, [contenteditable]")),
  ).toBeNull();
});

test("a closed job shows no current step", async ({ page }) => {
  const snapshot = structuredClone(demo) as typeof demo;
  (snapshot.jobs[0].job as Record<string, unknown>).pipeline_state =
    "abandoned";
  await serve(page, snapshot);
  await openDetail(page, "数据工程师");
  const workflow = page
    .getByRole("dialog")
    .getByRole("list", { name: "工作流程" });
  await expect(workflow).toBeVisible();
  await expect(workflow).not.toContainText("（现在）");
});

test("regeneration without a host service is shown as unavailable", async ({
  page,
}) => {
  await page.goto("/?demo=1");
  await openDetail(page, "数据工程师");
  const dialog = page.getByRole("dialog");
  await expect(
    dialog.getByRole("button", { name: "重新生成招呼语", exact: true }),
  ).toBeDisabled();
  await expect(dialog).toContainText("重新生成服务尚未接入");
});
