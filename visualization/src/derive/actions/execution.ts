/**
 * Presentation descriptors for the execution domain: immediate shell
 * commands, supervised script runs and their lifecycle (wait/stop/apply/
 * discard/read_candidate), plus LLM-authored script maintenance.
 */

import { truncate } from "../activitySemantics";
import type { ActionDescriptor } from "./types";
import { asNumber, asString, defaultTargetOf } from "./common";

function commandCall(shell: string) {
  return (params: Record<string, unknown>) => {
    const command = asString(params.command);
    return {
      headline: command ? `执行 ${truncate(command.replace(/\s+/g, " "), 60)}` : "执行命令",
      target: defaultTargetOf("execution.run_cmd", params),
      chips: [shell],
    };
  };
}

function executionIdChip(params: Record<string, unknown>): string[] | undefined {
  const id = asString(params.execution_id);
  return id ? [id] : undefined;
}

export const EXECUTION_ACTIONS: ActionDescriptor[] = [
  {
    action: "execution.run_cmd",
    verb: "Running",
    family: "command",
    summarizeCall: commandCall("cmd"),
  },
  {
    action: "execution.run_bash_command",
    verb: "Running",
    family: "command",
    summarizeCall: commandCall("bash"),
  },
  {
    action: "execution.run_powershell",
    verb: "Running",
    family: "command",
    summarizeCall: commandCall("powershell"),
  },
  {
    action: "execution.run_python_script",
    verb: "Running script",
    family: "process",
    summarizeCall: (params) => {
      const link = asString(params.source_link);
      return {
        headline: link ? `运行脚本 ${link}` : "运行脚本",
        target: defaultTargetOf("execution.run_python_script", params),
        chips: ["python"],
      };
    },
  },
  {
    action: "execution.run_bash_script",
    verb: "Running script",
    family: "process",
    summarizeCall: (params) => {
      const link = asString(params.source_link);
      return {
        headline: link ? `运行脚本 ${link}` : "运行脚本",
        target: defaultTargetOf("execution.run_bash_script", params),
        chips: ["bash"],
      };
    },
  },
  {
    action: "execution.create_script",
    verb: "Creating script",
    family: "generate",
    summarizeCall: (params) => {
      const link = asString(params.target_link);
      return {
        headline: link ? `生成脚本 ${link}` : "生成脚本",
        target: defaultTargetOf("execution.create_script", params),
      };
    },
  },
  {
    action: "execution.patch_script",
    verb: "Patching script",
    family: "patch",
    summarizeCall: (params) => {
      const link = asString(params.target_link);
      return {
        headline: link ? `编辑脚本 ${link}` : "编辑脚本",
        target: defaultTargetOf("execution.patch_script", params),
      };
    },
  },
  {
    action: "execution.rewrite_script",
    verb: "Rewriting script",
    family: "generate",
    summarizeCall: (params) => {
      const link = asString(params.target_link);
      return {
        headline: link ? `重写脚本 ${link}` : "重写脚本",
        target: defaultTargetOf("execution.rewrite_script", params),
      };
    },
  },
  {
    action: "execution.promote_script",
    verb: "Promoting script",
    family: "generate",
    summarizeCall: (params) => {
      const target = asString(params.target_link);
      const source = asString(params.source_link);
      return {
        headline: target ? `收录脚本 ${target}` : "收录脚本",
        target: defaultTargetOf("execution.promote_script", params),
        chips: source ? [source] : undefined,
      };
    },
  },
  {
    action: "execution.read_candidate",
    verb: "Reading candidate",
    family: "process",
    summarizeCall: (params) => {
      const path = asString(params.path);
      return {
        headline: path ? `查看候选 ${path}` : "查看候选",
        target: path ? { file: path } : undefined,
        chips: executionIdChip(params),
      };
    },
  },
  {
    action: "execution.apply",
    verb: "Applying execution",
    family: "process",
    summarizeCall: (params) => ({
      headline: "应用执行结果",
      target: asString(params.execution_id)
        ? { subject: asString(params.execution_id) }
        : undefined,
      chips: executionIdChip(params),
    }),
  },
  {
    action: "execution.wait",
    verb: "Waiting on process",
    family: "process",
    summarizeCall: (params) => {
      const seconds = asNumber(params.wait_seconds);
      return {
        headline: "等待进程",
        target: asString(params.execution_id)
          ? { subject: asString(params.execution_id) }
          : undefined,
        chips: seconds !== undefined ? [`${seconds}s`] : executionIdChip(params),
      };
    },
  },
  {
    action: "execution.stop",
    verb: "Stopping process",
    family: "process",
    summarizeCall: (params) => ({
      headline: "停止进程",
      target: asString(params.execution_id)
        ? { subject: asString(params.execution_id) }
        : undefined,
      chips: executionIdChip(params),
    }),
  },
  {
    action: "execution.discard",
    verb: "Discarding execution",
    family: "process",
    summarizeCall: (params) => ({
      headline: "丢弃执行",
      target: asString(params.execution_id)
        ? { subject: asString(params.execution_id) }
        : undefined,
      chips: executionIdChip(params),
    }),
  },
];
