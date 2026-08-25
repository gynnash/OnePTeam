import { describe, expect, it } from "vitest";
import type { ProductAssumption } from "../api";
import { blockingProductAssumptions, canApprovePrd } from "./prd-review";

function assumption(
  status: ProductAssumption["status"],
  risk: string,
): ProductAssumption {
  return {
    id: `${status}-${risk}`,
    project_id: "project-1",
    prd_version: 1,
    statement: "待确认产品假设",
    source: "discovery_policy",
    impact: "影响首版范围",
    risk,
    status,
    resolution: "",
    revision: 1,
  };
}

describe("PRD approval gate", () => {
  it("blocks rejected and pending high-risk assumptions", () => {
    const values = [
      assumption("accepted", "critical"),
      assumption("pending", "medium"),
      assumption("pending", "high"),
      assumption("rejected", "low"),
    ];

    expect(blockingProductAssumptions(values).map((item) => item.id)).toEqual([
      "pending-high",
      "rejected-low",
    ]);
  });

  it("requires a passed independent validation", () => {
    expect(canApprovePrd(null, [])).toBe(false);
    expect(
      canApprovePrd(
        {
          id: "validation-1", project_id: "project-1", prd_version: 1,
          passed: false, blockers: ["缺少范围"], warnings: [], issues: [],
          follow_up_questions: [],
        },
        [],
      ),
    ).toBe(false);
    expect(
      canApprovePrd(
        {
          id: "validation-2", project_id: "project-1", prd_version: 1,
          passed: true, blockers: [], warnings: [], issues: [],
          follow_up_questions: [],
        },
        [assumption("accepted", "high")],
      ),
    ).toBe(true);
  });
});
