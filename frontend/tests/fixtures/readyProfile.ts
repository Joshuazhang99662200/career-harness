import type { Page } from "@playwright/test";

/** An existing person with one confirmed fact: the root opens the job board. */
export const readyProfile = (page: Page) =>
  page.route("**/api/onboarding", (route) =>
    route.fulfill({
      json: {
        schema_version: "1.0",
        protocol_version: "1.0",
        candidate_id: "CAND_DEMO",
        source: "complete",
        message: null,
        stage: "ready",
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
          status: "unknown",
          rules_version: null,
        },
      },
    }),
  );
