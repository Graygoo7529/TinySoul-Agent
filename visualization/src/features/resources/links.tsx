/**
 * Markdown link and image renderers (plan §21.2).
 *
 * Every Markdown instance routes its links through the ResourceRouter with
 * the instance origin: resource protocols (workspace:/home:/memory:/
 * session:/turn:trace…) and relative references become router navigation,
 * http(s) opens externally, fragment-only hrefs stay in-page anchors, and
 * anything else keeps the default anchor. Hover/focus reveals the copy and
 * quote operations so plain reading stays clean.
 *
 * Images dispatch on the actual read capability: workspace images load
 * through the authenticated blob client, http(s) images load normally, and
 * Home/Memory references (no blob route) render as a reference hint instead
 * of a broken embed.
 */

import {
  useEffect,
  useState,
  type AnchorHTMLAttributes,
  type ReactElement,
  type ReactNode,
} from "react";
import {
  Check,
  Copy,
  ExternalLink,
  FileQuestion,
  ImageOff,
  Loader2,
  MessageSquareQuote,
} from "lucide-react";

import { useConnectionStore } from "../../store/connectionStore";
import { useMarkdownOrigin } from "../../components/markdown/origin";
import { IconButton } from "../../components/ui/Button";
import { useWorkspaceBlobUrl } from "./blobUrl";
import {
  classifyReference,
  splitFragment,
  type ResourceOrigin,
} from "./reference";
import { copyReference, openExternal, openReference, quoteReference } from "./router";

// ---------------------------------------------------------------------------
// Shared operations
// ---------------------------------------------------------------------------

/**
 * Copy + quote operations for one reference (jump is the link click). The
 * actions stay zero-width while hidden — reserving their layout space would
 * leave a wide gap after every inline reference — and expand on hover/focus.
 */
export function ReferenceActions({
  reference,
  origin,
}: {
  reference: string;
  origin: ResourceOrigin;
}): ReactElement {
  return (
    <span className="inline-flex max-w-0 translate-y-px items-center gap-0.5 overflow-hidden align-baseline opacity-0 transition-[max-width,opacity,margin] group-hover/ref:ml-1 group-hover/ref:max-w-10 group-hover/ref:opacity-100 focus-within:ml-1 focus-within:max-w-10 focus-within:opacity-100">
      <MiniAction label="Copy reference" onClick={() => copyReference(reference)}>
        <Copy size={11} />
      </MiniAction>
      <MiniAction
        label="Quote in conversation"
        onClick={() => quoteReference(reference, origin)}
      >
        <MessageSquareQuote size={11} />
      </MiniAction>
    </span>
  );
}

