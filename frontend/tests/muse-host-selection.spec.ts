import { test, expect } from "@playwright/test";
import demo from "../src/demo.json" with { type: "json" };
import { createDemoSource } from "../src/demoHost";
import { createMuseActions } from "../src/muse/adapter";
import type {
  HostSelection,
  HostSelectionRequest,
} from "../src/hostContracts";

/** A real-host source: selection is kept by the host (the repository), not the browser. */
async function hostSetup(withSelection = true) {
  let persisted: string | null = null;
  const source = await createDemoSource({
    snapshot: structuredClone(demo),
    definitions: {},
    storage: {
      load: () => persisted,
      save: (v) => {
        persisted = v;
      },
    },
  });
  let selection: HostSelection = {
    candidate_id: demo.candidate_id,
    version: 0,
    contact_ids: [],
  };
  const requests: HostSelectionRequest[] = [];
  const interference = { next: false };
  Object.assign(source, { mode: "host" });
  if (withSelection)
    Object.assign(source, {
      getSelection: async () => structuredClone(selection),
      saveSelection: async (request: HostSelectionRequest) => {
        requests.push(request);
        if (interference.next) {
          // Another device changed the selection after this panel read it.
          interference.next = false;
          selection = { ...selection, version: selection.version + 1 };
        }
        if (request.expected_version !== selection.version)
          return {
            status: "rejected" as const,
            message: "选择刚被更新过，请刷新后再操作；这次没有保存。",
            selection: structuredClone(selection),
          };
        const chosen = new Set(selection.contact_ids);
        for (const id of request.contact_ids) {
          if (["select", "select_visible"].includes(request.operation))
            chosen.add(id);
          else if (request.operation === "invert_visible")
            chosen.has(id) ? chosen.delete(id) : chosen.add(id);
          else chosen.delete(id);
        }
        if (request.operation === "clear_all") chosen.clear();
        selection = {
          ...selection,
          version: selection.version + 1,
          contact_ids: [...chosen],
        };
        return {
          status: "saved" as const,
          message: "已保存选择",
          selection: structuredClone(selection),
        };
      },
    });
  const store = new Map<string, string>();
  const api = createMuseActions(source, {
    operationStore: {
      load: (k: string) => store.get(k) ?? null,
      save: (k: string, v: string) => {
        store.set(k, v);
      },
    },
  });
  const rank = (await api.getTodos({})).jobs[0].rank;
  const title = (await api.getTableData({})).rows.find((r) => r.rank === rank)!
    .title;
  const contact = demo.jobs.find((j) => j.job.title === title)!.job
    .pipeline_id as string;
  return {
    api,
    source,
    rank,
    contact,
    requests,
    interference,
    store,
  };
}

test("a real host keeps the selection: changes go to it with the version last read", async () => {
  const { api, rank, contact, requests, store } = await hostSetup();
  await api.toggleSelectionItem({ rank, selected: true });
  expect(requests.at(-1)).toMatchObject({
    expected_version: 0,
    operation: "select",
    contact_ids: [contact],
  });
  expect(await api.getSelectionQueue({})).toEqual({ ranks: [rank], count: 1 });
  // Nothing about the selection is kept in the browser.
  expect([...store.keys()].some((k) => k.includes("selection"))).toBe(false);
  await api.applySelectionOperation({
    operation: "clear_visible",
    visibleRanks: [rank],
  });
  expect(requests.at(-1)?.operation).toBe("clear_visible");
  expect((await api.getSelectionQueue({})).count).toBe(0);
});

test("a stale selection change is reported, not silently overwritten", async () => {
  const { api, rank, interference } = await hostSetup();
  interference.next = true;
  await expect(
    api.toggleSelectionItem({ rank, selected: true }),
  ).rejects.toThrow("选择刚被更新过");
  expect((await api.getSelectionQueue({})).count).toBe(0);
});

test("one-click execution runs on a real host through its execution services", async () => {
  const { api, rank } = await hostSetup();
  await api.recordDecision({
    rank,
    kind: "accept_original",
    greetingText: null,
    note: null,
  });
  await api.toggleSelectionItem({ rank, selected: true });
  const result = await api.executeSelectionDirect({});
  expect(result.error).not.toBe("not_integrated");
  expect(result.queued.map((q) => q.rank)).toEqual([rank]);
  const retry = await api.executeJobDirect({ rank });
  expect(retry.error).not.toBe("not_integrated");
});

test("without a host selection service the selection stays unavailable", async () => {
  const { api } = await hostSetup(false);
  await expect(api.getSelectionQueue({})).rejects.toThrow("服务端选择队列尚未接入");
});

test("the panel offers one-click and retry only where the host provides the services", async () => {
  const { executionAvailability } = await import("../src/muse/availability");
  const { source } = await hostSetup();
  expect(executionAvailability(source, undefined)).toEqual({
    quickExecutionAvailable: true,
    retryAvailable: true,
  });
  const readonly = { ...source, createExecutionBatch: undefined, confirmExecution: undefined };
  expect(executionAvailability(readonly, undefined)).toEqual({
    quickExecutionAvailable: false,
    retryAvailable: false,
  });
  const noSelection = { ...source, getSelection: undefined, saveSelection: undefined };
  expect(executionAvailability(noSelection, undefined)).toEqual({
    quickExecutionAvailable: false,
    retryAvailable: true,
  });
});
