/**
 * Presentation descriptors for the home domain: Agent Home top-level entries
 * (skills, agent config), progressive resources, and framework prompt mounts.
 */

import type { ActionDescriptor } from "./types";
import { asString, defaultTargetOf } from "./common";

function linkCall(verbPhrase: string) {
  return (params: Record<string, unknown>) => {
    const link = asString(params.link);
    return {
      headline: link ? `${verbPhrase} ${link}` : verbPhrase,
      target: defaultTargetOf("home.top.write", params),
    };
  };
}

export const HOME_ACTIONS: ActionDescriptor[] = [
  {
    action: "home.top.search",
    verb: "Searching home",
    family: "search",
    summarizeCall: (params) => {
      const query = asString(params.query);
      return {
        headline: query ? `检索技能 “${query}”` : "检索技能",
        target: defaultTargetOf("home.top.search", params),
      };
    },
  },
  {
    action: "home.top.write",
    verb: "Writing home",
    family: "generate",
    summarizeCall: linkCall("写入"),
  },
  {
    action: "home.top.patch",
    verb: "Editing home",
    family: "patch",
    summarizeCall: linkCall("编辑"),
  },
  {
    action: "home.top.delete",
    verb: "Deleting home",
    family: "delete",
    summarizeCall: linkCall("删除"),
  },
  {
    action: "home.resource.read",
    verb: "Reading home resource",
    family: "read",
    summarizeCall: linkCall("读取"),
  },
  {
    action: "home.resource.write",
    verb: "Writing home resource",
    family: "generate",
    summarizeCall: linkCall("写入"),
  },
  {
    action: "home.resource.patch",
    verb: "Editing home resource",
    family: "patch",
    summarizeCall: linkCall("编辑"),
  },
  {
    action: "home.resource.delete",
    verb: "Deleting home resource",
    family: "delete",
    summarizeCall: linkCall("删除"),
  },
  {
    action: "home.prompt_mount.write",
    verb: "Writing prompt mount",
    family: "generate",
    summarizeCall: linkCall("写入挂载"),
  },
  {
    action: "home.prompt_mount.patch",
    verb: "Editing prompt mount",
    family: "patch",
    summarizeCall: linkCall("编辑挂载"),
  },
];
