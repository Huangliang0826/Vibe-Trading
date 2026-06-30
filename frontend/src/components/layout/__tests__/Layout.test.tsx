import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  api: { listSessions: vi.fn().mockResolvedValue([]) },
}));

import { Layout } from "../Layout";

function renderLayout() {
  render(
    <MemoryRouter initialEntries={["/overview"]}>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/overview" element={<div>Overview content</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("Layout mobile navigation", () => {
  it("keeps the sidebar off canvas until the mobile menu opens", async () => {
    renderLayout();

    const sidebar = screen.getByRole("complementary");
    expect(sidebar).toHaveClass("-translate-x-full", "md:translate-x-0");

    await userEvent.click(screen.getByRole("button", { name: "打开导航" }));

    expect(sidebar).toHaveClass("translate-x-0");
    expect(screen.getByRole("button", { name: "关闭导航" })).toBeInTheDocument();
  });
});
