/**
 * Workspace page modals (plan §10/P06): path entry (new file/folder, move),
 * tag replacement, append and find-and-replace. Each modal is a thin form —
 * the mutation itself lives in the page controller and its result toast.
 */

import { useState, type ReactElement } from "react";

import type { WorkspaceTag } from "../../api/v2/types";
import { Button } from "../../components/ui/Button";
import { Modal } from "../../components/ui/Modal";

/** Single-path form (new file, new folder, move target). */
export function PathInputModal({
  title,
  label,
  initial = "",
  placeholder,
  submitLabel,
  busy,
  onSubmit,
  onClose,
}: {
  title: string;
  label: string;
  initial?: string;
  placeholder?: string;
  submitLabel: string;
  busy: boolean;
  onSubmit: (path: string) => void;
  onClose: () => void;
}): ReactElement {
  const [value, setValue] = useState(initial);
  return (
    <Modal title={title} onClose={onClose} width="max-w-md">
      <form
        className="space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (value.trim() !== "") onSubmit(value.trim());
        }}
      >
        <label className="block space-y-1">
          <span className="text-[12px] text-fg-muted">{label}</span>
          <input
            // eslint-disable-next-line jsx-a11y/no-autofocus -- modal form focus
            autoFocus
            value={value}
            onChange={(event) => setValue(event.target.value)}
            placeholder={placeholder}
            className="h-8 w-full rounded-lg border border-line bg-bg px-3 font-mono text-[12.5px] outline-none focus:border-accent"
          />
        </label>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="submit"
            variant="primary"
            loading={busy}
            disabled={value.trim() === ""}
          >
            {submitLabel}
          </Button>
        </div>
      </form>
    </Modal>
  );
}

const KNOWN_TAGS: { tag: WorkspaceTag; label: string }[] = [
  { tag: "pinned", label: "pinned" },
  { tag: "tmp", label: "tmp" },
  { tag: "library", label: "library" },
];

/** Replace the tag set; tags outside the known three are preserved. */
export function TagsModal({
  tags,
  busy,
  onSubmit,
  onClose,
}: {
  tags: WorkspaceTag[];
  busy: boolean;
  onSubmit: (tags: WorkspaceTag[]) => void;
  onClose: () => void;
}): ReactElement {
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set(tags));
  const preserved = tags.filter(
    (tag) => !KNOWN_TAGS.some((known) => known.tag === tag),
  );
  const toggle = (tag: string, on: boolean) => {
    setSelected((current) => {
      const next = new Set(current);
      if (on) next.add(tag);
      else next.delete(tag);
      return next;
    });
  };
  return (
    <Modal title="Tags" onClose={onClose} width="max-w-sm">
      <div className="space-y-3">
        <div className="space-y-1.5">
          {KNOWN_TAGS.map(({ tag, label }) => (
            <label
              key={tag}
              className="flex cursor-pointer items-center gap-2 text-[13px] text-fg"
            >
              <input
                type="checkbox"
                checked={selected.has(tag)}
                onChange={(event) => toggle(tag, event.target.checked)}
                className="accent-accent"
              />
              {label}
            </label>
          ))}
        </div>
        {preserved.length > 0 && (
          <div className="text-[11px] text-fg-faint">
            Kept as-is: {preserved.join(", ")}
          </div>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            loading={busy}
            onClick={() =>
              onSubmit([
                ...KNOWN_TAGS.map((known) => known.tag).filter((tag) =>
                  selected.has(tag),
                ),
                ...preserved,
              ])
            }
          >
            Save tags
          </Button>
        </div>
      </div>
    </Modal>
  );
}

/** Append explicit text to a text resource. */
export function AppendModal({
  busy,
  onSubmit,
  onClose,
}: {
  busy: boolean;
  onSubmit: (text: string) => void;
  onClose: () => void;
}): ReactElement {
  const [text, setText] = useState("");
  return (
    <Modal title="Append text" onClose={onClose}>
      <div className="space-y-3">
        <textarea
          // eslint-disable-next-line jsx-a11y/no-autofocus -- modal form focus
          autoFocus
          value={text}
          onChange={(event) => setText(event.target.value)}
          rows={6}
          placeholder="Text appended to the end of the file…"
          className="w-full resize-y rounded-lg border border-line bg-bg px-3 py-2 font-mono text-[12.5px] leading-5 outline-none focus:border-accent"
        />
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            loading={busy}
            disabled={text === ""}
            onClick={() => onSubmit(text)}
          >
            Append
          </Button>
        </div>
      </div>
    </Modal>
  );
}

/** One find-and-replace pair (POST /edit; the backend verifies uniqueness). */
export function ReplaceModal({
  busy,
  onSubmit,
  onClose,
}: {
  busy: boolean;
  onSubmit: (oldText: string, newText: string) => void;
  onClose: () => void;
}): ReactElement {
  const [oldText, setOldText] = useState("");
  const [newText, setNewText] = useState("");
  return (
    <Modal title="Find and replace" onClose={onClose}>
      <div className="space-y-3">
        <label className="block space-y-1">
          <span className="text-[12px] text-fg-muted">
            Find (must match exactly once)
          </span>
          <textarea
            // eslint-disable-next-line jsx-a11y/no-autofocus -- modal form focus
            autoFocus
            value={oldText}
            onChange={(event) => setOldText(event.target.value)}
            rows={3}
            className="w-full resize-y rounded-lg border border-line bg-bg px-3 py-2 font-mono text-[12.5px] leading-5 outline-none focus:border-accent"
          />
        </label>
        <label className="block space-y-1">
          <span className="text-[12px] text-fg-muted">Replace with</span>
          <textarea
            value={newText}
            onChange={(event) => setNewText(event.target.value)}
            rows={3}
            className="w-full resize-y rounded-lg border border-line bg-bg px-3 py-2 font-mono text-[12.5px] leading-5 outline-none focus:border-accent"
          />
        </label>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            loading={busy}
            disabled={oldText === ""}
            onClick={() => onSubmit(oldText, newText)}
          >
            Replace
          </Button>
        </div>
      </div>
    </Modal>
  );
}
