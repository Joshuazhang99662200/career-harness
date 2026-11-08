// Helpers shared by the previous default template (?template=current).
// Taken unchanged from the retired zip reference copy (MuseApp.tsx) when it was removed.

import type { api, ApiResponse } from "./contracts";

type JobMaterials = ApiResponse<typeof api, "getJobMaterials">;

type TableRow = ApiResponse<typeof api, "getTableData">["rows"][number];

const MATCH_DECISION_CN: Record<string, string> = {
  strong_match: "经历与要求比较接近",
  possible_match: "有对得上的经历",
  weak_match: "对得上的地方不多",
  not_a_match: "与要求差距较大",
};
const HARD_FILTER_CN: Record<string, string> = {
  PASS: "基本要求符合",
  REVIEW: "基本要求有一项待确认",
  REJECT: "基本要求不符合",
};

export function plainText(text: string): string {
  let out = text;
  out = out.replace(
    /匹配分=(\d+(?:\.\d+)?)，决定=(strong_match|possible_match|weak_match|not_a_match)，硬筛=(PASS|REVIEW|REJECT)/g,
    (_m, score: string, dec: string, hf: string) =>
      `要点匹配 ${Math.round(parseFloat(score) * 100)} 分，${MATCH_DECISION_CN[dec] ?? dec}，${HARD_FILTER_CN[hf] ?? hf}`,
  );
  out = out.replace(/；?JD要点\+宿主工作记录撞公共算法（权重\/阈值原样）/g, "");
  if (out.includes("卡片决定=accept")) {
    out = out.replace("卡片决定=accept", "已记录文案选择：接受");
  }
  if (out.includes("卡片决定=reject")) {
    out = out.replace("卡片决定=reject", "已记录文案选择：不接受");
  }
  out = out.replace(
    /招呼稿版本=[^；。]+；稿件全文见队列，不在此重复全文/g,
    "招呼语已写好",
  );
  out = out.replace(/；回读见队列\s*send_readback/g, "；招呼语已发送");
  out = out.replace(/回读见队列\s*send_readback/g, "招呼语已发送");
  out = out.replace(/稿件全文见队列，不在此重复全文/g, "招呼语已写好");
  out = out.replace(/招呼稿版本=[^\s；。]+/g, "招呼语已写好");
  out = out.replace(/见队列\s*send_readback/g, "招呼语已发送");
  out = out.replace(/全文见队列/g, "全文见招呼语");
  out = out.replace(/见队列/g, "见招呼语");
  return out;
}

type JobFilter = "all" | "active" | "todo" | "waiting" | "contacted" | "ended";

export function rowMatchesFilter(
  r: TableRow,
  filter: JobFilter,
  todoRanks: ReadonlySet<number>,
): boolean {
  switch (filter) {
    case "all":
      return true;
    case "active":
      return r.state !== "declined" && r.state !== "closed";
    case "todo":
      return todoRanks.has(r.rank);
    case "waiting":
      return r.waiting;
    case "contacted":
      return r.contacted;
    case "ended":
      return r.state === "declined" || r.state === "closed";
  }
}
type SortMode = "match" | "intake";
const SORT_STORAGE_KEY = "panel-sort-mode";

export function loadSortMode(): SortMode {
  try {
    return window.localStorage.getItem(SORT_STORAGE_KEY) === "intake"
      ? "intake"
      : "match";
  } catch {
    return "match";
  }
}

export function saveSortMode(mode: SortMode) {
  try {
    window.localStorage.setItem(SORT_STORAGE_KEY, mode);
  } catch {}
}
export function sortRows(rows: TableRow[], mode: SortMode): TableRow[] {
  const ended = (r: TableRow) => r.state === "declined" || r.state === "closed";
  const intakeTs = (r: TableRow) =>
    r.intakeAt ? Date.parse(r.intakeAt) : null;
  return [...rows].sort((a, b) => {
    const ea = ended(a) ? 1 : 0;
    const eb = ended(b) ? 1 : 0;
    if (ea !== eb) return ea - eb;
    if (mode === "match") {
      const sa = a.matchScore;
      const sb = b.matchScore;
      if (sa == null && sb != null) return 1;
      if (sa != null && sb == null) return -1;
      if (sa != null && sb != null && sa !== sb) return sb - sa;
      const ta = intakeTs(a);
      const tb = intakeTs(b);
      if (ta == null && tb != null) return 1;
      if (ta != null && tb == null) return -1;
      if (ta != null && tb != null && ta !== tb) return tb - ta;
      return a.rank - b.rank;
    }
    const ta = intakeTs(a);
    const tb = intakeTs(b);
    if (ta == null && tb != null) return 1;
    if (ta != null && tb == null) return -1;
    if (ta != null && tb != null && ta !== tb) return tb - ta;
    return a.rank - b.rank;
  });
}

export function fmtRunTime(iso: unknown): string {
  if (typeof iso !== "string") return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function displayMaterialTitle(title: string): string {
  let t = title.replace(/（详情页原样匿名显示）/g, "");
  t = t.replace(/（CV-\d+-[^）]*）/g, "");
  if (/某/.test(t)) {
    t = t.replace(/（[^（）]*·/g, "（【猎头岗位】 ·");
  }
  return t;
}

type MaterialItem = JobMaterials["sentGreetings"][number];

export function MaterialList({
  items,
  emptyText,
  fullTextLabel,
}: {
  items: MaterialItem[];
  emptyText: string;
  fullTextLabel?: string;
}) {
  if (items.length === 0) {
    return <p className="mt-1 text-sm text-[var(--dim)]">{emptyText}</p>;
  }
  return (
    <div className="mt-2 space-y-2">
      {items.map((it) => (
        <details
          key={it.id}
          className="rounded-[var(--radius)] border border-[var(--border)] p-3"
          open={items.length === 1}
        >
          <summary className="cursor-pointer text-sm font-medium">
            {displayMaterialTitle(it.title)}
            {it.occurredAt ? (
              <span className="ml-2 text-xs font-normal text-[var(--dim)]">
                {it.occurredAt}
              </span>
            ) : null}
          </summary>
          {fullTextLabel && (
            <p className="mt-2 text-xs font-medium text-[var(--accent)]">
              {fullTextLabel}
            </p>
          )}
          <p className="mt-1 whitespace-pre-wrap text-sm leading-relaxed">
            {it.body}
          </p>
          {it.source && (
            <p className="mt-2 text-xs text-[var(--dim)]">
              数据来源：{it.source}
            </p>
          )}
        </details>
      ))}
    </div>
  );
}
