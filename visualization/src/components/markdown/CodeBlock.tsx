import { useMemo, type ReactElement } from "react";
import { useAppStore } from "../../store/appStore";
import type {
  CodeBlockFallbackProps,
  CodeBlockRegistration,
  MarkdownOrigin,
} from "./codeBlockRegistry";

/**
 * The default fence presentation — identical to what ReactMarkdown renders
 * for an unregistered fence, so the registry never changes the look of
 * ordinary code.
 */
export function PlainCodeBlock({
  source,
  language,
}: CodeBlockFallbackProps): ReactElement {
  return (
    <pre>
      <code className={language ? `language-${language}` : undefined}>
        {source}
      </code>
    </pre>
  );
}

/**
 * Dispatches one complete fence to its registration. A fence that is still
 * the open tail of a streaming document renders as plain source — no diagram
 * compile and no interactive card is started on partial input. A complete
 * fence whose `parse` fails renders the entry's fallback (default: plain
 * code); only a successfully parsed, complete fence mounts the rich
 * renderer (which itself waits for the viewport before heavy work).
 */
export function RegisteredCodeBlock({
  registration,
  language,
  source,
  streaming,
  origin,
}: {
  registration: CodeBlockRegistration;
  language: string;
  source: string;
  streaming: boolean;
  origin: MarkdownOrigin;
}): ReactElement {
  const theme = useAppStore((s) => s.theme);
  const parsed = useMemo(() => {
    if (registration.parse === undefined) return source;
    try {
      return registration.parse(source);
    } catch {
      return null;
    }
  }, [registration, source]);

  if (streaming) {
    return <PlainCodeBlock source={source} language={language} />;
  }
  if (parsed === null) {
    const Fallback = registration.fallback ?? PlainCodeBlock;
    return <Fallback source={source} language={language} />;
  }
  const Renderer = registration.render;
  return (
    <Renderer
      parsed={parsed}
      source={source}
      language={language}
      theme={theme}
      origin={origin}
    />
  );
}
