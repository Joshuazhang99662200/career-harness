import type { ReactNode } from "react";
import type { OnboardingResume, OnboardingState } from "../hostContracts";

const EXTRACTION: Record<OnboardingResume["extraction"], string> = {
  imported: "已整理成逐条事实",
  waiting_host: "Agent 正在整理",
  output_ready: "已整理好，等你在对话里核对",
  not_requested: "已读取，尚未整理",
};

function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section
      aria-label={title}
      className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-4"
    >
      <h2 className="mb-2 text-base font-semibold">{title}</h2>
      {children}
    </section>
  );
}

const button =
  "min-h-11 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] px-4 text-sm hover:bg-[var(--accent-soft)] focus-visible:outline-2 focus-visible:outline-[var(--accent)] disabled:opacity-50";

/**
 * First use is a conversation: the agent asks one question at a time and the
 * person confirms each fact there. This page only shows how far it has got.
 */
export function FirstUse({
  state,
  refreshing,
  onRefresh,
  onOpenBoard,
}: {
  state: OnboardingState;
  refreshing: boolean;
  onRefresh: () => void;
  onOpenBoard: () => void;
}) {
  const confirmed = state.facts.filter((f) => f.confirmed).length;
  const waiting = state.facts.length - confirmed;
  const title =
    state.stage === "ready"
      ? "本人资料与就绪情况"
      : state.stage === "collecting"
        ? "本人资料还在整理中"
        : state.stage === "unknown"
          ? "本人资料读取失败"
          : "还没有本人资料";
  return (
    <main className="mx-auto grid max-w-3xl gap-4 px-4 py-6 text-[var(--text)]">
      <header>
        <h1 className="text-2xl font-semibold">{title}</h1>
        {state.source === "unavailable" ? (
          <p role="alert" className="mt-1 text-sm text-[var(--danger)]">
            {state.message ?? "本人资料记录读取失败。"}
            没有当作空资料，也没有进入演示。
          </p>
        ) : (
          <p className="mt-1 text-sm text-[var(--dim)]">
            首次引导在对话里进行：在 Codex 或 Claude Code 里调用求职技能，Agent
            会一次问一个问题，先收集简历或经历，再逐条请你确认。这个页面只显示进度，不能在这里录入或确认。
          </p>
        )}
      </header>

      {state.stage === "not_started" && state.source !== "unavailable" && (
        <Card title="怎么开始">
          <p className="text-sm">
            在对话里说“开始求职”或调用求职技能即可。没有简历也可以，Agent
            会从经历问答开始。
          </p>
        </Card>
      )}

      {(state.stage === "collecting" || state.stage === "ready") && (
        <>
          <Card title="进度">
            <ul className="grid gap-1 text-sm">
              <li>
                简历：
                {state.resumes.length === 0
                  ? "还没有提供（也可以只靠问答）"
                  : state.resumes
                      .map(
                        (r) =>
                          `《${r.source_name}》${EXTRACTION[r.extraction]}`,
                      )
                      .join("；")}
              </li>
              <li>
                已确认事实 {confirmed} 条，待你在对话里确认 {waiting} 条
              </li>
              <li>
                已回答 {state.answered_count} 个问题，跳过 {state.skipped_count}{" "}
                个
              </li>
              {state.open_question && (
                <li>正在等你在对话里回答：{state.open_question.text}</li>
              )}
            </ul>
          </Card>

          {state.facts.length > 0 && (
            <Card title="已记录的事实">
              <ul className="grid gap-2 text-sm">
                {state.facts.map((fact) => (
                  <li key={fact.evidence_id}>
                    <p className="whitespace-pre-wrap">{fact.statement}</p>
                    <p className="text-xs text-[var(--dim)]">
                      {fact.source_type === "resume"
                        ? `简历第 ${fact.resume_page ?? "?"} 页`
                        : fact.source_type === "interview"
                          ? "来自你的回答"
                          : fact.source_type === "user_edit"
                            ? "你改写后的表述"
                            : "来源未注明"}{" "}
                      ·{" "}
                      <span
                        className={fact.confirmed ? "" : "text-[var(--warn)]"}
                      >
                        {fact.confirmed ? "已确认" : "待确认"}
                      </span>
                    </p>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {state.gaps.length > 0 && (
            <Card title="尚缺">
              <ul className="list-disc pl-5 text-sm text-[var(--dim)]">
                {state.gaps.map((gap) => (
                  <li key={gap.gap_id}>{gap.label}</li>
                ))}
              </ul>
            </Card>
          )}

          <Card title="下一步">
            <ul className="grid gap-1 text-sm">
              <li>
                {state.configuration.status === "initialized"
                  ? `求职设置已登记（版本 ${state.configuration.rules_version}），后续沿用。`
                  : state.configuration.status === "not_initialized"
                    ? "求职设置还没登记，Agent 会在对话里逐项问你确认。"
                    : "求职设置是否已登记暂时读不到，按未知处理。"}
              </li>
              <li>是否需要手机等通知提醒，Agent 会先问你，默认不开启。</li>
            </ul>
          </Card>
        </>
      )}

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          className={button}
          onClick={onRefresh}
          disabled={refreshing}
        >
          {refreshing ? "正在读取…" : "刷新进度"}
        </button>
        {/* Fetch results and job progress stay visible whatever the profile stage. */}
        <button type="button" className={button} onClick={onOpenBoard}>
          查看岗位进展
        </button>
      </div>
    </main>
  );
}
