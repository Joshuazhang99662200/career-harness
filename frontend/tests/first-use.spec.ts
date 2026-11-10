import { test, expect } from "@playwright/test";

const state = (extra: object) => ({
  schema_version: "1.0",
  protocol_version: "1.0",
  candidate_id: "CAND_SYNTHETIC",
  source: "complete",
  message: null,
  stage: "collecting",
  resumes: [],
  experiences: [],
  facts: [],
  open_question: null,
  answered_count: 0,
  skipped_count: 0,
  gaps: [],
  readiness: null,
  configuration: {
    schema_version: "1.0",
    status: "not_initialized",
    rules_version: null,
  },
  ...extra,
});

test("a new user is pointed to the conversation, not an empty board or the demo", async ({
  page,
}) => {
  await page.route("/api/onboarding", (route) =>
    route.fulfill({ json: state({ source: "missing", stage: "not_started" }) }),
  );
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "还没有本人资料" }),
  ).toBeVisible();
  await expect(page.getByText("首次引导在对话里进行")).toBeVisible();
  await expect(page.getByRole("textbox")).toHaveCount(0);
  await expect(page.locator("input")).toHaveCount(0);
  await expect(page.getByText("合成演示")).toHaveCount(0);
  // Fetch results and progress stay one click away.
  await page.route("**/api/snapshot", (route) =>
    route.fulfill({ status: 503, body: "{}" }),
  );
  await page.getByRole("button", { name: "查看岗位进展" }).click();
  await expect(
    page.getByRole("button", { name: "本人资料与就绪情况" }),
  ).toBeVisible();
});

test("progress is shown read-only while the conversation is under way", async ({
  page,
}) => {
  await page.route("/api/onboarding", (route) =>
    route.fulfill({
      json: state({
        answered_count: 1,
        open_question: {
          schema_version: "1.0",
          question_id: "QUESTION_SKILLS",
          gap_id: "GAP_SKILLS",
          text: "你在真实工作或项目里实际用过哪些技能？",
          stored_text:
            "Which skills have you applied in real work or projects?",
          asked_at: "2026-11-10T00:00:00Z",
        },
      }),
    }),
  );
  await page.goto("/");
  await expect(
    page.getByText(
      "正在等你在对话里回答：你在真实工作或项目里实际用过哪些技能？",
    ),
  ).toBeVisible();
  await expect(page.getByRole("textbox")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: /确认|保存|回答/ }),
  ).toHaveCount(0);
});

test("a read failure stays a failure", async ({ page }) => {
  await page.route("/api/onboarding", (route) =>
    route.fulfill({ status: 503, body: "{}" }),
  );
  await page.goto("/");
  await expect(page.getByRole("alert")).toContainText("本人资料状态读取失败");
  await expect(page.getByText("合成演示")).toHaveCount(0);
});
