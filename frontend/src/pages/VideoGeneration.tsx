import { useEffect, useRef, useState } from "react";
import {
  Clapperboard,
  CircleAlert,
  Download,
  ImagePlus,
  Link2,
  Loader2,
  Music2,
  Sparkles,
  Trash2,
  Video,
} from "lucide-react";
import { api, type VideoGenerationTask } from "@/lib/api";

type ReferenceImage = { name: string; url: string };

const STATUS_TEXT: Record<string, string> = {
  queued: "任务已排队",
  running: "正在生成视频",
  in_progress: "正在生成视频",
  succeeded: "生成完成",
  failed: "生成失败",
  expired: "结果已过期",
};

function taskError(task: VideoGenerationTask): string {
  const message = typeof task.error === "string"
    ? task.error
    : task.error?.message || task.error?.code || "";
  if (/error while downloading/i.test(message) && /status code:\s*404/i.test(message)) {
    return "参考素材地址已失效或无法公开访问（HTTP 404）。请删除该 URL，先把图片下载到电脑，再通过“上传”添加后重新生成。";
  }
  if (/error while downloading/i.test(message)) {
    return "Seedance 无法读取参考素材。请确认素材地址可公开下载，或改为上传本地图片后重试。";
  }
  return message || "视频生成失败，请调整提示词后重试。";
}

function isTemporaryArkImageUrl(url: string): boolean {
  if (!url.startsWith("https://")) return false;
  try {
    const parsed = new URL(url);
    return (
      parsed.searchParams.has("X-Tos-Signature") ||
      (parsed.hostname.includes("ark-acg-") && parsed.pathname.includes("doubao-seedream"))
    );
  } catch {
    return false;
  }
}

const TEMPORARY_IMAGE_MESSAGE =
  "这是火山引擎生成结果的临时签名地址，Seedance 可能无法读取。请先把图片下载到电脑，再使用上方“上传”添加。";

