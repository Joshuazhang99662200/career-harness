import { test, expect, type Route } from "@playwright/test";

const base = {
  schema_version: "1.0",
  protocol_version: "1.0",
  candidate_id: "CAND_SYNTHETIC",
  message: null,
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
};

const fact = {
  schema_version: "1.0",
  evidence_id: "EVID_SYNTHETIC",
  type: "experience",
  statement: "搭建过合成评测集。",
  entity: "",
  skills: [],
  metrics: [],
  source_type: "interview",
  source_reference: "QUESTION_EXPERIENCE:answer",
  resume_id: null,
  resume_page: null,
  confidence: "explicit",
  confirmed: false,
  confirmable: true,
  statement_digest: "sha256:shown",
};

const readiness = (confirmed: number) => ({
  schema_version: "1.0",
  candidate_id: "CAND_SYNTHETIC",
  readiness: {
    schema_version: "1.0",
    profile_completeness: 0.3,
    high_value_gaps: [],
    weak_claim_evidence_ids: [],
    confirmed_evidence_count: confirmed,
    target_role_readiness: 0.2,
  },
  open_gap_count: 1,
  unconfirmed_evidence_count: 1 - confirmed,
});

test("without a host the root shows a failure, not the board or the demo", async ({
  page,
}) => {
  await page.route("/api/onboarding", (route) =>
    route.fulfill({ status: 503, body: "{}" }),
  );
  await page.goto("/");
  await expect(page.getByRole("alert")).toContainText("本人资料状态读取失败");
  await expect(page.getByText("合成演示")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "岗位进展" })).toHaveCount(0);
});

test("a new user starts, and a fact is confirmed by its shown digest", async ({
  page,
}) => {
  const posts: Array<{ action: string; body: unknown; intent: string | null }> =
    [];
  let state: Record<string, unknown> = {
    ...base,
    source: "missing",
    writable: true,
    stage: "not_started",
  };
  await page.route("/api/onboarding", (route) =>
    route.fulfill({ json: state }),
  );
  await page.route("/api/onboarding/*", async (route: Route) => {
    const request = route.request();
    const action = new URL(request.url()).pathname.split("/").pop()!;
    posts.push({
      action,
      body: request.postDataJSON(),
      intent: request.headers()["x-careerharness-intent"] ?? null,
    });
    if (action === "start")
      state = {
        ...state,
        source: "complete",
        stage: "collecting",
        facts: [fact],
        readiness: readiness(0),
      };
    if (action === "confirm")
      state = {
        ...state,
        stage: "ready",
        facts: [{ ...fact, confirmed: true }],
        readiness: readiness(1),
      };
    await route.fulfill({ json: { state } });
  });

  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "开始求职前，先整理你的经历" }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "查看岗位进展" })).toHaveCount(
    0,
  );
  await page.getByRole("button", { name: "开始", exact: true }).click();
  await expect(page.getByText("搭建过合成评测集。")).toBeVisible();
  await expect(page.getByText("待你确认", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "属实，确认这条" }).click();
  await expect(page.getByText("已确认事实：1 条")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "查看岗位进展" }),
  ).toBeVisible();
  expect(posts).toEqual([
    { action: "start", body: {}, intent: "onboarding" },
    {
      action: "confirm",
      body: { evidence_id: "EVID_SYNTHETIC", statement_digest: "sha256:shown" },
      intent: "onboarding",
    },
  ]);
});

test("a read-only server shows the record and disables every write", async ({
  page,
}) => {
  await page.route("/api/onboarding", (route) =>
    route.fulfill({
      json: {
        ...base,
        source: "missing",
        writable: false,
        stage: "not_started",
      },
    }),
  );
  await page.goto("/");
  await expect(page.getByText("只读方式打开")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "开始", exact: true }),
  ).toBeDisabled();
});
