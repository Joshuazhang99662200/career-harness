import { useState, type ReactNode } from "react";
import type {
  OnboardingFact,
  OnboardingResume,
  OnboardingState,
} from "../hostContracts";
import type { OnboardingResult, OnboardingSource } from "./source";

const ERRORS: Record<string, string> = {
  STALE_APPROVAL:
    "这条内容在你看到之后已经变化，页面已重新读取，请再核对一次。未保存。",
  POLICY_REJECTION:
    "这条表述较弱，不能直接确认；请先改写成你能确认的说法。未保存。",
  CONTRACT_VALIDATION_ERROR:
    "提交的内容未通过检查（例如不是 PDF、超过 10 MB，或这一步还没准备好）。未保存。",
  RESUME_PARSE_ERROR: "简历文件无法读取（可能已加密或损坏）。未保存。",
  INVALID_PROVIDER_OUTPUT:
    "整理结果和简历原文对不上，未载入。请让宿主重新整理这份简历。",
  MISSING_EVIDENCE: "这条事实已不存在，页面已重新读取。",
  STORAGE_ERROR: "本人资料记录暂时无法写入。未保存。",
  source_unavailable: "本人资料记录暂时无法读写。未保存。",
  local_origin_required: "只能在本机打开的页面里录入资料。未保存。",
  read_only: "当前页面是只读方式打开的，不能录入资料。未保存。",
};

const errorText = (code: string) => ERRORS[code] ?? `未保存（${code}）。`;

const EXTRACTION: Record<OnboardingResume["extraction"], string> = {
  imported: "已载入，请在下方逐条核对。",
  waiting_host:
    "已读取原文，正在等宿主 Agent 整理经历。整理好后点“刷新”即可看到。",
  output_ready: "宿主已整理完成。载入后，每一条都需要你核对确认。",
  not_requested: "已读取原文，尚未请求整理。",
};

function sourceLabel(fact: OnboardingFact, resumes: OnboardingResume[]) {
  if (fact.source_type === "resume") {
    const resume = resumes.find((r) => r.resume_id === fact.resume_id);
    return `来自简历${resume ? `《${resume.source_name}》` : ""}第 ${fact.resume_page ?? "?"} 页`;
  }
  if (fact.source_type === "interview") return "来自你的回答";
  if (fact.source_type === "user_edit") return "你改写后的表述";
  return "来源未注明";
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section
      aria-label={title}
      className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-4"
    >
      <h2 className="mb-3 text-base font-semibold">{title}</h2>
      {children}
    </section>
  );
}

const button =
  "min-h-11 rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] px-4 text-sm hover:bg-[var(--accent-soft)] focus-visible:outline-2 focus-visible:outline-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-50";
const primary =
  "min-h-11 rounded-[var(--radius)] bg-[var(--accent)] px-4 text-sm font-medium text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-50";

function Fact({
  fact,
  resumes,
  disabled,
  run,
  source,
}: {
  fact: OnboardingFact;
  resumes: OnboardingResume[];
  disabled: boolean;
  run: (label: string, call: () => Promise<OnboardingResult>) => void;
  source: OnboardingSource;
}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(fact.statement);
  const page =
    fact.resume_id &&
    resumes
      .find((r) => r.resume_id === fact.resume_id)
      ?.pages.find((p) => p.page_number === fact.resume_page);
  const status = fact.confirmed
    ? "已确认"
    : fact.confirmable
      ? "待你确认"
      : "表述较弱，需先改写";
  return (
    <li className="border-t border-[var(--border)] py-3 first:border-t-0">
      <p className="text-sm whitespace-pre-wrap">{fact.statement}</p>
      {fact.metrics.length > 0 && (
        <p className="text-xs text-[var(--dim)]">
          数字：
          {fact.metrics.map((m) => `${m.name} ${m.value}${m.unit}`).join("；")}
        </p>
      )}
      <p className="mt-1 text-xs text-[var(--dim)]">
        {sourceLabel(fact, resumes)} ·{" "}
        <span className={fact.confirmed ? "" : "text-[var(--warn)]"}>
          {status}
        </span>
      </p>
      {page && (
        <details className="mt-1 text-xs">
          <summary className="cursor-pointer text-[var(--accent)]">
            查看这一页原文
          </summary>
          <pre className="mt-1 max-h-60 overflow-auto whitespace-pre-wrap rounded bg-[var(--bg)] p-2">
            {page.text || "（这一页没有可提取的文字）"}
          </pre>
        </details>
      )}
      {!fact.confirmed && !editing && (
        <div className="mt-2 flex flex-wrap gap-2">
          {fact.confirmable && (
            <button
              type="button"
              className={primary}
              disabled={disabled}
              onClick={() =>
                run("确认", () =>
                  source.confirm(fact.evidence_id, fact.statement_digest),
                )
              }
            >
              属实，确认这条
            </button>
          )}
          <button
            type="button"
            className={button}
            disabled={disabled}
            onClick={() => {
              setText(fact.statement);
              setEditing(true);
            }}
          >
            改写
          </button>
        </div>
      )}
      {editing && (
        <form
          className="mt-2 grid gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            setEditing(false);
            run("改写", () =>
              source.edit(fact.evidence_id, fact.statement_digest, text),
            );
          }}
        >
          <label className="text-xs text-[var(--dim)]">
            改成你能确认的说法（保存后还需要再确认一次）
            <textarea
              className="mt-1 block w-full rounded border border-[var(--border)] bg-[var(--surface)] p-2 text-sm"
              rows={3}
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
          </label>
          <div className="flex gap-2">
            <button
              type="submit"
              className={primary}
              disabled={disabled || !text.trim()}
            >
              保存改写
            </button>
            <button
              type="button"
              className={button}
              onClick={() => setEditing(false)}
            >
              取消
            </button>
          </div>
        </form>
      )}
    </li>
  );
}