export function VideoGeneration({ embedded = false }: { embedded?: boolean }) {
  const [prompt, setPrompt] = useState("");
  const [images, setImages] = useState<ReferenceImage[]>([]);
  const [imageUrl, setImageUrl] = useState("");
  const [videoUrl, setVideoUrl] = useState("");
  const [audioUrl, setAudioUrl] = useState("");
  const [ratio, setRatio] = useState<"16:9" | "9:16" | "1:1" | "4:3" | "3:4" | "21:9">("16:9");
  const [resolution, setResolution] = useState<"480p" | "720p" | "1080p">("720p");
  const [duration, setDuration] = useState(5);
  const [generateAudio, setGenerateAudio] = useState(true);
  const [watermark, setWatermark] = useState(false);
  const [task, setTask] = useState<VideoGenerationTask | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState("");
  const pollTimer = useRef<number | null>(null);

  const stopPolling = () => {
    if (pollTimer.current !== null) window.clearTimeout(pollTimer.current);
    pollTimer.current = null;
  };

  useEffect(() => stopPolling, []);

  const poll = async (taskId: string) => {
    try {
      const next = await api.getVideoGenerationTask(taskId);
      setTask(next);
      if (next.status === "succeeded") {
        setSubmitting(false);
        return;
      }
      if (next.status === "failed" || next.status === "expired") {
        setSubmitting(false);
        setError(taskError(next));
        return;
      }
      pollTimer.current = window.setTimeout(() => void poll(taskId), 4000);
    } catch (err) {
      setSubmitting(false);
      setError(err instanceof Error ? err.message : "查询视频生成状态失败");
    }
  };

  const addFiles = async (files: FileList | null) => {
    if (!files) return;
    setError("");
    const remaining = 4 - images.length;
    const selected = Array.from(files).slice(0, remaining);
    if (selected.some((file) => file.size > 5 * 1024 * 1024)) {
      setError("每张参考图片不能超过 5 MB。再次选择时请使用更小的图片。");
      return;
    }
    const loaded = await Promise.all(selected.map((file) => new Promise<ReferenceImage>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve({ name: file.name, url: String(reader.result) });
      reader.onerror = () => reject(new Error(`无法读取 ${file.name}`));
      reader.readAsDataURL(file);
    })));
    setImages((current) => [...current, ...loaded].slice(0, 4));
  };

  const addImageUrl = () => {
    const value = imageUrl.trim();
    if (!value) return;
    if (!value.startsWith("https://")) {
      setError("参考图片地址必须以 https:// 开头。");
      return;
    }
    if (isTemporaryArkImageUrl(value)) {
      setError(TEMPORARY_IMAGE_MESSAGE);
      return;
    }
    if (images.length >= 4) {
      setError("最多添加 4 张参考图片。");
      return;
    }
    setImages((current) => [...current, { name: `参考图片 ${current.length + 1}`, url: value }]);
    setImageUrl("");
    setError("");
  };

  const submit = async () => {
    if (!prompt.trim()) {
      setError("请先写下你想生成的视频内容。");
      return;
    }
    if (images.some((image) => isTemporaryArkImageUrl(image.url))) {
      setError(TEMPORARY_IMAGE_MESSAGE);
      return;
    }
    stopPolling();
    setError("");
    setTask(null);
    setSubmitting(true);
    try {
      const created = await api.createVideoGenerationTask({
        prompt: prompt.trim(),
        image_urls: images.map((image) => image.url),
        reference_video_url: videoUrl.trim() || undefined,
        reference_audio_url: audioUrl.trim() || undefined,
        ratio,
        resolution,
        duration,
        generate_audio: generateAudio,
        watermark,
      });
      setTask({ ...created, status: created.status || "queued" });
      void poll(created.id);
    } catch (err) {
      setSubmitting(false);
      setError(err instanceof Error ? err.message : "视频任务创建失败");
    }
  };

  const download = async () => {
    if (!task?.id) return;
    setDownloading(true);
    setError("");
    try {
      await api.downloadGeneratedVideo(task.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "视频下载失败");
    } finally {
      setDownloading(false);
    }
  };

  const outputUrl = task?.video_url || task?.content?.video_url;

  return (
    <div className={`mx-auto w-full max-w-7xl space-y-6 p-4 md:p-6 ${embedded ? "pt-4 md:pt-4" : ""}`}>
      <header>
        <div className="flex items-center gap-2">
          <Clapperboard className="h-6 w-6 text-primary" />
          <h1 className="text-2xl font-semibold">视频生成</h1>
        </div>
        <p className="mt-1 text-sm text-muted-foreground">使用豆包 Seedance 2.0，将提示词和参考素材生成视频。</p>
      </header>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.15fr)_minmax(340px,.85fr)]">
        <section className="space-y-6 rounded-xl border bg-card p-5 shadow-sm">
          <div>
            <label htmlFor="video-prompt" className="mb-2 block text-sm font-medium">视频描述</label>
            <textarea
              id="video-prompt"
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              rows={8}
              maxLength={5000}
              placeholder="例如：第一人称城市夜景短片，镜头缓慢穿过雨后的街道，霓虹灯倒映在路面……"
              className="w-full resize-y rounded-lg border bg-background px-3 py-2 text-sm outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/20"
            />
            <div className="mt-1 text-right text-xs text-muted-foreground">{prompt.length} / 5000</div>
          </div>

          <div>
            <div className="mb-2 flex items-center gap-2 text-sm font-medium"><ImagePlus className="h-4 w-4" />参考图片（可选，最多 4 张）</div>
            <label className="flex cursor-pointer items-center justify-center gap-2 rounded-lg border border-dashed px-4 py-6 text-sm text-muted-foreground transition hover:border-primary hover:text-primary">
              <ImagePlus className="h-5 w-5" />
              上传 JPG、PNG 或 WebP（每张不超过 5 MB）
              <input type="file" accept="image/jpeg,image/png,image/webp" multiple className="hidden" onChange={(event) => void addFiles(event.target.files)} />
            </label>
            <div className="mt-3 flex gap-2">
              <div className="relative min-w-0 flex-1">
                <Link2 className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
                <input value={imageUrl} onChange={(event) => setImageUrl(event.target.value)} placeholder="或粘贴图片 HTTPS 地址" className="w-full rounded-md border bg-background py-2 pl-9 pr-3 text-sm" />
              </div>
              <button type="button" onClick={addImageUrl} className="rounded-md border px-3 text-sm hover:bg-muted">添加</button>
            </div>
            {images.length > 0 && (
              <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
                {images.map((image, index) => (
                  <div key={`${image.name}-${index}`} className="group relative aspect-video overflow-hidden rounded-lg border bg-muted">
                    <img src={image.url} alt={image.name} className="h-full w-full object-cover" />
                    <button type="button" aria-label={`删除 ${image.name}`} onClick={() => setImages((current) => current.filter((_, itemIndex) => itemIndex !== index))} className="absolute right-1 top-1 rounded bg-black/65 p-1 text-white opacity-80 hover:opacity-100">
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <label className="space-y-2 text-sm font-medium">
              <span className="flex items-center gap-2"><Video className="h-4 w-4" />参考视频 URL（可选）</span>
              <input type="url" value={videoUrl} onChange={(event) => setVideoUrl(event.target.value)} placeholder="https://…/reference.mp4" className="w-full rounded-md border bg-background px-3 py-2 font-normal" />
            </label>
            <label className="space-y-2 text-sm font-medium">
              <span className="flex items-center gap-2"><Music2 className="h-4 w-4" />参考音频 URL（可选）</span>
              <input type="url" value={audioUrl} onChange={(event) => setAudioUrl(event.target.value)} placeholder="https://…/music.mp3" className="w-full rounded-md border bg-background px-3 py-2 font-normal" />
            </label>
          </div>

          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
            <label className="space-y-2 text-sm font-medium">画面比例
              <select value={ratio} onChange={(event) => setRatio(event.target.value as typeof ratio)} className="w-full rounded-md border bg-background px-3 py-2 font-normal">
                <option value="16:9">16:9 横屏</option><option value="9:16">9:16 竖屏</option><option value="1:1">1:1 方形</option><option value="4:3">4:3</option><option value="3:4">3:4</option><option value="21:9">21:9 超宽屏</option>
              </select>
            </label>
            <label className="space-y-2 text-sm font-medium">清晰度
              <select value={resolution} onChange={(event) => setResolution(event.target.value as typeof resolution)} className="w-full rounded-md border bg-background px-3 py-2 font-normal">
                <option value="480p">480p</option><option value="720p">720p</option><option value="1080p">1080p</option>
              </select>
            </label>
            <label className="space-y-2 text-sm font-medium">时长
              <select value={duration} onChange={(event) => setDuration(Number(event.target.value))} className="w-full rounded-md border bg-background px-3 py-2 font-normal">
                {[4, 5, 6, 8, 10, 11, 12].map((value) => <option key={value} value={value}>{value} 秒</option>)}
              </select>
            </label>
          </div>

          <div className="flex flex-wrap gap-6 rounded-lg bg-muted/50 p-3 text-sm">
            <label className="flex cursor-pointer items-center gap-2"><input type="checkbox" checked={generateAudio} onChange={(event) => setGenerateAudio(event.target.checked)} className="h-4 w-4 accent-primary" />同步生成音频</label>
            <label className="flex cursor-pointer items-center gap-2"><input type="checkbox" checked={watermark} onChange={(event) => setWatermark(event.target.checked)} className="h-4 w-4 accent-primary" />添加水印</label>
          </div>

          {error && <div role="alert" className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</div>}
          <button type="button" onClick={() => void submit()} disabled={submitting || !prompt.trim()} className="flex w-full items-center justify-center gap-2 rounded-lg bg-primary px-4 py-3 font-medium text-primary-foreground transition hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50">
            {submitting ? <Loader2 className="h-5 w-5 animate-spin" /> : <Sparkles className="h-5 w-5" />}
            {submitting ? STATUS_TEXT[task?.status || "queued"] : "生成视频"}
          </button>
        </section>

        <aside className="rounded-xl border bg-card p-5 shadow-sm lg:sticky lg:top-6 lg:h-fit">
          <h2 className="font-semibold">生成结果</h2>
          {!task && (
            <div className="mt-4 flex min-h-72 flex-col items-center justify-center rounded-lg border border-dashed bg-muted/30 p-8 text-center text-muted-foreground">
              <Clapperboard className="mb-3 h-10 w-10 opacity-40" />
              <p className="text-sm">填写提示词并点击生成后，视频会显示在这里。</p>
            </div>
          )}
          {task && !outputUrl && (
            <div className="mt-4 flex min-h-72 flex-col items-center justify-center rounded-lg bg-muted/40 p-8 text-center">
              {task.status === "failed" || task.status === "expired"
                ? <CircleAlert className="mb-4 h-9 w-9 text-destructive" />
                : <Loader2 className="mb-4 h-9 w-9 animate-spin text-primary" />}
              <p className="font-medium">{STATUS_TEXT[task.status || "queued"]}</p>
              <p className="mt-2 text-xs text-muted-foreground">Seedance 正在处理，页面会自动更新，无需重复点击。</p>
              <p className="mt-4 max-w-full truncate font-mono text-[11px] text-muted-foreground">{task.id}</p>
            </div>
          )}
          {outputUrl && (
            <div className="mt-4 space-y-4">
              <video src={outputUrl} controls playsInline className="w-full rounded-lg bg-black" />
              <div className="flex items-center justify-between text-xs text-muted-foreground">
                <span>{task.resolution || resolution} · {task.ratio || ratio}</span><span>{task.duration || duration} 秒</span>
              </div>
              <button type="button" onClick={() => void download()} disabled={downloading} className="flex w-full items-center justify-center gap-2 rounded-lg border px-4 py-2.5 text-sm font-medium transition hover:bg-muted disabled:opacity-50">
                {downloading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Download className="h-4 w-4" />}
                {downloading ? "正在下载" : "下载到本地"}
              </button>
            </div>
          )}
          <p className="mt-4 text-xs leading-5 text-muted-foreground">参考素材和提示词会发送至火山引擎 Ark。请仅上传你有权使用的内容；生成任务可能产生模型调用费用。</p>
        </aside>
      </div>
    </div>
  );
}
