import { test, expect } from "@playwright/test";
import demo from "../src/demo.json" with { type: "json" };

const empty = {
  ...demo,
  jobs: [],
  runs: [],
  sources: [{ name: "pipeline", status: "missing" }],
};

test("with no jobs yet the page says so in one line and shows no profile or facts", async ({
  page,
}) => {
  const asked: string[] = [];
  page.on("request", (request) => asked.push(new URL(request.url()).pathname));
  await page.route("**/api/snapshot", (route) =>
    route.fulfill({ json: empty }),
  );
  await page.goto("/");
  await expect(page.getByRole("status")).toHaveText("还没有岗位进来。");
  await expect(page.locator("input, textarea")).toHaveCount(0);
  await expect(page.getByText("合成演示")).toHaveCount(0);
  expect(asked).not.toContain("/api/onboarding");
});

test("once jobs arrive the root opens the job board", async ({ page }) => {
  await page.route("**/api/snapshot", (route) => route.fulfill({ json: demo }));
  await page.route("**/api/definitions", (route) =>
    route.fulfill({ json: {} }),
  );
  await page.goto("/");
  await expect(
    page.locator(".muse-space [aria-label='岗位列表']"),
  ).toBeVisible();
});
