import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { createHttpSource, type ConsoleDataSource } from "./dataSource";
import { createDemoSource } from "./demoHost";
import type { OnboardingState } from "./hostContracts";
import "./app.css";
import { MuseSourcePanel } from "./muse/MusePanel";
import "./muse/theme.css";
import { FirstUse } from "./onboarding/FirstUse";
import { readOnboarding } from "./onboarding/state";

function LoadState({ title, error }: { title: string; error?: string }) {
  return (
    <main className="load-state">
      <h1>{title}</h1>
      {error ? (
        <p role="alert">{error}</p>
      ) : (
        <p role="status">正在读取本地记录…</p>
      )}
    </main>
  );
}

function DemoApp() {
  const [source, setSource] = useState<ConsoleDataSource | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    void Promise.all([import("./demo"), import("./demo-definitions.json")])
      .then(async ([{ demo }, definitions]) => {
        const key = "ja-console.synthetic.v1.CAND_DEMO";
        const next = await createDemoSource({
          snapshot: demo,
          definitions: definitions.default,
          storage: {
            load: () => localStorage.getItem(key),
            save: (value) => localStorage.setItem(key, value),
          },
        });
        if (active) setSource(next);
      })
      .catch(() => {
        if (active)
          setError(
            "合成存储无法读取，请在排查时核对；未自动重置或接入真实数据。",
          );
      });
    return () => {
      active = false;
    };
  }, []);
  if (error || !source) return <LoadState title="岗位进展" error={error} />;
  return <MuseSourcePanel source={source} />;
}

/**
 * The real entry. First use is a conversation with the agent; until the person
 * has confirmed a fact, the page shows that progress instead of an empty job
 * board. A read failure is shown as a failure and never falls back to the demo.
 */
function LiveApp() {
  const [board] = useState(createHttpSource);
  const [first, setFirst] = useState<OnboardingState | null>(null);
  const [view, setView] = useState<"profile" | "board">("profile");
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const load = (signal?: AbortSignal) => {
    setRefreshing(true);
    return readOnboarding(signal)
      .then((state) => {
        setFirst(state);
        setError("");
        return state;
      })
      .catch(() => {
        if (!signal?.aborted)
          setError(
            "本人资料状态读取失败。没有显示岗位看板，也没有进入演示；请确认本机服务已启动后刷新。",
          );
        return null;
      })
      .finally(() => setRefreshing(false));
  };
  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal).then((state) => {
      if (state?.stage === "ready") setView("board");
    });
    return () => controller.abort();
  }, []);
  if (error || !first) return <LoadState title="本人资料" error={error} />;
  if (view === "profile")
    return (
      <FirstUse
        state={first}
        refreshing={refreshing}
        onRefresh={() => void load()}
        onOpenBoard={() => setView("board")}
      />
    );
  return (
    <>
      <nav className="flex justify-end bg-[var(--surface)] px-4 py-1">
        <button
          type="button"
          className="min-h-11 text-sm text-[var(--accent)]"
          onClick={() =>
            void load().then((state) => state && setView("profile"))
          }
        >
          本人资料与就绪情况
        </button>
      </nav>
      <MuseSourcePanel source={board} />
    </>
  );
}

function App() {
  return new URLSearchParams(location.search).get("demo") === "1" ? (
    <DemoApp />
  ) : (
    <LiveApp />
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
