import type { JsonValue, PresetChange } from "../../../api/v2/types";
import { isPlainRecord } from "../draft/model";
import { useConfigDraftStore } from "../draft/store";
import { translatedField } from "../i18n";
import { budgetSummary, type PresetDefinitionView } from "./presetsModel";

function valueText(value: JsonValue): string {
  if (value === null) return "默认值";
  if (Array.isArray(value)) return value.length ? value.map(valueText).join(" → ") : "空列表";
  if (typeof value === "object") return Object.entries(value).map(([key, item]) => `${key}: ${valueText(item)}`).join("；");
  return String(value);
}

function FieldName({ path }: { path: string }) {
  const catalog = useConfigDraftStore((state) => state.catalog);
  const field = translatedField(catalog, path);
  return <span title={path}>{field?.title ?? path}</span>;
}

export function PresetChanges({ changes }: { changes: PresetChange[] | undefined }) {
  if (changes === undefined) return <p className="text-[12px] text-fg-muted">暂时无法比较方案，请查看配置问题。</p>;
  if (changes.length === 0) return <p className="text-[12px] text-fg-muted">方案声明项与当前配置一致。</p>;
  return <div className="overflow-x-auto"><table className="w-full text-left text-[12px]">
    <thead><tr className="border-b border-line text-fg-muted"><th className="p-2">配置项</th><th className="p-2">当前值</th><th className="p-2">方案值</th></tr></thead>
    <tbody>{changes.map((change) => <tr key={JSON.stringify(change.path)} className="border-b border-line/60 align-top">
      <td className="break-all p-2"><FieldName path={change.path.join(".")} /><div className="text-[10px] text-fg-faint">{change.path.join(" / ")}</div></td>
      <td className="break-words p-2 font-mono text-fg-muted">{change.before === null ? "未设置" : valueText(change.before)}</td>
      <td className="break-words p-2 font-mono">{change.before === null && change.after !== null && <span className="mr-1 text-success">新增</span>}{valueText(change.after)}</td>
    </tr>)}</tbody>
  </table></div>;
}

function ValueRow({ path, value, label }: { path: string; value: JsonValue; label?: string }) {
  return <div className="flex flex-wrap justify-between gap-x-4 gap-y-1 py-1 text-[12px]">
    <span className="break-all text-fg-muted">{label ?? <FieldName path={path} />}</span>
    <span className="break-all font-mono">{valueText(value)}</span>
  </div>;
}

/** Actual declarations, shared by the plans page and the chat quick entry. */
export function PresetContent({ definition }: { definition: PresetDefinitionView }) {
  const tasks = definition.values["llm.tasks"];
  const bindings = definition.values["action.models.bindings"];
  const budgets = budgetSummary(definition);
  return <div className="space-y-4">
    <section><div className="mb-1 text-[12px] font-semibold">任务链</div>
      {isPlainRecord(tasks) && Object.entries(tasks).map(([id, task]) => isPlainRecord(task) && <div key={id} className="mb-2 rounded border border-line p-2">
        <ValueRow path={`llm.tasks.${id}.models`} label={id} value={task.models ?? null} />
        <details className="text-[11px] text-fg-muted"><summary className="cursor-pointer">调用参数</summary>
          {Object.entries(task).filter(([key]) => key !== "models").map(([key, value]) => <ValueRow key={key} path={`llm.tasks.${id}.${key}`} value={value} />)}
          <p className="mt-1 text-fg-faint">未设置的参数使用默认值。</p>
        </details>
      </div>)}
    </section>
    <section><div className="mb-1 text-[12px] font-semibold">路由</div>
      {["loop.cycle.phase1_task_profile", "loop.cycle.phase2_task_profile"].filter((path) => path in definition.values).map((path) =>
        <ValueRow key={path} path={path} value={definition.values[path]} />)}
      {Array.isArray(bindings) && bindings.map((binding, index) => isPlainRecord(binding) && <div key={String(binding.consumer ?? index)} className="my-2 rounded border border-line p-2">
        <div className="break-all font-mono text-[11px]">{String(binding.consumer)}</div>
        <ValueRow path="implementation" label="实现" value={binding.implementation ?? null} />
        <ValueRow path="target" label="目标" value={binding.target ?? null} />
        {isPlainRecord(binding.options) && Object.keys(binding.options).length > 0 && <ValueRow path="options" label="参数" value={binding.options} />}
      </div>)}
      {Object.entries(definition.retrieval).filter(([, fields]) => "query.channels" in fields).map(([consumer, fields]) =>
        <ValueRow key={consumer} path={`action.retrieval.${consumer}.query.channels`} label={`${consumer} · 检索通道`} value={fields["query.channels"]} />)}
    </section>
    <section><div className="mb-1 text-[12px] font-semibold">预算</div>
      {definition.includeBudgets ? budgets.map((row) => <ValueRow key={row.path} path={row.path} value={row.value} />)
        : <p className="text-[12px] text-fg-muted">本方案不修改预算。</p>}
    </section>
  </div>;
}
