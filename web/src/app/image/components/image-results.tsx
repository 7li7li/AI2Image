"use client";

import { useEffect, useMemo, useState } from "react";
import { Clock3, Copy, ImageIcon, LoaderCircle, RefreshCw, Share2, Sparkles, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { createPromptShare, fetchPromptLibrary, type PromptLibraryItem, type PromptLibraryPayload } from "@/lib/api";
import { resolveApiAssetUrl } from "@/lib/assets";
import { cn } from "@/lib/utils";
import type { ImageConversation, ImageTurnStatus, StoredImage, StoredReferenceImage } from "@/store/image-conversations";

export type ImageLightboxItem = {
  id: string;
  src: string;
  sizeLabel?: string;
  dimensions?: string;
};

type ImageResultsProps = {
  selectedConversation: ImageConversation | null;
  onOpenLightbox: (images: ImageLightboxItem[], index: number) => void;
  onContinueEdit: (conversationId: string, image: StoredImage | StoredReferenceImage) => void;
  onRegenerate: (conversationId: string, turn: ImageConversation["turns"][number]) => void;
  onDeleteTurn: (conversationId: string, turnId: string) => void | Promise<void>;
  formatConversationTime: (value: string) => string;
};

type EmptyStatePromptSource = {
  id?: string;
  title?: string;
  label?: string;
  fallbackTitle: string;
  fallbackDescription?: string;
  fallbackPreview: string;
};

const emptyStateExampleSources: EmptyStatePromptSource[] = [
  {
    title: "包装贴合效果",
    label: "包装贴合效果",
    fallbackTitle: "包装贴合效果",
    fallbackPreview: "/banana-prompt-quicker/external/pbs.twimg.com/83fb94b764edcbdfce00f78f.jpg",
  },
  {
    title: "时尚杂志封面风格",
    label: "时尚杂志封面风格",
    fallbackTitle: "时尚杂志封面风格",
    fallbackPreview: "/banana-prompt-quicker/external/bibigpt-apps.chatvid.ai/081ec7325039543b79c27572.png",
  },
  {
    title: "产品原型图",
    label: "产品原型图",
    fallbackTitle: "产品原型图",
    fallbackPreview: "/banana-prompt-quicker/external/pbs.twimg.com/0e65471a02a977f41b998482.jpg",
  },
  {
    title: "时尚心情板拼贴",
    label: "时尚心情板拼贴",
    fallbackTitle: "时尚心情板拼贴",
    fallbackPreview: "/banana-prompt-quicker/external/pbs.twimg.com/36faf385d4541ff7c5ab41b0.jpg",
  },
];

function buildPromptShareTitle(prompt: string) {
  const cleaned = prompt.replace(/\s+/g, " ").trim();
  if (!cleaned) {
    return "未命名提示词";
  }
  return cleaned.length > 24 ? `${cleaned.slice(0, 24)}...` : cleaned;
}

function shareUrlFromId(shareId: string) {
  if (typeof window === "undefined") {
    return `/prompt-manager?share=${encodeURIComponent(shareId)}`;
  }
  return `${window.location.origin}/prompt-manager?share=${encodeURIComponent(shareId)}`;
}

async function sharePromptPayload(payload: PromptLibraryPayload) {
  const data = await createPromptShare(payload);
  const shareUrl = shareUrlFromId(data.share_id);
  if (navigator.share) {
    try {
      await navigator.share({ title: payload.title, text: payload.description || payload.title, url: shareUrl });
      return "shared";
    } catch {
      // Fall back to clipboard below when native sharing is cancelled or unavailable.
    }
  }
  await navigator.clipboard.writeText(shareUrl);
  return "copied";
}

export function ImageResults({
  selectedConversation,
  onOpenLightbox,
  onContinueEdit,
  onRegenerate,
  onDeleteTurn,
  formatConversationTime,
}: ImageResultsProps) {
  const [imageDimensions, setImageDimensions] = useState<Record<string, string>>({});
  const [promptLibraryItems, setPromptLibraryItems] = useState<PromptLibraryItem[]>([]);
  const shouldShowEmptyState = !selectedConversation || selectedConversation.turns.length === 0;

  useEffect(() => {
    if (!shouldShowEmptyState) {
      return;
    }

    let cancelled = false;
    void fetchPromptLibrary()
      .then((data) => {
        if (!cancelled) {
          setPromptLibraryItems(data.items || data.prompts || []);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setPromptLibraryItems([]);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [shouldShowEmptyState]);

  const emptyStateExamples = useMemo(
    () => emptyStateExampleSources.map((source) => buildEmptyStatePromptPreview(source, promptLibraryItems)),
    [promptLibraryItems],
  );

  const updateImageDimensions = (id: string, width: number, height: number) => {
    const dimensions = formatImageDimensions(width, height);
    setImageDimensions((current) => {
      if (current[id] === dimensions) {
        return current;
      }
      return { ...current, [id]: dimensions };
    });
  };

  const copyTurnPrompt = async (prompt: string) => {
    const cleaned = prompt.trim();
    if (!cleaned) {
      toast.error("没有可复制的提示词");
      return;
    }
    await navigator.clipboard.writeText(cleaned);
    toast.success("提示词已复制");
  };

  const shareTurnPrompt = async (turn: { prompt: string; mode: string; size: string; count: number }) => {
    const cleaned = turn.prompt.trim();
    if (!cleaned) {
      toast.error("没有可分享的提示词");
      return;
    }
    try {
      const result = await sharePromptPayload({
        title: buildPromptShareTitle(cleaned),
        description: turn.mode === "edit" ? "图生图提示词" : "文生图提示词",
        prompt: cleaned,
        mode: turn.mode,
        image_size: turn.size,
        image_count: String(turn.count),
      });
      toast.success(result === "shared" ? "分享已打开" : "分享链接已复制");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "分享失败");
    }
  };

  if (shouldShowEmptyState) {
    return (
      <div className="image-empty-state grid content-center gap-3">
        <div className="p-5 text-center">
          <div className="mx-auto grid size-12 place-items-center rounded-lg bg-gradient-to-br from-rose-100 to-fuchsia-100 text-rose-500">
            <ImageIcon className="size-5" />
          </div>
          <h1 className="mt-4 text-2xl font-bold tracking-tight text-stone-950">从下方创作台开始</h1>
          <p className="mt-2 text-sm leading-6 text-stone-500">
            支持文生图、图生图、参考图上传和粘贴、提示词库、队列恢复、灯箱预览与继续编辑。
          </p>
        </div>
        <div className="image-empty-examples-grid mx-auto grid w-full gap-3">
          {emptyStateExamples.map((item) => (
            <div key={item.label} className="overflow-hidden rounded-lg border border-white/70 bg-white/46 shadow-sm backdrop-blur-sm">
              <div className="aspect-[4/3] bg-white/46">
                <img
                  src={item.preview}
                  alt={`${item.label}示例图`}
                  className="h-full w-full object-cover"
                  loading="eager"
                  decoding="async"
                />
              </div>
              <div className="px-3 py-2 text-sm font-semibold text-stone-800">{item.label}</div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {selectedConversation.turns.map((turn, turnIndex) => {
        const referenceLightboxImages = turn.referenceImages.map((image, index) => ({
          id: `${turn.id}-reference-${index}`,
          src: image.dataUrl,
        }));
        const successfulTurnImages = turn.images.flatMap((image) => {
          const imageSrc = getStoredImageSrc(image);
          return image.status === "success" && imageSrc
            ? [
                {
                  id: image.id,
                  src: imageSrc,
                  sizeLabel: image.b64_json && !image.url ? formatBase64ImageSize(image.b64_json) : undefined,
                  dimensions: imageDimensions[image.id],
                },
              ]
            : [];
        });

        return (
          <section key={turn.id} className="group overflow-hidden rounded-lg bg-white/46 shadow-sm">
            <div className="bg-white/56 px-4 py-3">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="mb-2 flex flex-wrap gap-2 text-[11px] font-medium text-stone-400">
                    <span>第 {turnIndex + 1} 轮</span>
                    <span>{turn.mode === "edit" ? "图生图" : "文生图"}</span>
                    <span>{getTurnStatusLabel(turn.status)}</span>
                    <span>{formatConversationTime(turn.createdAt)}</span>
                  </div>
                  <p className="whitespace-pre-wrap break-words text-sm leading-6 text-stone-800">{turn.prompt}</p>
                </div>
                <div className="flex shrink-0 items-center gap-1.5">
                  <div className="pointer-events-none flex items-center gap-1.5 opacity-0 transition-opacity group-hover:pointer-events-auto group-hover:opacity-100 group-focus-within:pointer-events-auto group-focus-within:opacity-100">
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="size-8 rounded-full text-stone-500 hover:bg-stone-100 hover:text-stone-800"
                    onClick={() => onRegenerate(selectedConversation.id, turn)}
                    disabled={turn.status === "queued" || turn.status === "generating"}
                    title="重新生成"
                    aria-label="重新生成"
                  >
                    <RefreshCw className="size-4" />
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="size-8 rounded-full text-stone-500 hover:bg-stone-100 hover:text-stone-800"
                    onClick={() => void onDeleteTurn(selectedConversation.id, turn.id)}
                    disabled={turn.status === "queued" || turn.status === "generating"}
                    title="删除"
                    aria-label="删除"
                  >
                    <Trash2 className="size-4" />
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="size-8 rounded-full text-stone-500 hover:bg-stone-100 hover:text-stone-800"
                    onClick={() => void copyTurnPrompt(turn.prompt)}
                    title="复制"
                    aria-label="复制"
                  >
                    <Copy className="size-4" />
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="size-8 rounded-full text-stone-500 hover:bg-stone-100 hover:text-stone-800"
                    onClick={() => void shareTurnPrompt(turn)}
                    title="分享"
                    aria-label="分享"
                  >
                    <Share2 className="size-4" />
                  </Button>
                  </div>
                  <div className="rounded-full bg-rose-50 px-3 py-1 text-xs font-semibold text-stone-600">
                    {turn.count} 张
                  </div>
                </div>
              </div>
            </div>

            {turn.referenceImages.length > 0 ? (
              <div className="border-b border-rose-100/60 px-4 py-3">
                <div className="mb-3 text-xs font-semibold text-stone-500">本轮参考图</div>
                <div className="flex flex-wrap gap-3">
                  {turn.referenceImages.map((image, index) => (
                    <div key={`${turn.id}-${image.name}-${index}`} className="flex items-end gap-2">
                      <button
                        type="button"
                        onClick={() => onOpenLightbox(referenceLightboxImages, index)}
                        className="group relative size-20 overflow-hidden rounded-lg border border-rose-100 bg-rose-50/60 text-left transition hover:border-rose-200"
                        aria-label={`预览参考图 ${image.name || index + 1}`}
                      >
                        <img
                          src={image.dataUrl}
                          alt={image.name || `参考图 ${index + 1}`}
                          className="absolute inset-0 h-full w-full object-cover transition duration-200 group-hover:scale-[1.02]"
                        />
                      </button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="rounded-full text-stone-600 hover:bg-stone-100 hover:text-stone-900"
                        onClick={() => onContinueEdit(selectedConversation.id, image)}
                      >
                        <Sparkles className="size-4" />
                        加入编辑
                      </Button>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}

            <div className="grid gap-3 p-4 md:grid-cols-2 xl:grid-cols-3">
              {turn.images.map((image, index) => {
                const featured = index === 0 && turn.images.length > 1;

                if (image.status === "success" && (image.b64_json || image.url)) {
                  const currentIndex = successfulTurnImages.findIndex((item) => item.id === image.id);
                  const imageSrc = getStoredImageSrc(image);
                  const sizeLabel = image.b64_json && !image.url ? formatBase64ImageSize(image.b64_json) : "";
                  const dimensions = imageDimensions[image.id];
                  const imageMeta = [sizeLabel, dimensions].filter(Boolean).join(" · ");

                  return (
                    <div
                      key={image.id}
                      className={cn(
                        "overflow-hidden rounded-lg border border-white/75 bg-white/78 shadow-sm",
                        featured && "md:row-span-2",
                      )}
                    >
                      <button
                        type="button"
                        onClick={() => onOpenLightbox(successfulTurnImages, Math.max(0, currentIndex))}
                        className={cn("group block w-full cursor-zoom-in bg-stone-100", featured ? "aspect-[3/4]" : getImageAspectClass(turn.size))}
                      >
                        <img
                          src={imageSrc}
                          alt={`Generated result ${index + 1}`}
                          className="h-full w-full object-cover transition duration-200 group-hover:brightness-90"
                          loading="lazy"
                          decoding="async"
                          onLoad={(event) => {
                            updateImageDimensions(
                              image.id,
                              event.currentTarget.naturalWidth,
                              event.currentTarget.naturalHeight,
                            );
                          }}
                        />
                      </button>
                      <div className="flex flex-wrap items-center justify-between gap-2 px-3 py-3">
                        <div className="min-w-0 text-xs text-stone-500">
                          <span>结果 {index + 1}</span>
                          {imageMeta ? <span className="ml-2 text-stone-400">{imageMeta}</span> : null}
                        </div>
                        <div className="flex shrink-0 items-center gap-1.5">
                          <Button
                            variant="ghost"
                            size="sm"
                            className="rounded-full text-stone-600 hover:bg-stone-100 hover:text-stone-900"
                            onClick={() => onContinueEdit(selectedConversation.id, image)}
                          >
                            <Sparkles className="size-4" />
                            加入编辑
                          </Button>
                        </div>
                      </div>
                    </div>
                  );
                }

                if (image.status === "error") {
                  return (
                    <div
                      key={image.id}
                      className={cn(
                        "overflow-hidden rounded-lg border border-rose-200 bg-rose-50",
                        getImageAspectClass(turn.size),
                        featured && "md:row-span-2",
                      )}
                    >
                      <div className="flex h-full items-center justify-center px-6 py-8 text-center text-sm leading-6 text-rose-600">
                        {image.error || "生成失败"}
                      </div>
                    </div>
                  );
                }

                return (
                  <div
                    key={image.id}
                    className={cn(
                      "overflow-hidden rounded-lg border border-rose-100/80 bg-rose-50/70",
                      getImageAspectClass(turn.size),
                      featured && "md:row-span-2",
                    )}
                  >
                    <div className="flex h-full flex-col items-center justify-center gap-3 px-6 py-8 text-center text-stone-500">
                      <div className="rounded-full bg-white p-3 shadow-sm">
                        {turn.status === "queued" ? (
                          <Clock3 className="size-5" />
                        ) : (
                          <LoaderCircle className="size-5 animate-spin" />
                        )}
                      </div>
                      <p className="text-sm">{turn.status === "queued" ? "已加入当前对话队列..." : "正在处理图片..."}</p>
                    </div>
                  </div>
                );
              })}
            </div>

            {turn.status === "queued" ? (
              <div className="mx-4 mb-4 rounded-lg bg-amber-50/70 px-4 py-3 text-sm leading-6 text-amber-700">
                等待当前对话中的前序任务完成
              </div>
            ) : null}

            {turn.status === "error" && turn.error ? (
              <div className="mx-4 mb-4 border-l-2 border-amber-300 bg-amber-50/70 px-4 py-3 text-sm leading-6 text-amber-700">
                {turn.error}
              </div>
            ) : null}
          </section>
        );
      })}
    </div>
  );
}

function getImageAspectClass(size: string) {
  if (size === "1:1") return "aspect-square";
  if (size === "16:9") return "aspect-video";
  if (size === "9:16") return "aspect-[9/16]";
  if (size === "4:3") return "aspect-[4/3]";
  if (size === "3:4") return "aspect-[3/4]";
  return "aspect-[4/3]";
}

function getStoredImageSrc(image: StoredImage) {
  if (image.url) {
    return resolveApiAssetUrl(image.url);
  }
  if (image.b64_json) {
    return `data:image/png;base64,${image.b64_json}`;
  }
  return "";
}

function buildEmptyStatePromptPreview(source: EmptyStatePromptSource, items: PromptLibraryItem[]) {
  const prompt = items.find((item) => {
    if (source.id && item.id === source.id) {
      return true;
    }
    if (source.title && item.title === source.title) {
      return true;
    }
    return false;
  });

  return {
    label: source.label || prompt?.title || source.fallbackTitle,
    title: prompt?.title || source.fallbackTitle,
    description: prompt?.description || source.fallbackDescription || "",
    preview: resolveApiAssetUrl(prompt?.preview || source.fallbackPreview),
  };
}

function getTurnStatusLabel(status: ImageTurnStatus) {
  if (status === "queued") {
    return "排队中";
  }
  if (status === "generating") {
    return "处理中";
  }
  if (status === "success") {
    return "已完成";
  }
  return "失败";
}

function formatBase64ImageSize(base64: string) {
  const normalized = base64.replace(/\s/g, "");
  const padding = normalized.endsWith("==") ? 2 : normalized.endsWith("=") ? 1 : 0;
  const bytes = Math.max(0, Math.floor((normalized.length * 3) / 4) - padding);

  if (bytes >= 1024 * 1024) {
    return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
  }
  if (bytes >= 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${bytes} B`;
}

function formatImageDimensions(width: number, height: number) {
  return `${width} x ${height}`;
}
