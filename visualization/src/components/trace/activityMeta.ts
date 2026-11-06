/**
 * Icon and color per activity-step type, shared by the live status trail and
 * the trace timeline so the same event reads identically in both surfaces.
 */

import {
  AlertTriangle,
  BookOpen,
  Brain,
  CheckCircle2,
  Compass,
  Flag,
  ListChecks,
  Loader2,
  RotateCcw,
  WandSparkles,
} from "lucide-react";
import type { ActivityStepType } from "../../features/chat/presentation";

export const activityIcons: Record<ActivityStepType, React.ComponentType<{ size?: number; className?: string }>> = {
  background: BookOpen,
  control_failure: AlertTriangle,
  todo: ListChecks,
  milestone: Flag,
  domain_select: Compass,
  skill_mount: WandSparkles,
  thinking: Brain,
  provider_retry: RotateCcw,
  action_plan: Loader2,
  action_result: CheckCircle2,
};

export const activityColors: Record<ActivityStepType, string> = {
  background: "text-info",
  control_failure: "text-warning",
  todo: "text-accent",
  milestone: "text-warning",
  domain_select: "text-accent",
  skill_mount: "text-info",
  thinking: "text-accent",
  provider_retry: "text-warning",
  action_plan: "text-warning",
  action_result: "text-success",
};
