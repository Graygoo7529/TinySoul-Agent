/**
 * The fixed TinySoul model capability vocabulary (`tinysoul.llm.protocol`),
 * shared by the model editor and the task-chain required-capabilities editor.
 */

import type { MessageId } from "../../../i18n/core";

export const MODEL_CAPABILITIES: { value: string; labelId: MessageId }[] = [
  { value: "text_input", labelId: "settings.capability.text_input" },
  { value: "image_input", labelId: "settings.capability.image_input" },
  { value: "image_remote_url", labelId: "settings.capability.image_remote_url" },
  { value: "json_object_output", labelId: "settings.capability.json_object_output" },
  { value: "tool_calling", labelId: "settings.capability.tool_calling" },
  { value: "reasoning_output", labelId: "settings.capability.reasoning_output" },
  { value: "prompt_cache", labelId: "settings.capability.prompt_cache" },
];
