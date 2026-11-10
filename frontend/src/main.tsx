import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { createHttpSource, type ConsoleDataSource } from "./dataSource";
import { createDemoSource } from "./demoHost";
import type { OnboardingState } from "./hostContracts";
import "./app.css";
import { MuseSourcePanel } from "./muse/MusePanel";
import "./muse/theme.css";
import { OnboardingView } from "./onboarding/OnboardingView";
import { createHttpOnboarding } from "./onboarding/source";

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
 * The real entry: who the person is comes first. Without a profile or any
 * confirmed fact the first-use flow is shown, never an empty job board; a read
 * failure is shown as a failure and never falls back to the demo.
 */
function LiveApp() {
  const [onboarding] = useState(createHttpOnboarding);
  const [board] = useState(createHttpSource);
  const [first, setFirst] = useState<OnboardingState | null>(null);
  const [view, setView] = useState<"onboarding" | "board">("onboarding");
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    onboarding
      .getState(controller.signal)
      .then((state) => {
        setFirst(state);
        if (state.stage === "ready") setView("board");
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setError(
            "本人资料状态读取失败。没有显示岗位看板，也没有进入演示；请确认本机服务已启动后刷新。",
          );
      });
    return () => controller.abort();
  }, [onboarding]);
  if (error || !first) return <LoadState title="本人资料" error={error} />;
  if (view === "onboarding")
    return (
      <OnboardingView
        source={onboarding}
        initial={first}
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
            void onboarding
              .getState()
              .then((state) => {
                setFirst(state);
                setView("onboarding");
              })
              .catch(() =>
                setError("本人资料状态读取失败，未显示过期内容；请刷新重试。"),
              )
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
