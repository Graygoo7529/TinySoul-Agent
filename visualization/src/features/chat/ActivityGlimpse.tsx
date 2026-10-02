import { useState } from "react";
import { Crossfade } from "../../components/ui/Crossfade";
import { JsonTree } from "../../components/ui/JsonTree";
import { useConnectionStore } from "../../store/connectionStore";
import { useTurnStore } from "../../store/turnStore";
import { actionFamily } from "../trace/registry";
import { asObject, asString } from "../trace/facts";
import { makeTraceNavigation, pushActionDetail } from "../trace/entries";
import { FAMILY_VIEWS } from "../trace/resultViews";
import { ActivityStep as Step } from "./ActivityStep";
import type { ActivityStep } from "./presentation";

/** c479ca0's expanding action inset, using canonical v2 result-family renderers. */
export function ActivityGlimpse({ item, live }: { item: ActivityStep; live: boolean }) {
  const [expanded, setExpanded] = useState(item.autoExpandGist);
  const epoch = useConnectionStore((s) => s.epoch);
  const turnId = useTurnStore((s) => s.turnId);
  const day = useTurnStore((s) => s.day);
  if (item.content.type !== "action_plan" && item.content.type !== "action_result") return <Step item={item} animate={live} />;
  const data = item.content.glimpse;
  // The conversation owns answer/question bodies; the trail keeps their action fact.
  if (data.actionId === "core.ask" || data.actionId === "core.answer") return <Step item={item} animate={live} />;
  const params = asObject(data.params);
  const text = asString(params?.command) ?? asString(params?.script) ?? asString(params?.query) ?? asString(params?.instruction) ?? asString(params?.text);
  const FamilyView = FAMILY_VIEWS[actionFamily(data.actionId)];
  return <Step item={item} animate={live} onToggleGlimpse={() => setExpanded(!expanded)} glimpseExpanded={expanded}
    glimpse={expanded && <div className="grow-in">
      <Crossfade id={`${data.callId}:${data.stage}`} className="mt-1 rounded-lg border border-line/70 bg-bg-sunken/70 px-2.5 py-1.5">
        <div className="max-h-44 overflow-y-auto text-[11px]">
          {data.stage === "plan" ? text !== null
            ? <pre className="line-clamp-5 whitespace-pre-wrap break-words font-mono text-fg-muted">{text}</pre>
            : <JsonTree value={params ?? {}} defaultExpanded={false} />
            : turnId && <FamilyView result={data.payload ?? null} params={params} nav={makeTraceNavigation(epoch, turnId, day)} />}
          {data.result?.preview && <div className="text-danger">{data.result.preview}</div>}
        </div>
        {turnId && <button type="button" className="mt-1 text-[10px] text-accent hover:underline"
          onClick={() => pushActionDetail(epoch, turnId, day, { callId: data.callId, action: data.actionId, ordinal: 0 })}>Details</button>}
      </Crossfade>
    </div>} />;
}
