import { useEffect, useState, type ReactNode } from "react";
import { Plus } from "lucide-react";

import { Button } from "../../components/ui/Button";
import { Modal } from "../../components/ui/Modal";
import type { ConfigCollectionDescriptor } from "../../types";
import { validObjectId } from "./model";

const inputClass =
  "focus-ring h-8 w-full rounded-md border border-line bg-bg-elev px-2.5 font-mono text-[12px] outline-none focus:border-accent";

export function CreateObjectModal({
  collection,
  existing,
  open,
  onClose,
  onCreate,
  children,
  valid = true,
}: {
  collection: ConfigCollectionDescriptor;
  existing: string[];
  open: boolean;
  onClose: () => void;
  onCreate: (id: string) => Promise<void>;
  children?: ReactNode;
  valid?: boolean;
}) {
  const [id, setId] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    if (!open) setId("");
  }, [open]);
  if (!open) return null;
  const available = validObjectId(id) && !existing.includes(id);
  return (
    <Modal title={`New ${collection.title}`} onClose={onClose}>
      <div className="space-y-4">
        <label className="block">
          <span className="mb-1.5 block text-[11px] font-medium text-fg-muted">
            {collection.identity.title}
          </span>
          <input
            autoFocus
            aria-label={collection.identity.title}
            value={id}
            onChange={(event) => setId(event.target.value)}
            className={inputClass}
          />
          <span className="mt-1 block text-[10px] text-fg-faint">{collection.identity.description}</span>
        </label>
        {children}
        <div className="flex justify-end gap-2 border-t border-line pt-3">
          <Button size="xs" variant="ghost" onClick={onClose}>Cancel</Button>
          <Button
            size="xs"
            variant="primary"
            loading={saving}
            disabled={!available || !valid}
            onClick={() => {
              setSaving(true);
              void onCreate(id).finally(() => setSaving(false));
            }}
          >
            <Plus size={13} /> Create
          </Button>
        </div>
      </div>
    </Modal>
  );
}
