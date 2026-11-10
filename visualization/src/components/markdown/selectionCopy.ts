/**
 * Selection → Markdown copy for rendered `.md-body` content. The renderers
 * emit a bounded element set (GFM + KaTeX), so a small explicit walker maps a
 * selected DOM fragment back to Markdown source — the clipboard gets
 * structured Markdown, not flattened text. Unmapped subtrees degrade to
 * their text content instead of failing the copy.
 */

/** Build the Markdown for the current selection inside `root`. */
export function markdownFromSelection(root: HTMLElement): string | null {
  const selection = window.getSelection();
  if (selection === null || selection.rangeCount === 0) return null;
  const range = selection.getRangeAt(0);
  if (range.collapsed || !root.contains(range.commonAncestorContainer)) return null;
  const fragment = range.cloneContents();
  const holder = document.createElement("div");
  holder.appendChild(fragment);
  const text = childrenToMarkdown(holder).replace(/\n{3,}/g, "\n\n").trim();
  return text === "" ? null : text;
}

function childrenToMarkdown(node: Node): string {
  let out = "";
  for (const child of Array.from(node.childNodes)) out += nodeToMarkdown(child);
  return out;
}

function nodeToMarkdown(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) return node.textContent ?? "";
  if (!(node instanceof HTMLElement)) return "";

  // KaTeX: recover the TeX source from the annotation rehype-katex keeps.
  if (node.classList.contains("katex-display") || node.classList.contains("katex")) {
    const tex = node.querySelector('annotation[encoding="application/x-tex"]')?.textContent;
    if (tex != null) {
      return node.classList.contains("katex-display") ? `\n\n$$${tex}$$\n\n` : `$${tex}$`;
    }
  }

  const inner = childrenToMarkdown(node);
  switch (node.tagName) {
    case "P": return `${inner}\n\n`;
    case "STRONG": case "B": return `**${inner}**`;
    case "EM": case "I": return `*${inner}*`;
    case "DEL": case "S": return `~~${inner}~~`;
    case "H1": case "H2": case "H3": case "H4": case "H5": case "H6": {
      const level = Number(node.tagName[1]);
      return `${"#".repeat(level)} ${inner.trim()}\n\n`;
    }
    case "A": {
      const href = node.getAttribute("href") ?? "";
      return href === "" ? inner : `[${inner}](${href})`;
    }
    case "CODE": return node.closest("pre") === null ? `\`${inner}\`` : inner;
    case "PRE": {
      const code = node.querySelector("code");
      const language = /language-([\w-]+)/.exec(code?.className ?? "")?.[1] ?? "";
      return `\n\n\`\`\`${language}\n${(code ?? node).textContent ?? ""}\n\`\`\`\n\n`;
    }
    case "BLOCKQUOTE": return `${inner.trim().split("\n").map((line) => `> ${line}`).join("\n")}\n\n`;
    case "UL": return `${listItems(node, false)}\n`;
    case "OL": return `${listItems(node, true)}\n`;
    case "TABLE": return `${tableToMarkdown(node)}\n`;
    case "BR": return "\n";
    case "HR": return "\n---\n\n";
    default: return inner;
  }
}

function listItems(list: HTMLElement, ordered: boolean): string {
  return Array.from(list.children)
    .filter((item): item is HTMLElement => item.tagName === "LI")
    .map((item, index) => {
      const marker = ordered ? `${index + 1}.` : "-";
      const body = childrenToMarkdown(item).trim().replace(/\n+/g, " ");
      return `${marker} ${body}`;
    })
    .join("\n");
}

function tableToMarkdown(table: HTMLElement): string {
  const rows = Array.from(table.querySelectorAll("tr")).map((row) =>
    Array.from(row.querySelectorAll("th,td")).map((cell) => childrenToMarkdown(cell).trim()),
  );
  if (rows.length === 0) return "";
  const [head, ...body] = rows;
  const header = head ?? [];
  const divider = header.map(() => "---");
  return [header, divider, ...body]
    .map((row) => `| ${row.join(" | ")} |`)
    .join("\n");
}
