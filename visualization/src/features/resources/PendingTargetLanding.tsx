/**
 * Home/Memory landing while those pages land (F5-B).
 *
 * The ResourceRouter already resolves and records navigation targets for both
 * owners; until their pages exist, this landing shows exactly which resource
 * was asked for and keeps the copy/quote operations available. It never
 * fakes the page itself.
 */

import type { ReactElement } from "react";
import { Brain, House } from "lucide-react";

import { EmptyState } from "../../components/ui/EmptyState";
import { Button } from "../../components/ui/Button";
import { copyReference, quoteReference } from "./router";
import { useResourceTargets } from "./targetsStore";

export function PendingTargetLanding({
  owner,
}: {
  owner: "home" | "memory";
}): ReactElement {
  const target = useResourceTargets((s) => (owner === "home" ? s.home : s.memory));
  const title = owner === "home" ? "Home" : "Memory";
  const icon = owner === "home" ? <House size={26} /> : <Brain size={26} />;

  if (target === null) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <EmptyState
          icon={icon}
          title={title}
          description="This page is being rebuilt against the v2 contracts."
        />
      </div>
    );
  }

  const reference = target.link;
  const day = "day" in target ? target.day : null;
  const origin =
    owner === "home"
      ? { homeView: (target as { view: "effective" | "actual" }).view }
      : { day: day ?? undefined };

  return (
    <div className="flex h-full items-center justify-center p-6">
      <EmptyState
        icon={icon}
        title={title}
        description={
          <>
            The page is being rebuilt against the v2 contracts. The requested
            resource is ready to reference:
            <span className="mt-2 block break-all rounded-lg border border-line bg-bg-elev px-3 py-2 font-mono text-[12px] text-fg">
              {reference}
            </span>
            {owner === "home" && "view" in target && (
              <span className="mt-1 block text-[11px] text-fg-faint">
                view: {target.view}
              </span>
            )}
            {owner === "memory" && day !== null && (
              <span className="mt-1 block text-[11px] text-fg-faint">
                day: {day}
              </span>
            )}
          </>
        }
        action={
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={() => copyReference(reference)}>
              Copy reference
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => quoteReference(reference, origin)}
            >
              Quote in conversation
            </Button>
          </div>
        }
      />
    </div>
  );
}
