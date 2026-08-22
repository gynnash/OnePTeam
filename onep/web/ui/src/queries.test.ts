import { describe, expect, it } from "vitest";
import { isReadActivity } from "./queries";

describe("isReadActivity", () => {
  it("filters read capabilities that would otherwise create an SSE refresh loop", () => {
    expect(
      isReadActivity({
        type: "action.completed",
        payload: { capability_id: "project.detail" },
      }),
    ).toBe(true);
  });

  it("keeps mutating actions in the activity timeline", () => {
    expect(
      isReadActivity({
        type: "action.completed",
        payload: { capability_id: "project.settings.update" },
      }),
    ).toBe(false);
  });
});
