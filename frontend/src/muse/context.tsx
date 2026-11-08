import { createContext, useContext } from "react";
import type { MuseActions } from "./contracts";
import type { Snapshot } from "../contracts";

/** Read-only loader for the supplementary public-careers channel; absent means not connected. */
export type MusePublicCareers = () => Promise<Snapshot["public_careers"]>;

export interface MuseConfiguration {
  refreshMs?: number;
  regenerationAvailable?: boolean;
  quickExecutionAvailable?: boolean;
  retryAvailable?: boolean;
  batchRefreshMs?: number;
  progressBatchLimit?: number;
  executionSummary?: string;
  readonlyReason?: string;
  disabledDecisions?: Partial<Record<string, string>>;
}
export type MuseCvFiles = Record<number, { v1?: string; v2?: string }>;
export const MuseContext = createContext<{
  actions: MuseActions;
  configuration: MuseConfiguration;
  cvFiles: MuseCvFiles;
  publicCareers?: MusePublicCareers;
} | null>(null);
export function useMuseActions() {
  const context = useContext(MuseContext);
  if (!context) throw new Error("Muse actions are not connected");
  return context.actions;
}
export const useMuseConfiguration = () =>
  useContext(MuseContext)?.configuration ?? {};
export const useMuseCvFiles = () => useContext(MuseContext)?.cvFiles ?? {};
export const useMusePublicCareers = () =>
  useContext(MuseContext)?.publicCareers;
