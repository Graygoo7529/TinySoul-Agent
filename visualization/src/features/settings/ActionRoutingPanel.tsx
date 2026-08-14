import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";

import type { TinySoulClient } from "../../api/tinysoul";
import { Badge } from "../../components/ui/Badge";
import { Button, IconButton } from "../../components/ui/Button";
import { Collapsible } from "../../components/ui/Collapsible";
import type {
  ActionCatalog,
  ConfigCatalog,
  ConfigStatus,
  JsonValue,
} from "../../types";
import { useAppStore } from "../../store/appStore";
import { useConfigStore } from "../../store/configStore";
import { ConfigFieldGroups } from "./ConfigFieldGroups";
import { configObjects, surfaceFields, type ConfigSettingField } from "./model";

interface ActionRoute extends Record<string, JsonValue> {
  action_id: string;
  task_profile: string;
}

const selectClass =
  "focus-ring h-8 rounded-md border border-line bg-bg-elev px-2.5 text-[12px] outline-none focus:border-accent disabled:opacity-50";

export function ActionRoutingPanel({
  client,
  status,
  catalog,
  actions,
}: {
  client: TinySoulClient;
  status: ConfigStatus;
  catalog: ConfigCatalog;
  actions: ActionCatalog;
}) {
  const fields = surfaceFields(status, catalog, "action_routing");
  const defaultField = fields.find((field) => field.path.endsWith(".default_task_profile"));
  const overridesField = fields.find((field) => field.path.endsWith(".overrides"));
  const timeoutField = fields.find((field) => field.path.endsWith(".timeout_seconds"));
  const advancedFields = [defaultField, timeoutField].filter(
    (field): field is ConfigSettingField => Boolean(field),
  );
  const chains = configObjects(status, catalog, "llm.tasks").map((item) => item.id);
  const routes = parseRoutes(overridesField?.storedValue);
  const eligible = actions.actions.filter(
    (action) =>
      action.backend_kind === "llm_action" &&
      !routes.some((route) => route.action_id === action.id),
  );
  const [actionId, setActionId] = useState(eligible[0]?.id ?? "");
  const [profile, setProfile] = useState(chains[0] ?? "");
  const patch = useConfigStore((state) => state.patch);
  const savingPath = useConfigStore((state) => state.savingPath);
  const pushToast = useAppStore((state) => state.pushToast);
  const canWrite = status.activity.can_write && !savingPath;
  const selectedAction = eligible.some((item) => item.id === actionId) ? actionId : eligible[0]?.id ?? "";
  const selectedProfile = chains.includes(profile) ? profile : chains[0] ?? "";

  const commit = async (field: ConfigSettingField, value: JsonValue, message = "Action routing active") => {
    try {
      const result = await patch(client, {
        source_id: field.sourceId,
        path: field.path,
        op: "set",
        value,
      });
      pushToast("success", `${message} · ${shortId(result.generation_id)}`);
    } catch (error) {
      pushToast("error", error instanceof Error ? error.message : String(error));
    }
  };

  return (
    <div>
      <section className="border-b border-line">
        <div className="flex items-center justify-between bg-bg-sunken/40 px-5 py-2.5">
          <div>
            <div className="text-[12px] font-semibold text-fg-muted">
              {overridesField?.descriptor.title ?? "Action overrides"}
            </div>
            <div className="mt-0.5 text-[10px] text-fg-faint">
              {overridesField?.descriptor.description}
            </div>
          </div>
          <Badge>{routes.length}</Badge>
        </div>
        <div className="divide-y divide-line">
          {routes.map((route) => {
            const action = actions.actions.find((item) => item.id === route.action_id);
            return (
              <div key={route.action_id} className="grid gap-3 px-5 py-3 md:grid-cols-[minmax(220px,1fr)_minmax(200px,320px)_32px] md:items-center">
                <div className="min-w-0">
                  <div className="truncate font-mono text-[12px] font-medium text-fg">{route.action_id}</div>
                  <div className="mt-0.5 truncate text-[10px] text-fg-faint">
                    {action?.domain ?? "Unavailable"} · {action?.backend_kind ?? "llm_action"}
                  </div>
                  {action?.description && <p className="mt-1 line-clamp-2 text-[10px] text-fg-muted">{action.description}</p>}
                </div>
                <select
                  aria-label={`Task chain for ${route.action_id}`}
                  value={route.task_profile}
                  disabled={!canWrite || !overridesField}
                  onChange={(event) => {
                    if (!overridesField) return;
                    void commit(
                      overridesField,
                      routes.map((item) =>
                        item.action_id === route.action_id
                          ? { ...item, task_profile: event.target.value }
                          : item,
                      ),
                    );
                  }}
                  className={`${selectClass} w-full`}
                >
                  {chains.map((chain) => <option key={chain}>{chain}</option>)}
                </select>
                <IconButton
                  label="Remove Action override"
                  disabled={!canWrite || !overridesField}
                  onClick={() => {
                    if (overridesField) {
                      void commit(
                        overridesField,
                        routes.filter((item) => item.action_id !== route.action_id),
                        "Action override removed",
                      );
                    }
                  }}
                  className="hover:text-danger"
                >
                  <Trash2 size={14} />
                </IconButton>
              </div>
            );
          })}
        </div>
        {eligible.length > 0 && overridesField && (
          <div className="grid gap-2 border-t border-line bg-bg-sunken/20 px-5 py-3 md:grid-cols-[minmax(220px,1fr)_minmax(200px,320px)_auto]">
            <select
              aria-label="LLM-backed Action"
              value={selectedAction}
              disabled={!canWrite}
              onChange={(event) => setActionId(event.target.value)}
              className={`${selectClass} min-w-0`}
            >
              {eligible.map((action) => <option key={action.id} value={action.id}>{action.id}</option>)}
            </select>
            <select
              aria-label="Task chain"
              value={selectedProfile}
              disabled={!canWrite}
              onChange={(event) => setProfile(event.target.value)}
              className={`${selectClass} min-w-0`}
            >
              {chains.map((chain) => <option key={chain}>{chain}</option>)}
            </select>
            <Button
              size="xs"
              variant="outline"
              disabled={!canWrite || !selectedAction || !selectedProfile}
              onClick={() =>
                void commit(
                  overridesField,
                  [...routes, { action_id: selectedAction, task_profile: selectedProfile }],
                  "Action override added",
                )
              }
            >
              <Plus size={13} /> Add override
            </Button>
          </div>
        )}
      </section>
      {advancedFields.length > 0 && (
        <div className="p-4">
          <Collapsible title="Advanced" meta={<Badge>{advancedFields.length}</Badge>}>
            <ConfigFieldGroups
              fields={advancedFields}
              status={status}
              catalog={catalog}
              canWrite={canWrite}
              savingPath={savingPath}
              onCommit={commit}
            />
          </Collapsible>
        </div>
      )}
    </div>
  );
}

function parseRoutes(value: JsonValue | undefined): ActionRoute[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (!item || Array.isArray(item) || typeof item !== "object") return [];
    return typeof item.action_id === "string" && typeof item.task_profile === "string"
      ? [{ action_id: item.action_id, task_profile: item.task_profile }]
      : [];
  });
}

function shortId(value: string): string {
  return value.length > 12 ? value.slice(0, 12) : value;
}
