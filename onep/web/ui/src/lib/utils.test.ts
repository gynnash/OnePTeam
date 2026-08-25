import { describe, expect, it } from "vitest";
import {
  projectHue,
  shortTime,
  stageLabel,
  statusLabel,
  summarize,
} from "./utils";

describe("human-facing formatters", () => {
  it("translates durable states and stages", () => {
    expect(statusLabel.cancel_requested).toBe("正在停止");
    expect(stageLabel.understand).toBe("理解目标");
  });

  it("summarizes raw evidence without losing the original object", () => {
    expect(summarize({ detail: "x".repeat(30) }, 20)).toHaveLength(20);
    expect(shortTime("not-a-date")).toBe("not-a-date");
  });

  it("gives project covers a stable hue inside the brand range", () => {
    expect(projectHue("OnePTeam")).toBe(projectHue("OnePTeam"));
    expect(projectHue("OnePTeam")).toBeGreaterThanOrEqual(248);
    expect(projectHue("OnePTeam")).toBeLessThan(300);
  });
});
