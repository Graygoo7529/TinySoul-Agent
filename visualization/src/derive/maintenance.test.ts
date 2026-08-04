import { describe, expect, it } from "vitest";
import { maintenanceTaskCount } from "./maintenance";

describe("maintenanceTaskCount", () => {
  it("counts Home once and each pending Memory day", () => {
    expect(
      maintenanceTaskCount({
        availability: {
          checked_day: "2026-08-04",
          home_pending: true,
          home_change_count: 2,
          home_skill_memory_count: 1,
          memory_pending: true,
          memory_days: ["2026-08-01", "2026-08-02", "2026-08-03"],
        },
      }),
    ).toBe(4);
  });

  it("returns zero when no Maintenance work is available", () => {
    expect(maintenanceTaskCount(null)).toBe(0);
  });
});
