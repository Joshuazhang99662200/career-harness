import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { createHttpSource, type ConsoleDataSource } from "./dataSource";
import { createDemoSource } from "./demoHost";
import "./app.css";
import { MuseSourcePanel } from "./muse/MusePanel";

/** Shown before the board: loading, an error, or "nothing here yet" with one action. */
function LoadState({
  title,
  error,
  status = "正在读取本地记录…",
  onRefresh,
}: {
  title: string;
  error?: string;
  status?: string;
  onRefresh?: () => void;
}) {
  return (
    <main className="min-h-screen bg-[var(--bg)] px-4 py-10 text-[var(--text)]">
      <div className="mx-auto max-w-3xl">
        <h1 className="text-2xl font-semibold">{title}</h1>
        {error ? (
          <p role="alert" className="mt-2 text-sm text-[var(--danger)]">
            {error}
          </p>
        ) : (
          <p role="status" className="mt-2 text-sm text-[var(--dim)]">
            {status}
          </p>
        )}
        {onRefresh && (
          <button
            type="button"
            onClick={onRefresh}
            className="mt-4 min-h-11 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] px-4 text-sm hover:bg-[var(--accent-soft)] focus-visible:outline-2 focus-visible:outline-[var(--accent)]"
          >
            刷新
          </button>
        )}
      </div>
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
 * The real entry shows job progress only. Profile and fact work happen in the
 * conversation. Until a job or run exists the page says so in one line; a read
 * failure goes to the board, which diagnoses it and never falls back to the demo.
 */
function LiveApp() {
  const [board] = useState(createHttpSource);
  const [view, setView] = useState<"loading" | "empty" | "board">("loading");
  const load = () => {
    setView("loading");
    board
      .getSnapshot()
      .then((snapshot) =>
        setView(
          snapshot.jobs.length || snapshot.runs.length ? "board" : "empty",
        ),
      )
      .catch(() => setView("board"));
  };
  useEffect(load, [board]);
  if (view === "loading") return <LoadState title="岗位进展" />;
  if (view === "empty")
    return (
      <LoadState title="岗位进展" status="还没有岗位进来。" onRefresh={load} />
    );
  return <MuseSourcePanel source={board} />;
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
