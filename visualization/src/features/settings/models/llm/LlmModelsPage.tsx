import { useI18n } from "../../../../i18n";
import { ModelSelectionList } from "../ModelPicker";
import {
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  Pencil,
  Trash2,
} from "lucide-react";
import { Badge } from "../../../../components/ui/Badge";
import {
  Button,
} from "../../../../components/ui/Button";
import { objectSourceFor } from "../../draft/fields";
import { useConfigDraftStore } from "../../draft/store";
import { useSettingsUiStore } from "../../uiStore";
import {
  modelReferences,
  llmObjectIdError,
  objectDeletable,
  projectCollection,
  stringField,
  stringListField,
  writableProjectSource,
  type ProjectedObject,
} from "../collectionDrafts";
import {
  DeleteObjectModal,
  ObjectEditorLayout,
  RenameObjectModal,
} from "../ObjectEditor";
import {
  setObjectField,
  stageObjectCreate,
  stageObjectDelete,
  stageObjectRename,
} from "../objectEditing";
import { ModelEditor } from "./ModelEditor";
import { NewModelModal } from "./NewModelModal";

export const ROOT = "llm.models";

export function LlmModelsPage() {
  const { t } = useI18n();
  const state = useConfigDraftStore();
  const objects = useMemo(
    () => projectCollection(state, ROOT),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [state.saved, state.drafts],
  );
  const providers = useMemo(
    () => projectCollection(state, "llm.providers"),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [state.saved, state.drafts],
  );
  const tasks = useMemo(
    () => projectCollection(state, "llm.tasks"),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [state.saved, state.drafts],
  );
  const collection = state.catalog?.collections.find((item) => item.root === ROOT);
  const tasksCollection = state.catalog?.collections.find(
    (item) => item.root === "llm.tasks",
  );
  const tasksCreateSource = tasksCollection?.createSource ?? "";
  const deletePolicy = collection?.deletePolicy ?? "all";
  const createSourceAvailable =
    collection?.allowCreate === true && state.saved?.activity.can_write === true;

  const [selected, setSelected] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [renaming, setRenaming] = useState<ProjectedObject | null>(null);
  const [deleting, setDeleting] = useState<ProjectedObject | null>(null);

  // Consume one-shot focus requests (search hits, apply-error locate, jumps).
  const focusPath = useSettingsUiStore((s) => s.focusPath);
  useEffect(() => {
    if (focusPath !== null && focusPath.startsWith(`${ROOT}.`)) {
      const id = focusPath.slice(ROOT.length + 1).split(".", 1)[0];
      if (id !== undefined && id !== "") {
        setSelected(id);
      }
    }
  }, [focusPath]);
  // Clear a stale selection (deleted model); entering stays list-first.
  useEffect(() => {
    if (selected !== null && !objects.some((item) => item.id === selected)) {
      setSelected(null);
    }
  }, [objects, selected]);

  const current = objects.find((item) => item.id === selected) ?? null;
  const objectSource = (object: ProjectedObject) => {
    const source = objectSourceFor(state.saved, `${ROOT}.${object.id}`, object.ownerSources[0] ?? null);
    return source !== null && writableProjectSource(state, source) ? source : null;
  };
  const writeSource = current === null ? null : objectSource(current);
  const currentDeletable = objectDeletable(current, deletePolicy) && writeSource !== null;
  const families = [...new Set(objects.map((item) => stringField(item.value, "family")).filter(Boolean))].sort();

  const items = objects.map((item) => ({ id: item.id, dirty: item.dirty, isNew: item.isNew }));

  return (
    <>
      <ObjectEditorLayout
        title={t("settings.models")}
        description={
          collection?.description ??
          t("settings.providerModelsWithCapabilitiesAndRequestOptions")
        }
        items={items}
        selected={selected}
        onSelect={setSelected}
        onAdd={() => {
          setCreating(true);
        }}
        addDisabled={!createSourceAvailable}
        addTitle={
          createSourceAvailable
            ? t("settings.newModel")
            : t("settings.modelsReadOnly")
        }
        renderList={(select) => <ModelSelectionList models={objects} value={selected} onSelect={select} />}
        headerBadges={
          current !== null && (
            <>
              {current.isNew && <Badge tone="accent">{t("settings.draftCreated")}</Badge>}
              {!current.isNew && current.dirty && <Badge tone="accent">{t("common.modified")}</Badge>}
              {current.value.collapsed === true && <Badge tone="gray">{t("settings.collapsed")}</Badge>}
            </>
          )
        }
        headerActions={
          current !== null && (
            <>
              <Button
                size="xs"
                variant="outline"
                disabled={!currentDeletable}
                title={
                  currentDeletable
                    ? t("settings.rename")
                    : t("settings.modelRenameReadOnly")
                }
                onClick={() => setRenaming(current)}
              >
                <Pencil size={13} />{t("settings.rename")}</Button>
              <Button
                size="xs"
                variant="danger"
                disabled={!currentDeletable}
                title={
                  currentDeletable
                    ? t("settings.delete")
                    : t("settings.modelDeleteReadOnly")
                }
                onClick={() => setDeleting(current)}
              >
                <Trash2 size={13} />{t("settings.delete")}</Button>
            </>
          )
        }
      >
        {current !== null && (
          <fieldset disabled={writeSource === null}>
            {writeSource === null && <p className="p-3 text-xs text-fg-muted">{t("settings.noWritableProjectSourceHoldsThisModel")}</p>}
            <ModelEditor object={current} providers={providers} writeSource={writeSource} />
          </fieldset>
        )}
      </ObjectEditorLayout>

      <NewModelModal
        open={creating}
        onClose={() => setCreating(false)}
        existing={objects.map((item) => item.id)}
        families={families}
        models={objects}
        providers={providers}
        template={collection?.createTemplate ?? {}}
        catalog={state.catalog}
        onCreate={(id, value, target) => {
          const draft = useConfigDraftStore.getState();
          if (target.create) {
            draft.createSource(target.sourceId, target.includeSourceId);
          }
          stageObjectCreate(ROOT, id, value, target.sourceId);
          setSelected(id);
          setCreating(false);
        }}
      />

      <RenameObjectModal validateId={llmObjectIdError}
        title={t("settings.rename")}
        objectId={renaming?.id ?? ""}
        existing={objects.map((item) => item.id)}
        references={renaming !== null ? modelReferences(tasks, renaming.id) : []}
        referenceNote="Task chains referencing this model — an apply with stale references is rejected:"
        open={renaming !== null}
        onClose={() => setRenaming(null)}
        onRename={(newId, updateReferences) => {
          if (renaming === null) return;
          const references = modelReferences(tasks, renaming.id);
          stageObjectRename(ROOT, renaming, newId, objectSource(renaming));
          if (updateReferences) {
            for (const reference of references) {
              const task = tasks.find((item) => item.id === reference.owner);
              if (task === undefined) continue;
              const models = stringListField(task.value, "models").map((id) =>
                id === renaming.id ? newId : id,
              );
              setObjectField("llm.tasks", task, "models", models, tasksCreateSource);
            }
          }
          setSelected(newId);
          setRenaming(null);
        }}
      />
      <DeleteObjectModal
        title={t("settings.delete")}
        objectId={deleting?.id ?? ""}
        references={deleting !== null ? modelReferences(tasks, deleting.id) : []}
        open={deleting !== null}
        onClose={() => setDeleting(null)}
        onDelete={() => {
          if (deleting !== null) stageObjectDelete(ROOT, deleting);
          setDeleting(null);
        }}
      />
    </>
  );
}
