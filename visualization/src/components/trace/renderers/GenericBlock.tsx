/**
 * Fallback renderer: the raw JSON tree, so every payload stays inspectable
 * even when no family renderer claims it.
 */

import { JsonTree } from "../../ui/JsonTree";

export function GenericBlock({ value }: { value: unknown }) {
  return <JsonTree value={value} defaultExpanded={false} />;
}
