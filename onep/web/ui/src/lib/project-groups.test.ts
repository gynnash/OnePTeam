import { describe, expect, it } from "vitest";
import type { Project } from "../api";
import { groupProjects, normalizeProjectName } from "./project-groups";

function project(id: string, name: string, updatedAt: string): Project {
  return {
    id,
    name,
    mode: "build",
    status: "pending",
    current_stage: "",
    workspace_path: "",
    requirement: `prompt-${id}`,
    created_at: updatedAt,
    updated_at: updatedAt,
  };
}

describe("project groups", () => {
  it("normalizes whitespace, width, and case", () => {
    expect(normalizeProjectName("  TechRadar ")).toBe("techradar");
    expect(normalizeProjectName("ＯｎｅＰ  Team")).toBe("onep team");
  });

  it("groups equal names and sorts prompts by latest update", () => {
    const groups = groupProjects([
      project("older", "TechRadar", "2026-01-01T00:00:00Z"),
      project("other", "Release Notes", "2026-02-01T00:00:00Z"),
      project("latest", " techradar ", "2026-03-01T00:00:00Z"),
    ]);

    expect(groups.map((group) => group.key)).toEqual([
      "techradar",
      "release notes",
    ]);
    expect(groups[0].projects.map((item) => item.id)).toEqual([
      "latest",
      "older",
    ]);
    expect(groups[0].latest.id).toBe("latest");
  });
});
