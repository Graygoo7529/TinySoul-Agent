/** Application view models that are not Endpoint wire contracts. */

export interface TopLinkEntry {
  link: string;
  content: string;
  source: string;
  owner: string;
  evictable: boolean;
}

export type AppTab = "chat" | "workspace" | "monitor" | "settings";
