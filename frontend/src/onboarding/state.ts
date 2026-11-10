import type { OnboardingState } from "../hostContracts";

/** Read-only: first use happens in the conversation, this only shows where it stands. */
export async function readOnboarding(
  signal?: AbortSignal,
): Promise<OnboardingState> {
  const response = await fetch("/api/onboarding", {
    cache: "no-store",
    signal,
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const value: OnboardingState = await response.json();
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
