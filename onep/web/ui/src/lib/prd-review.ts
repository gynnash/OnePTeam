import type { PrdValidation, ProductAssumption } from "../api";

const blockingRisks = new Set(["high", "critical", "高", "严重"]);

export function blockingProductAssumptions(
  assumptions: ProductAssumption[],
): ProductAssumption[] {
  return assumptions.filter(
    (item) =>
      item.status === "rejected" ||
      (item.status === "pending" && blockingRisks.has(item.risk.toLowerCase())),
  );
}

export function canApprovePrd(
  validation: PrdValidation | null,
  assumptions: ProductAssumption[],
): boolean {
  return Boolean(validation?.passed) && blockingProductAssumptions(assumptions).length === 0;
}
