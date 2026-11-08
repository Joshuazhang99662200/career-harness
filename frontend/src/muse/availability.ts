import type { ConsoleDataSource } from "../dataSource";
import type { MuseSyncActions } from "./syncAdapter";

/** Offer an action only where the demo or the host actually provides its services. */
export function executionAvailability(
  source: ConsoleDataSource,
  syncActions: Partial<MuseSyncActions> | undefined,
) {
  const demo = source.mode === "demo";
  const executes = !!(source.createExecutionBatch && source.confirmExecution);
  const keepsSelection = !!(source.getSelection && source.saveSelection);
  return {
    quickExecutionAvailable:
      demo ||
      !!syncActions?.executeSelectionDirect ||
      (executes && keepsSelection),
    retryAvailable: demo || !!syncActions?.executeJobDirect || executes,
  };
}
