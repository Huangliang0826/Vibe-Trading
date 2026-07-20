import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { expect, it, vi } from "vitest";

vi.mock("@/pages/Analytics", () => ({
  Analytics: () => <div>数据洞察面板</div>,
}));

import { Settings } from "../Settings";

it("shows data insights as a settings tab", () => {
  render(
    <MemoryRouter initialEntries={["/settings?tab=analytics"]}>
      <Routes>
        <Route path="/settings" element={<Settings />} />
      </Routes>
    </MemoryRouter>,
  );

  expect(screen.getByRole("tab", { name: "系统设置" })).toHaveAttribute("aria-selected", "false");
  expect(screen.getByRole("tab", { name: "数据洞察" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByText("数据洞察面板")).toBeInTheDocument();
});
