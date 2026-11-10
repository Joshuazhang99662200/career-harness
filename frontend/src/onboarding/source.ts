import type { OnboardingState } from "../hostContracts";

/** One onboarding write: the state read back from storage, and why it failed if it did. */
export interface OnboardingResult {
  state: OnboardingState;
  error?: string;
}

/** Host transport for first use. Every write must call Candidate Core and read back. */
export interface OnboardingSource {
  getState(signal?: AbortSignal): Promise<OnboardingState>;
  start(): Promise<OnboardingResult>;
  uploadResume(file: File): Promise<OnboardingResult>;
  importExtraction(requestId: string): Promise<OnboardingResult>;
  ask(): Promise<OnboardingResult>;
  /** `null` skips the question and keeps the gap unknown. */
  answer(questionId: string, answer: string | null): Promise<OnboardingResult>;
  confirm(
    evidenceId: string,
    statementDigest: string,
  ): Promise<OnboardingResult>;
  edit(
    evidenceId: string,
    statementDigest: string,
    statement: string,
  ): Promise<OnboardingResult>;
}

export function checkOnboarding(value: OnboardingState): OnboardingState {
  if (
    value?.protocol_version !== "1.0" ||
    !value.candidate_id ||
    !["complete", "missing", "unavailable"].includes(value.source) ||
    !Array.isArray(value.facts) ||
    !Array.isArray(value.resumes) ||
    !Array.isArray(value.gaps)
  )
    throw new Error("收到的本人资料格式与当前页面不匹配");
  return value;
}

/** The local console server; writes exist only when it was started with them enabled. */
export function createHttpOnboarding(): OnboardingSource {
  async function post(
    action: string,
    body: BodyInit,
    type: string,
    headers: Record<string, string> = {},
  ): Promise<OnboardingResult> {
    const response = await fetch(`/api/onboarding/${action}`, {
      method: "POST",
      cache: "no-store",
      headers: {
        "Content-Type": type,
        "X-CareerHarness-Intent": "onboarding",
        ...headers,
      },
      body,
    });
    let payload: { state?: OnboardingState; error?: { code?: string } };
    try {
      payload = await response.json();
    } catch {
      throw new Error(`HTTP ${response.status}`);
    }
    if (!payload?.state)
      throw new Error(payload?.error?.code ?? `HTTP ${response.status}`);
    return {
      state: checkOnboarding(payload.state),
      error: response.ok
        ? undefined
        : (payload.error?.code ?? `HTTP ${response.status}`),
    };
  }
  const json = (action: string, value: object = {}) =>
    post(action, JSON.stringify(value), "application/json");
  return {
    async getState(signal) {
      const response = await fetch("/api/onboarding", {
        cache: "no-store",
        signal,
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return checkOnboarding(await response.json());
    },
    start: () => json("start"),
    uploadResume: async (file) =>
      post("resume", await file.arrayBuffer(), "application/pdf", {
        "X-File-Name": encodeURIComponent(file.name),
      }),
    importExtraction: (requestId) => json("import", { request_id: requestId }),
    ask: () => json("question"),
    answer: (questionId, answer) =>
      json(
        "answer",
        answer === null
          ? { question_id: questionId, skip: true }
          : { question_id: questionId, answer },
      ),
    confirm: (evidenceId, statementDigest) =>
      json("confirm", {
        evidence_id: evidenceId,
        statement_digest: statementDigest,
      }),
    edit: (evidenceId, statementDigest, statement) =>
      json("edit", {
        evidence_id: evidenceId,
        statement_digest: statementDigest,
        statement,
      }),
  };
}