function MiniAction({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: ReactElement;
}): ReactElement {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      onClick={(event) => {
        event.preventDefault();
        event.stopPropagation();
        onClick();
      }}
      className="inline-flex h-4 w-4 items-center justify-center rounded text-fg-faint transition-colors hover:bg-hover hover:text-fg"
    >
      {children}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Anchor renderer
// ---------------------------------------------------------------------------

type AnchorProps = AnchorHTMLAttributes<HTMLAnchorElement>;

/**
 * The `a` renderer. The href has already passed the Markdown URL transform,
 * which keeps only routable references and default-safe URLs.
 */
export function MarkdownAnchor({ href, children, ...rest }: AnchorProps) {
  const origin = useMarkdownOrigin();
  const epoch = useConnectionStore((s) => s.epoch);

  if (href === undefined || href === "") {
    // The transform stripped an unsafe URL — show the text, never a dead link.
    return <span>{children}</span>;
  }
  if (href.startsWith("#")) {
    // In-page anchor (GFM footnotes); the router is not involved.
    return (
      <a href={href} {...rest}>
        {children}
      </a>
    );
  }
  const kind = classifyReference(href);
  if (kind === "external") {
    return (
      <span className="group/ref inline">
        <a
          href={href}
          onClick={(event) => {
            event.preventDefault();
            openExternal(href);
          }}
          title={href}
          {...rest}
        >
          {children}
          <ExternalLink size={10} className="ml-0.5 inline -translate-y-0.5" />
        </a>
        <ReferenceActions reference={href} origin={origin} />
      </span>
    );
  }
  if (kind === "other") {
    // Unknown protocol (mailto:, …): the transform already vetted it.
    return (
      <a href={href} {...rest}>
        {children}
      </a>
    );
  }
  return (
    <span className="group/ref inline">
      <a
        href={href}
        onClick={(event) => {
          event.preventDefault();
          void openReference(epoch, href, origin);
        }}
        title={href}
        {...rest}
      >
        {children}
      </a>
      <ReferenceActions reference={href} origin={origin} />
    </span>
  );
}

// ---------------------------------------------------------------------------
// Inline code renderer
// ---------------------------------------------------------------------------

/**
 * Inline `code` (block code is handled by the `pre` renderer). A strict
 * protocol-bearing reference gets a link control; any other code text stays
 * plain — arbitrary colon text is never linkified.
 */
export function MarkdownInlineCode({
  children,
  className,
  insidePre,
}: {
  children?: ReactNode;
  /** The fence language class (block code); forwarded to the plain element. */
  className?: string;
  insidePre: boolean;
}) {
  const origin = useMarkdownOrigin();
  const epoch = useConnectionStore((s) => s.epoch);
  const text = typeof children === "string" ? children : null;
  const routable =
    !insidePre &&
    text !== null &&
    (() => {
      const kind = classifyReference(text.trim());
      return kind !== "other" && kind !== "relative";
    })();
  if (!routable || text === null) {
    return <code className={className}>{children}</code>;
  }
  const reference = text.trim();
  return (
    <span className="group/ref inline">
      <code
        role="link"
        tabIndex={0}
        title={`Open ${reference}`}
        onClick={() => void openReference(epoch, reference, origin)}
        onKeyDown={(event) => {
          if (event.key === "Enter") void openReference(epoch, reference, origin);
        }}
        className="cursor-pointer underline decoration-dotted underline-offset-2"
      >
        {children}
      </code>
      <ReferenceActions reference={reference} origin={origin} />
    </span>
  );
}

// ---------------------------------------------------------------------------
// Image renderer
// ---------------------------------------------------------------------------

interface ImgProps {
  src?: string;
  alt?: string;
}

type ImageResolution =
  | { kind: "external"; url: string }
  | { kind: "workspace"; ref: string; day: string | null }
  | { kind: "reference"; reference: string }
  | { kind: "invalid"; reason: string };

/** Decide how an image source can be read, resolving via API-18 if needed. */
async function resolveImageSource(
  src: string,
  origin: ResourceOrigin,
): Promise<ImageResolution> {
  const kind = classifyReference(src);
  if (kind === "external") return { kind: "external", url: src };
  if (kind === "workspace") {
    const { resource } = splitFragment(src);
    return { kind: "workspace", ref: resource, day: origin.day ?? null };
  }
  if (kind === "home" || kind === "memory" || kind === "memory-dynamic") {
    // Home/Memory expose no blob route; keep the reference visible.
    return { kind: "reference", reference: src };
  }
  if (kind === "relative") {
    if (!origin.ref) {
      return {
        kind: "invalid",
        reason: "A relative image needs the resource it was read from.",
      };
    }
    const clients = useConnectionStore.getState().clients;
    if (clients === null) {
      return { kind: "invalid", reason: "Not connected to a backend." };
    }
    try {
      const resolved = await clients.resources.resolve({
        ref: src,
        origin_ref: origin.ref,
        day: origin.day,
        turn_id: origin.turnId,
        view: origin.homeView,
      });
      const link =
        typeof resolved.locator.ref === "string" ? resolved.locator.ref : null;
      if (link !== null && link.startsWith("workspace:")) {
        const { resource } = splitFragment(link);
        const day =
          typeof resolved.locator.day === "string" && resolved.locator.day !== ""
            ? resolved.locator.day
            : null;
        return { kind: "workspace", ref: resource, day };
      }
      return { kind: "reference", reference: link ?? src };
    } catch (error) {
      return {
        kind: "invalid",
        reason: error instanceof Error ? error.message : String(error),
      };
    }
  }
  return { kind: "invalid", reason: "This image reference is not readable." };
}

/** The `img` renderer: media by capability, never a guessed URL. */
export function MarkdownImage({ src, alt }: ImgProps) {
  const origin = useMarkdownOrigin();
  const epoch = useConnectionStore((s) => s.epoch);
  const [resolution, setResolution] = useState<ImageResolution | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  useEffect(() => {
    setResolution(null);
    setFailed(null);
    if (src === undefined || src === "") {
      setFailed("The image reference is empty.");
      return;
    }
    let cancelled = false;
    void resolveImageSource(src, origin).then((value) => {
      if (!cancelled) setResolution(value);
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [epoch, src, origin.ref, origin.day, origin.turnId, origin.homeView]);

  if (failed !== null) {
    return <ImageHint alt={alt} detail={failed} />;
  }
  if (resolution === null) {
    return (
      <span className="my-2 inline-flex items-center gap-2 rounded-lg border border-line bg-bg-elev px-3 py-2 text-[12px] text-fg-faint">
        <Loader2 size={13} className="animate-spin-slow" />
        Loading image…
      </span>
    );
  }
  switch (resolution.kind) {
    case "external":
      return (
        // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
        <img
          src={resolution.url}
          alt={alt ?? ""}
          onError={() => setFailed("The image could not be loaded.")}
        />
      );
    case "workspace":
      return <WorkspaceImage resourceRef={resolution.ref} day={resolution.day} alt={alt} />;
    case "reference":
      return (
        <ReferenceImageHint epoch={epoch} reference={resolution.reference} alt={alt} origin={origin} />
      );
    case "invalid":
      return <ImageHint alt={alt} detail={resolution.reason} />;
  }
}

/** An embedded workspace image through the authenticated blob client. */
function WorkspaceImage({
  resourceRef,
  day,
  alt,
}: {
  resourceRef: string;
  day: string | null;
  alt?: string;
}) {
  const blob = useWorkspaceBlobUrl(resourceRef, day);
  if (blob.error !== null) {
    return <ImageHint alt={alt} detail={blob.error} reference={resourceRef} />;
  }
  if (blob.url === null) {
    return (
      <span className="my-2 inline-flex items-center gap-2 rounded-lg border border-line bg-bg-elev px-3 py-2 text-[12px] text-fg-faint">
        <Loader2 size={13} className="animate-spin-slow" />
        Loading image…
      </span>
    );
  }
  return <img src={blob.url} alt={alt ?? ""} />;
}

/**
 * A resource without a blob route (Home/Memory, or an unresolved owner):
 * shown as a reference with an open affordance, never a fake embed.
 */
function ReferenceImageHint({
  epoch,
  reference,
  alt,
  origin,
}: {
  epoch: number;
  reference: string;
  alt?: string;
  origin: ResourceOrigin;
}) {
  return (
    <span className="my-2 flex items-center gap-2 rounded-lg border border-line bg-bg-elev px-3 py-2 text-[12px] text-fg-muted">
      <ImageOff size={13} className="shrink-0 text-fg-faint" />
      <span className="min-w-0 flex-1 truncate" title={reference}>
        {alt || reference}
      </span>
      <span className="shrink-0 text-fg-faint">not embeddable</span>
      <IconButton
        label="Open resource"
        className="h-6 w-6"
        onClick={() => void openReference(epoch, reference, origin)}
      >
        <ExternalLink size={12} />
      </IconButton>
      <CopyMini reference={reference} />
    </span>
  );
}

/** A failed/unreadable image keeps alt text and reason visible. */
function ImageHint({
  alt,
  detail,
  reference,
}: {
  alt?: string;
  detail: string;
  reference?: string;
}) {
  return (
    <span className="my-2 flex items-center gap-2 rounded-lg border border-warning/30 bg-warning-soft px-3 py-2 text-[12px] text-warning">
      <FileQuestion size={13} className="shrink-0" />
      <span className="min-w-0 flex-1 truncate" title={reference ?? alt}>
        {alt || reference || "Image"}
      </span>
      <span className="shrink-0">{detail}</span>
    </span>
  );
}

function CopyMini({ reference }: { reference: string }) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 1500);
    return () => window.clearTimeout(timer);
  }, [copied]);
  return (
    <IconButton
      label={copied ? "Copied" : "Copy reference"}
      className="h-6 w-6"
      onClick={() => {
        copyReference(reference);
        setCopied(true);
      }}
    >
      {copied ? <Check size={12} className="text-success" /> : <Copy size={12} />}
    </IconButton>
  );
}
