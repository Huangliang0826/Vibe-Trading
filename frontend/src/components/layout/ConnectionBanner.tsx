import { WifiOff, RefreshCw } from "lucide-react";
import type { SSEStatus } from "@/hooks/useSSE";
import type { ApiHealthStatus } from "@/hooks/useApiHealth";

interface Props {
  status: SSEStatus;
  retryAttempt?: number;
  apiStatus?: ApiHealthStatus;
  onRetryApi?: () => void;
}

export function ConnectionBanner({
  status,
  retryAttempt,
  apiStatus = "healthy",
  onRetryApi,
}: Props) {
  if (apiStatus === "unavailable" || apiStatus === "misconfigured") {
    const message = apiStatus === "misconfigured"
      ? "API 代理配置异常，请运行 scripts/dev doctor 检查服务。"
      : "后端连接失败，请运行 scripts/dev doctor 检查服务。";
    return (
      <div className="flex items-center gap-2 border-b border-destructive/30 bg-destructive/10 px-4 py-2 text-xs text-destructive">
        <WifiOff className="h-3.5 w-3.5 shrink-0" />
        <span>{message}</span>
        <button
          type="button"
          aria-label="重试后端连接"
          className="ml-auto inline-flex items-center gap-1 text-xs font-medium hover:underline"
          onClick={onRetryApi}
        >
          <RefreshCw className="h-3.5 w-3.5" />
          重试
        </button>
      </div>
    );
  }

  if (status === "connected" || status === "disconnected") return null;

  return (
    <div className="flex items-center gap-2 px-4 py-2 text-xs bg-warning/15 text-warning border-b border-warning/30">
      {status === "reconnecting" ? (
        <>
          <RefreshCw className="h-3.5 w-3.5 animate-spin" />
          <span>连接断开，重连中（第 {retryAttempt || 1} 次）...</span>
        </>
      ) : (
        <>
          <WifiOff className="h-3.5 w-3.5" />
          <span>连接断开</span>
        </>
      )}
    </div>
  );
}
