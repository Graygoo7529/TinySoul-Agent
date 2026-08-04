import type { MaintenanceStatus } from "../types";

export function maintenanceTaskCount(
  status: MaintenanceStatus | null | undefined,
): number {
  if (!status) return 0;
  return (
    (status.availability.home_pending ? 1 : 0) +
    status.availability.memory_days.length
  );
}
