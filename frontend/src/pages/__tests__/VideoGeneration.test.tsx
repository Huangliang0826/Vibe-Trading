import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

const apiMock = vi.hoisted(() => ({
  createVideoGenerationTask: vi.fn(),
  getVideoGenerationTask: vi.fn(),
  downloadGeneratedVideo: vi.fn(),
}));
vi.mock("@/lib/api", async (original) => ({ ...(await original<object>()), api: apiMock }));

import { VideoGeneration } from "../VideoGeneration";

it("rejects temporary signed Ark image URLs before creating a paid task", async () => {
  const user = userEvent.setup();
  render(<VideoGeneration />);

  await user.type(
    screen.getByPlaceholderText("或粘贴图片 HTTPS 地址"),
    "https://ark-acg-cn-beijing.dualstack.cn-beijing.tos.volces.com/original/image.png?X-Tos-Signature=expired",
  );
  await user.click(screen.getByRole("button", { name: "添加" }));

  expect(screen.getByRole("alert")).toHaveTextContent("临时签名地址");
  expect(apiMock.createVideoGenerationTask).not.toHaveBeenCalled();
});
