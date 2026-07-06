import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConnectionBanner } from "../ConnectionBanner";


describe("ConnectionBanner", () => {
  it("renders nothing when API and SSE are healthy", () => {
    const { container } = render(
      <ConnectionBanner status="connected" apiStatus="healthy" />,
    );
    expect(container.innerHTML).toBe("");
  });

  it("gives an API failure priority over SSE reconnecting", () => {
    render(
      <ConnectionBanner status="reconnecting" retryAttempt={3} apiStatus="unavailable" />,
    );
    expect(screen.getByText(/后端连接失败/)).toBeInTheDocument();
    expect(screen.queryByText(/重连中/)).not.toBeInTheDocument();
  });

  it("identifies an HTML proxy misconfiguration", () => {
    render(<ConnectionBanner status="connected" apiStatus="misconfigured" />);
    expect(screen.getByText(/API 代理配置异常/)).toBeInTheDocument();
    expect(screen.getByText(/scripts\/dev doctor/)).toBeInTheDocument();
  });

  it("runs an immediate retry", async () => {
    const retry = vi.fn();
    render(
      <ConnectionBanner status="connected" apiStatus="unavailable" onRetryApi={retry} />,
    );

    await userEvent.setup().click(screen.getByRole("button", { name: "重试后端连接" }));

    expect(retry).toHaveBeenCalledTimes(1);
  });

  it("keeps the SSE reconnecting message when the API is healthy", () => {
    render(
      <ConnectionBanner status="reconnecting" retryAttempt={3} apiStatus="healthy" />,
    );
    expect(screen.getByText(/连接断开，重连中/)).toBeInTheDocument();
    expect(screen.getByText(/第 3 次/)).toBeInTheDocument();
  });
});
