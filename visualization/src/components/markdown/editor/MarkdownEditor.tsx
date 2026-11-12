import { useEffect, useMemo } from "react";
import { EditorContent, useEditor } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { Markdown } from "@tiptap/markdown";

/**
 * WYSIWYG Markdown editor for workspace documents (TipTap 3 + the markdown
 * extension). The document stays plain Markdown end to end — editing renders
 * typography in place, `onChange` receives serialized Markdown, and the
 * caller's save path never sees a rich-text format. `value` is authoritative:
 * external changes (undo, load, source-mode round trip) replace the editor
 * content; typing flows out through `onChange`.
 */
export function MarkdownEditor({
  value,
  onChange,
  onSaveShortcut,
  ariaLabel,
}: {
  value: string;
  onChange: (markdown: string) => void;
  /** Ctrl/Cmd+S inside the editor triggers the same save as the toolbar. */
  onSaveShortcut: () => void;
  ariaLabel: string;
}) {
  const extensions = useMemo(() => [StarterKit, Markdown], []);
  const editor = useEditor({
    extensions,
    content: value,
    contentType: "markdown",
    onUpdate: ({ editor: current }) => {
      onChange(current.getMarkdown());
    },
    editorProps: {
      attributes: {
        class: "md-editor md-body",
        role: "textbox",
        "aria-label": ariaLabel,
        "aria-multiline": "true",
      },
      handleKeyDown: (_view, event) => {
        if ((event.ctrlKey || event.metaKey) && event.key === "s") {
          event.preventDefault();
          onSaveShortcut();
          return true;
        }
        return false;
      },
    },
  });

  // External value changes (load / undo / source-mode edits) replace content.
  useEffect(() => {
    if (editor === null) return;
    if (editor.getMarkdown() !== value) {
      editor.commands.setContent(value, { contentType: "markdown" });
    }
  }, [editor, value]);

  useEffect(() => () => editor?.destroy(), [editor]);

  return <EditorContent editor={editor} className="md-editor-host" />;
}