export function OnboardingView({
  source,
  initial,
  onOpenBoard,
}: {
  source: OnboardingSource;
  initial: OnboardingState;
  onOpenBoard: () => void;
}) {
  const [state, setState] = useState(initial);
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [answer, setAnswer] = useState("");
  const disabled = busy !== null || !state.writable;

  function run(label: string, call: () => Promise<OnboardingResult>) {
    setBusy(label);
    setNotice("");
    call()
      .then((result) => {
        setState(result.state);
        if (result.error) setNotice(errorText(result.error));
        return result;
      })
      .catch(async (error: unknown) => {
        setNotice(
          `${label}未完成：${error instanceof Error ? error.message : "连接中断"}。下方显示的是重新读取的记录。`,
        );
        try {
          setState(await source.getState());
        } catch {
          setNotice(
            `${label}未完成，也无法重新读取记录；下方是上一次读到的内容，可能已过期。`,
          );
        }
      })
      .finally(() => setBusy(null));
  }

  const refresh = () =>
    run("刷新", async () => ({ state: await source.getState() }));
  const readiness = state.readiness?.readiness;
  const unconfirmed = state.facts.filter((f) => !f.confirmed).length;
  const question = state.open_question;

  return (
    <main
      className="mx-auto grid max-w-3xl gap-4 px-4 py-6 text-[var(--text)]"
      aria-busy={busy !== null}
    >
      <header>
        <h1 className="text-2xl font-semibold">
          {state.stage === "ready" ? "本人资料" : "开始求职前，先整理你的经历"}
        </h1>
        <p className="mt-1 text-sm text-[var(--dim)]">
          这里只记录你提供和确认过的事实。后续写简历和招呼时，只会使用你确认过的内容。
        </p>
      </header>

      {notice && (
        <p
          role="alert"
          className="rounded-[var(--radius)] bg-[var(--warn-soft)] p-3 text-sm"
        >
          {notice}
        </p>
      )}
      {busy && (
        <p role="status" className="text-sm text-[var(--dim)]">
          正在{busy}，完成后显示保存后的记录…
        </p>
      )}

      {state.source === "unavailable" && (
        <Section title="读取失败">
          <p role="alert" className="text-sm text-[var(--danger)]">
            {state.message ?? "本人资料记录读取失败。"}
            未把它当作空资料，也没有进入演示。
          </p>
          <button
            type="button"
            className={`${button} mt-3`}
            onClick={refresh}
            disabled={busy !== null}
          >
            重新读取
          </button>
        </Section>
      )}

      {!state.writable && state.source !== "unavailable" && (
        <div className="rounded-[var(--radius)] border border-[var(--border)] bg-[var(--surface)] p-3 text-sm">
          这个页面目前是只读方式打开的，可以查看，但不能在这里录入资料。需要录入时，请让宿主用允许首次引导的方式重新打开本页。
          <details className="mt-2 text-xs text-[var(--dim)]">
            <summary className="cursor-pointer">排查信息</summary>
            启动参数需包含 <code>--allow-onboarding-writes</code>
            ，数据库需放在私有目录（如 <code>.jobagent/</code>
            ）。当前候选人编号：
            <code>{state.candidate_id}</code>
          </details>
        </div>
      )}

      {state.stage === "not_started" && state.source !== "unavailable" && (
        <Section title="接下来会做什么">
          <ol className="list-decimal space-y-1 pl-5 text-sm">
            <li>提供一份简历（PDF）；没有简历也可以直接从问答开始。</li>
            <li>宿主 Agent 把简历整理成一条条经历，并标出在原文第几页。</li>
            <li>你逐条核对：属实就确认，不准确就改写。</li>
            <li>围绕还缺的信息一次只问一个问题，不知道可以跳过，保持未知。</li>
            <li>看到就绪情况后，再进入找岗位的步骤。</li>
          </ol>
          <button
            type="button"
            className={`${primary} mt-4`}
            disabled={disabled}
            onClick={() => run("开始", () => source.start())}
          >
            开始
          </button>
        </Section>
      )}

      {(state.stage === "collecting" || state.stage === "ready") && (
        <>
          <Section title="简历与材料">
            {state.resumes.length === 0 && (
              <p className="text-sm text-[var(--dim)]">
                还没有上传简历。没有简历也可以，直接从下方“补充信息”开始。
              </p>
            )}
            <ul className="grid gap-3">
              {state.resumes.map((resume) => (
                <li key={resume.resume_id} className="text-sm">
                  <p className="font-medium">
                    {resume.source_name}（{resume.pages.length} 页）
                  </p>
                  <p className="text-[var(--dim)]">
                    {EXTRACTION[resume.extraction]}
                  </p>
                  {resume.warnings.length > 0 && (
                    <p className="text-xs text-[var(--warn)]">
                      有页面没有可提取的文字，整理结果可能不完整。
                    </p>
                  )}
                  <div className="mt-2 flex flex-wrap gap-2">
                    {resume.extraction === "waiting_host" && (
                      <button
                        type="button"
                        className={button}
                        onClick={refresh}
                        disabled={busy !== null}
                      >
                        刷新
                      </button>
                    )}
                    {resume.extraction === "output_ready" &&
                      resume.request_id && (
                        <button
                          type="button"
                          className={primary}
                          disabled={disabled}
                          onClick={() =>
                            run("载入整理结果", () =>
                              source.importExtraction(resume.request_id!),
                            )
                          }
                        >
                          载入整理结果
                        </button>
                      )}
                  </div>
                  <details className="mt-1 text-xs">
                    <summary className="cursor-pointer text-[var(--accent)]">
                      查看读取到的原文
                    </summary>
                    {resume.pages.map((page) => (
                      <pre
                        key={page.page_number}
                        className="mt-1 max-h-60 overflow-auto whitespace-pre-wrap rounded bg-[var(--bg)] p-2"
                      >
                        第 {page.page_number} 页{"\n"}
                        {page.text || "（这一页没有可提取的文字）"}
                      </pre>
                    ))}
                  </details>
                </li>
              ))}
            </ul>
            {state.resumes.some((r) => r.extraction === "imported") ? (
              <p className="mt-3 text-xs text-[var(--dim)]">
                已有简历整理结果。要补充另一份简历，请在对话里交给宿主合并，这里不会覆盖已有资料。
              </p>
            ) : (
              <div className="mt-3 text-sm">
                <label
                  className={`${button} inline-flex items-center ${disabled ? "cursor-not-allowed opacity-50" : "cursor-pointer"} focus-within:outline-2 focus-within:outline-[var(--accent)]`}
                >
                  选择简历 PDF
                  <input
                    type="file"
                    accept="application/pdf,.pdf"
                    className="sr-only"
                    disabled={disabled}
                    onChange={(event) => {
                      const file = event.target.files?.[0];
                      event.target.value = "";
                      if (file)
                        run("上传简历", () => source.uploadResume(file));
                    }}
                  />
                </label>
                <p className="mt-1 text-xs text-[var(--dim)]">
                  不超过 10 MB，只保存在本机私有目录。
                </p>
              </div>
            )}
          </Section>

          {state.experiences.length > 0 && (
            <Section title="整理出的经历">
              <ul className="grid gap-1 text-sm">
                {state.experiences.map((experience) => (
                  <li key={experience.id}>
                    {experience.company} · {experience.title}
                    {(experience.time_range.start ||
                      experience.time_range.end) && (
                      <span className="text-[var(--dim)]">
                        {" "}
                        （{experience.time_range.start ?? "?"} 至{" "}
                        {experience.time_range.end ?? "今"}）
                      </span>
                    )}
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-xs text-[var(--dim)]">
                经历本身由下方的逐条事实支撑，请以逐条核对为准。
              </p>
            </Section>
          )}

          <Section title={`逐条核对（待确认 ${unconfirmed} 条）`}>
            {state.facts.length === 0 ? (
              <p className="text-sm text-[var(--dim)]">
                还没有需要核对的事实。上传简历或回答下方的问题后，会出现在这里。
              </p>
            ) : (
              <ul>
                {state.facts.map((fact) => (
                  <Fact
                    key={`${fact.evidence_id}:${fact.statement_digest}`}
                    fact={fact}
                    resumes={state.resumes}
                    disabled={disabled}
                    run={run}
                    source={source}
                  />
                ))}
              </ul>
            )}
          </Section>

          <Section title="补充信息">
            {question ? (
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  const text = answer.trim();
                  run("保存回答", () =>
                    source.answer(question.question_id, text),
                  );
                  setAnswer("");
                }}
              >
                <label className="block text-sm font-medium">
                  {question.text}
                  <textarea
                    className="mt-2 block w-full rounded border border-[var(--border)] bg-[var(--surface)] p-2 text-sm font-normal"
                    rows={4}
                    value={answer}
                    disabled={disabled}
                    onChange={(e) => setAnswer(e.target.value)}
                  />
                </label>
                <p className="mt-1 text-xs text-[var(--dim)]">
                  回答会先记为待确认的事实，出现在上方由你确认。
                </p>
                <div className="mt-2 flex flex-wrap gap-2">
                  <button
                    type="submit"
                    className={primary}
                    disabled={disabled || !answer.trim()}
                  >
                    保存回答
                  </button>
                  <button
                    type="button"
                    className={button}
                    disabled={disabled}
                    onClick={() => {
                      setAnswer("");
                      run("跳过", () =>
                        source.answer(question.question_id, null),
                      );
                    }}
                  >
                    跳过，保持未知
                  </button>
                </div>
              </form>
            ) : (
              <>
                <p className="text-sm text-[var(--dim)]">
                  {state.gaps.length > 0
                    ? "还有信息没补充。每次只问一个问题。"
                    : "目前没有需要追问的缺口。"}
                </p>
                {state.gaps.length > 0 && (
                  <button
                    type="button"
                    className={`${button} mt-2`}
                    disabled={disabled}
                    onClick={() => run("准备问题", () => source.ask())}
                  >
                    {state.answered_count + state.skipped_count > 0
                      ? "下一个问题"
                      : "开始补充信息"}
                  </button>
                )}
              </>
            )}
            {state.answered_count + state.skipped_count > 0 && (
              <p className="mt-2 text-xs text-[var(--dim)]">
                已回答 {state.answered_count} 个，跳过 {state.skipped_count}{" "}
                个。
              </p>
            )}
          </Section>

          <Section title="就绪情况">
            <ul className="grid gap-1 text-sm">
              <li>已确认事实：{readiness?.confirmed_evidence_count ?? 0} 条</li>
              <li>
                待你确认：{state.readiness?.unconfirmed_evidence_count ?? 0} 条
              </li>
              <li>
                资料完整度：
                {readiness
                  ? `${Math.round(readiness.profile_completeness * 100)}%`
                  : "未知"}
              </li>
            </ul>
            {state.gaps.length > 0 && (
              <>
                <p className="mt-2 text-sm">尚缺：</p>
                <ul className="list-disc pl-5 text-sm text-[var(--dim)]">
                  {state.gaps.map((gap) => (
                    <li key={gap.gap_id}>{gap.label}</li>
                  ))}
                </ul>
              </>
            )}
          </Section>

          <Section title="下一步">
            <ul className="grid gap-2 text-sm">
              <li>
                {state.configuration.status === "initialized"
                  ? `求职设置已登记（版本 ${state.configuration.rules_version}），后续沿用，不会重新询问。`
                  : state.configuration.status === "not_initialized"
                    ? "求职设置还没登记：岗位方向、每日额度等，会由宿主在对话里逐项问你确认；这里不代为设置。"
                    : "求职设置是否已登记暂时读不到，按未知处理。"}
              </li>
              <li>是否需要手机等通知提醒，会先问你；你同意之前不会开启。</li>
            </ul>
            {state.stage === "ready" ? (
              <button
                type="button"
                className={`${primary} mt-3`}
                onClick={onOpenBoard}
              >
                查看岗位进展
              </button>
            ) : (
              <p className="mt-3 text-sm text-[var(--dim)]">
                至少确认一条事实后，才能进入岗位进展。
              </p>
            )}
          </Section>
        </>
      )}
    </main>
  );
}
