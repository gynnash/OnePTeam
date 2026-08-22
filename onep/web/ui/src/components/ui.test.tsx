import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Badge, JsonInspector, LoadFailure, Modal } from "./ui";

describe("design-system primitives", () => {
  it("renders translated status rather than raw status alone", () => {
    render(<Badge value="running" />);
    expect(screen.getByText("运行中")).toBeInTheDocument();
  });

  it("progressively discloses raw data", async () => {
    render(<JsonInspector value={{ command: "pytest -q" }} />);
    expect(screen.queryByText(/pytest -q/)).not.toBeVisible();
    await userEvent.click(screen.getByText("查看原始数据"));
    expect(screen.getByText(/pytest -q/)).toBeVisible();
  });

  it("renders modal content through the Radix portal", () => {
    render(
      <Modal open onOpenChange={() => undefined} title="确认操作">
        <p>不可逆说明</p>
      </Modal>,
    );
    expect(screen.getByRole("dialog")).toHaveTextContent("确认操作");
    expect(screen.getByText("不可逆说明")).toBeInTheDocument();
  });

  it("keeps request failures distinct from empty states", async () => {
    const retry = vi.fn();
    render(<LoadFailure title="无法读取任务" onRetry={retry} />);

    expect(screen.getByRole("alert")).toHaveTextContent("无法读取任务");
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(retry).toHaveBeenCalledOnce();
  });
});
