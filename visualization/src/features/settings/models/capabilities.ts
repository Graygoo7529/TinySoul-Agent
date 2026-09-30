/**
 * The fixed TinySoul model capability vocabulary (`tinysoul.llm.protocol`),
 * shared by the model editor and the task-chain required-capabilities editor.
 */

import type { SelectOption } from "./controls";

export const MODEL_CAPABILITIES: SelectOption[] = [
  { value: "text_input", label: "Text input" },
  { value: "image_input", label: "Image input" },
  { value: "image_remote_url", label: "Remote image URLs" },
  { value: "json_object_output", label: "JSON object output" },
  { value: "tool_calling", label: "Tool calling" },
  { value: "reasoning_output", label: "Reasoning output" },
  { value: "prompt_cache", label: "Prompt cache" },
];
