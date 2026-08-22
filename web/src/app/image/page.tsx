"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  LoaderCircle,
  Menu,
  Plus,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";

import { ImageComposer } from "@/app/image/components/image-composer";
import type { AnnotationEditResult } from "@/app/image/components/annotation-editor-dialog";
import { ImageResults, type ImageLightboxItem } from "@/app/image/components/image-results";
import { ImageSidebar } from "@/app/image/components/image-sidebar";
import { ImageLightbox } from "@/components/image-lightbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import {
  createImageEditTask,
  createImageGenerationTask,
  fetchBackgroundTask,
  fetchBackgroundTaskStats,
  fetchAvailableModels,
  fetchManagedImages,
  fetchModelQuotaCosts,
  fetchMyImages,
  polishImagePrompt,
  streamBackgroundTask,
  type BackgroundTaskStatus,
  type ImageRequestOptions,
  type ImageResponse,
} from "@/lib/api";
import { resolveApiAssetUrl } from "@/lib/assets";
import { imageModelOptions } from "@/lib/model-options";
import { useSiteSettingsStore } from "@/lib/site-settings";
import { useAuthGuard } from "@/lib/use-auth-guard";
import { cn } from "@/lib/utils";
import {
  clearImageConversations,
  deleteImageConversation,
  DEFAULT_IMAGE_MODERATION,
  DEFAULT_IMAGE_QUALITY,
  DEFAULT_IMAGE_TRANSPARENT_BACKGROUND,
  getImageConversationOwnerKey,
  getImageConversationStats,
  IMAGE_CONVERSATIONS_CHANGED_EVENT,
  listImageConversations,
  saveImageConversation,
  saveImageConversations,
  type ImageConversationsChangedDetail,
  type ImageConversation,
  type ImageConversationMode,
  type ImageTurn,
  type ImageTurnStatus,
  type StoredImage,
  type StoredReferenceImage,
} from "@/store/image-conversations";
import type { StoredAuthSession } from "@/store/auth";

const ACTIVE_CONVERSATION_STORAGE_KEY = "chatgpt2api:image_active_conversation_id";
const QUOTA_REFRESH_EVENT = "yanai:quota-refresh";
const IMAGE_SIZE_STORAGE_KEY = "chatgpt2api:image_last_size";
const IMAGE_RESOLUTION_STORAGE_KEY = "chatgpt2api:image_last_resolution";
const IMAGE_QUALITY_STORAGE_KEY = "chatgpt2api:image_last_quality";
const IMAGE_MODERATION_STORAGE_KEY = "chatgpt2api:image_last_moderation";
const IMAGE_TRANSPARENT_BACKGROUND_STORAGE_KEY = "chatgpt2api:image_last_transparent_background";
const IMAGE_MODEL_STORAGE_KEY = "chatgpt2api:image_last_model";
const SUPPORTED_IMAGE_SIZES = new Set([
  "",
  "1:1",
  "3:2",
  "2:3",
  "16:9",
  "9:16",
  "4:3",
  "3:4",
  "5:4",
  "4:5",
  "21:9",
  "9:21",
  "8:1",
  "4:1",
  "1:4",
  "1:8",
]);
const BACKGROUND_TASK_POLL_INTERVAL_MS = 1500;
const activeImageTurnQueueIds = new Set<string>();

type PreparedReferenceImage = {
  referenceImage: StoredReferenceImage;
  file: File;
};

function normalizeQuotaCost(value: unknown) {
  const parsed = Number(value ?? 1);
  if (!Number.isFinite(parsed)) {
    return 1;
  }
  return Math.max(0, parsed);
}

function buildModelQuotaCosts(models: Array<{ id?: string; quota_cost?: number }>) {
  const costs: Record<string, number> = {};
  for (const model of models) {
    const modelId = String(model.id || "").trim().toLowerCase();
    if (modelId) {
      costs[modelId] = normalizeQuotaCost(model.quota_cost);
    }
  }
  return costs;
}

function normalizeModelQuotaCostMap(costs: Record<string, number> | undefined) {
  const normalized: Record<string, number> = {};
  for (const [model, cost] of Object.entries(costs || {})) {
    const modelId = model.trim().toLowerCase();
    if (modelId) {
      normalized[modelId] = normalizeQuotaCost(cost);
    }
  }
  return normalized;
}

function quotaCostForModel(costs: Record<string, number>, model: string) {
  const modelId = model.trim().toLowerCase();
  return modelId ? costs[modelId] ?? 1 : 1;
}

function formatQuotaCost(value: number) {
  return value.toFixed(8).replace(/\.?0+$/, "");
}

function getScopedStorageKey(baseKey: string, ownerKey: string) {
  return ownerKey ? `${baseKey}:${ownerKey}` : baseKey;
}

function buildConversationTitle(prompt: string) {
  const trimmed = prompt.trim();
  if (trimmed.length <= 12) {
    return trimmed;
  }
  return `${trimmed.slice(0, 12)}...`;
}

function formatConversationTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function createId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function readFileAsDataUrl(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("读取参考图失败"));
    reader.readAsDataURL(file);
  });
}

function dataUrlToFile(dataUrl: string, fileName: string, mimeType?: string) {
  const [header, content] = dataUrl.split(",", 2);
  const matchedMimeType = header.match(/data:(.*?);base64/)?.[1];
  const binary = atob(content || "");
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return new File([bytes], fileName, { type: mimeType || matchedMimeType || "image/png" });
}

async function imageUrlToFile(url: string, fileName: string) {
  const response = await fetch(resolveApiAssetUrl(url));
  if (!response.ok) {
    throw new Error(`读取生成图失败 (${response.status})`);
  }
  const blob = await response.blob();
  const mimeType = blob.type || "image/png";
  return new File([blob], fileName, { type: mimeType });
}

async function buildReferenceImageFromResult(
  image: StoredImage,
  fileName: string,
): Promise<PreparedReferenceImage | null> {
  if (image.url) {
    try {
      const file = await imageUrlToFile(image.url, fileName);
      const referenceImage = {
        name: file.name,
        type: file.type || "image/png",
        dataUrl: await readFileAsDataUrl(file),
      };
      return { referenceImage, file };
    } catch (error) {
      if (!image.b64_json) {
        throw error;
      }
    }
  }

  if (!image.b64_json) {
    return null;
  }

  const referenceImage = {
    name: fileName,
    type: "image/png",
    dataUrl: `data:image/png;base64,${image.b64_json}`,
  };
  return {
    referenceImage,
    file: dataUrlToFile(referenceImage.dataUrl, referenceImage.name, referenceImage.type),
  };
}

function pickFallbackConversationId(conversations: ImageConversation[]) {
  const activeConversation = conversations.find((conversation) =>
    conversation.turns.some((turn) => turn.status === "queued" || turn.status === "generating"),
  );
  return activeConversation?.id ?? conversations[0]?.id ?? null;
}

function sortImageConversations(conversations: ImageConversation[]) {
  return [...conversations].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
}

function normalizeImageSize(value: string | null | undefined) {
  const normalized = String(value || "").trim();
  return SUPPORTED_IMAGE_SIZES.has(normalized) ? normalized : "";
}

function buildImageRequestOptions(turn: Pick<
  ImageTurn,
  "size" | "resolution" | "quality" | "moderation" | "transparentBackground"
>): ImageRequestOptions {
  return {
    size: normalizeImageSize(turn.size),
    resolution: turn.resolution,
    quality: turn.quality || DEFAULT_IMAGE_QUALITY,
    output_format: "png",
    output_compression: null,
    moderation: turn.moderation || DEFAULT_IMAGE_MODERATION,
    background: turn.transparentBackground ? "transparent" : undefined,
  };
}

function delay(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function waitForBackgroundTaskResult<T>(initialTask: BackgroundTaskStatus<T>) {
  let task = initialTask;
  if (task.status === "queued" || task.status === "running") {
    try {
      await streamBackgroundTask<T>(
        task.task_id || task.id,
        (nextTask) => {
          task = nextTask;
        },
        { version: task.version ?? -1 },
      );
    } catch {
      // Older deployments or proxies may not support SSE; polling keeps those setups working.
    }
  }
  while (task.status === "queued" || task.status === "running") {
    await delay(BACKGROUND_TASK_POLL_INTERVAL_MS);
    task = await fetchBackgroundTask<T>(task.task_id || task.id);
  }
  if (task.status === "error") {
    throw new Error(task.error || "任务处理失败");
  }
  if (!task.result) {
    throw new Error("任务没有返回结果");
  }
  return task.result;
}

async function fetchGeneratedImageByRequestId(
  requestId: string,
  role: StoredAuthSession["role"],
): Promise<ImageResponse | null> {
  if (!requestId) {
    return null;
  }
  try {
    const page =
      role === "admin"
        ? await fetchManagedImages({ request_id: requestId, page_size: 1 })
        : await fetchMyImages({ request_id: requestId, page_size: 1 });
    const item = page.items[0];
    if (!item?.url) {
      return null;
    }
    const createdAt = new Date(item.created_at || "").getTime();
    return {
      created: Number.isFinite(createdAt) ? Math.floor(createdAt / 1000) : Math.floor(Date.now() / 1000),
      data: [{ url: item.url }],
    };
  } catch {
    return null;
  }
}

function isSameLocalDay(value: string, date = new Date()) {
  const target = new Date(value);
  if (Number.isNaN(target.getTime())) {
    return false;
  }
  return (
    target.getFullYear() === date.getFullYear() &&
    target.getMonth() === date.getMonth() &&
    target.getDate() === date.getDate()
  );
}

function getWorkspaceStats(conversations: ImageConversation[]) {
  let todayGenerated = 0;
  let successImages = 0;
  let failedImages = 0;
  let queued = 0;
  let running = 0;

  for (const conversation of conversations) {
    const stats = getImageConversationStats(conversation);
    queued += stats.queued;
    running += stats.running;

    for (const turn of conversation.turns) {
      for (const image of turn.images) {
        if (image.status === "success") {
          successImages += 1;
          if (isSameLocalDay(turn.createdAt)) {
            todayGenerated += 1;
          }
        } else if (image.status === "error") {
          failedImages += 1;
        }
      }
    }
  }

  const completed = successImages + failedImages;
  return {
    todayGenerated,
    successImages,
    failedImages,
    queued,
    running,
    active: queued + running,
    successRate: completed > 0 ? `${((successImages / completed) * 100).toFixed(1)}%` : "--",
  };
}

function conversationMatchesQuery(conversation: ImageConversation, query: string) {
  const normalizedQuery = query.trim().toLowerCase();
  if (!normalizedQuery) {
    return true;
  }

  return (
    conversation.title.toLowerCase().includes(normalizedQuery) ||
    conversation.turns.some((turn) =>
      [
        turn.prompt,
        turn.mode,
        turn.status,
        turn.size,
        turn.resolution,
        turn.quality,
        turn.outputFormat,
        turn.outputCompression,
        turn.moderation,
        turn.transparentBackground ? "transparent" : "",
      ].some((value) =>
        String(value || "").toLowerCase().includes(normalizedQuery),
      ),
    )
  );
}

async function recoverConversationHistory(
  items: ImageConversation[],
  ownerKey: string,
  options: { isConversationQueueActive?: (conversationId: string) => boolean } = {},
) {
  const normalized = items.map((conversation) => {
    let changed = false;
    const isConversationQueueActive = options.isConversationQueueActive?.(conversation.id) ?? false;

    const turns = conversation.turns.map((turn) => {
      if (turn.status !== "queued" && turn.status !== "generating") {
        return turn;
      }

      const loadingCount = turn.images.filter((image) => image.status === "loading").length;
      if (loadingCount > 0) {
        if (turn.status === "generating" && !isConversationQueueActive) {
          changed = true;
          return {
            ...turn,
            status: "queued" as const,
            error: undefined,
          };
        }
        return turn;
      }

      const failedCount = turn.images.filter((image) => image.status === "error").length;
      const successCount = turn.images.filter((image) => image.status === "success").length;
      const nextStatus: ImageTurnStatus =
        failedCount > 0 ? "error" : successCount > 0 ? "success" : "queued";
      const nextError = failedCount > 0 ? turn.error || `其中 ${failedCount} 张未成功生成` : undefined;
      if (nextStatus === turn.status && nextError === turn.error) {
        return turn;
      }

      changed = true;
      return {
        ...turn,
        status: nextStatus,
        error: nextError,
      };
    });

    if (!changed) {
      return conversation;
    }

    return {
      ...conversation,
      turns,
      updatedAt: new Date().toISOString(),
    };
  });

  const changedConversations = normalized.filter((conversation, index) => conversation !== items[index]);
  if (changedConversations.length > 0) {
    await saveImageConversations(normalized, ownerKey);
  }

  return normalized;
}

function ImagePageContent({ session }: { session: StoredAuthSession }) {
  const conversationsRef = useRef<ImageConversation[]>([]);
  const resultsViewportRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [workspaceSearch, setWorkspaceSearch] = useState("");
  const [imagePrompt, setImagePrompt] = useState("");
  const [imageCount, setImageCount] = useState("1");
  const [imageMode, setImageMode] = useState<ImageConversationMode>("generate");
  const [imageSize, setImageSize] = useState("");
  const [imageResolution, setImageResolution] = useState("auto");
  const [imageQuality, setImageQuality] = useState(DEFAULT_IMAGE_QUALITY);
  const [imageModeration, setImageModeration] = useState(DEFAULT_IMAGE_MODERATION);
  const [imageTransparentBackground, setImageTransparentBackground] = useState(DEFAULT_IMAGE_TRANSPARENT_BACKGROUND);
  const [selectedImageModel, setSelectedImageModel] = useState("");
  const [availableModels, setAvailableModels] = useState<string[]>([]);
  const [imageModelResolutions, setImageModelResolutions] = useState<Record<string, string[]>>({});
  const [modelQuotaCosts, setModelQuotaCosts] = useState<Record<string, number>>({});
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  const [referenceImageFiles, setReferenceImageFiles] = useState<File[]>([]);
  const [referenceImages, setReferenceImages] = useState<StoredReferenceImage[]>([]);
  const [conversations, setConversations] = useState<ImageConversation[]>([]);
  const [selectedConversationId, setSelectedConversationId] = useState<string | null>(null);
  const [isLoadingHistory, setIsLoadingHistory] = useState(true);
  const [taskConcurrency, setTaskConcurrency] = useState(1);
  const [queueTick, setQueueTick] = useState(0);
  const [lightboxImages, setLightboxImages] = useState<ImageLightboxItem[]>([]);
  const [lightboxOpen, setLightboxOpen] = useState(false);
  const [lightboxIndex, setLightboxIndex] = useState(0);
  const [deleteConfirm, setDeleteConfirm] = useState<{ type: "one"; id: string } | { type: "all" } | null>(null);
  const [isPolishingPrompt, setIsPolishingPrompt] = useState(false);

  const defaultImageModel = useSiteSettingsStore((state) => state.settings.default_image_model || "gpt-image-2");
  const defaultImagePromptPolishModel = useSiteSettingsStore(
    (state) => state.settings.default_image_prompt_polish_model || "gpt-5.5",
  );
  const imageConversationOwnerKey = useMemo(() => getImageConversationOwnerKey(session), [session]);
  const activeConversationStorageKey = useMemo(
    () => getScopedStorageKey(ACTIVE_CONVERSATION_STORAGE_KEY, imageConversationOwnerKey),
    [imageConversationOwnerKey],
  );
  const imageSizeStorageKey = useMemo(
    () => getScopedStorageKey(IMAGE_SIZE_STORAGE_KEY, imageConversationOwnerKey),
    [imageConversationOwnerKey],
  );
  const imageResolutionStorageKey = useMemo(
    () => getScopedStorageKey(IMAGE_RESOLUTION_STORAGE_KEY, imageConversationOwnerKey),
    [imageConversationOwnerKey],
  );
  const imageQualityStorageKey = useMemo(
    () => getScopedStorageKey(IMAGE_QUALITY_STORAGE_KEY, imageConversationOwnerKey),
    [imageConversationOwnerKey],
  );
  const imageModerationStorageKey = useMemo(
    () => getScopedStorageKey(IMAGE_MODERATION_STORAGE_KEY, imageConversationOwnerKey),
    [imageConversationOwnerKey],
  );
  const imageTransparentBackgroundStorageKey = useMemo(
    () => getScopedStorageKey(IMAGE_TRANSPARENT_BACKGROUND_STORAGE_KEY, imageConversationOwnerKey),
    [imageConversationOwnerKey],
  );
  const imageModelStorageKey = useMemo(
    () => getScopedStorageKey(IMAGE_MODEL_STORAGE_KEY, imageConversationOwnerKey),
    [imageConversationOwnerKey],
  );
  const selectableImageModels = useMemo(
    () => imageModelOptions(defaultImageModel, availableModels),
    [availableModels, defaultImageModel],
  );
  const activeImageModel = useMemo(() => {
    const selected = selectedImageModel.trim();
    if (selected && selectableImageModels.some((model) => model.toLowerCase() === selected.toLowerCase())) {
      return selectableImageModels.find((model) => model.toLowerCase() === selected.toLowerCase()) || selected;
    }
    return selectableImageModels[0] || "";
  }, [selectableImageModels, selectedImageModel]);
  const activeImageQuotaCost = useMemo(
    () => quotaCostForModel(modelQuotaCosts, activeImageModel),
    [activeImageModel, modelQuotaCosts],
  );
  const promptPolishQuotaCost = useMemo(
    () => quotaCostForModel(modelQuotaCosts, defaultImagePromptPolishModel),
    [defaultImagePromptPolishModel, modelQuotaCosts],
  );
  const promptPolishQuotaCostLabel = formatQuotaCost(promptPolishQuotaCost);
  const parsedCount = useMemo(() => Math.max(1, Math.min(10, Number(imageCount) || 1)), [imageCount]);
  const selectedConversation = useMemo(
    () => conversations.find((item) => item.id === selectedConversationId) ?? null,
    [conversations, selectedConversationId],
  );
  const filteredConversations = useMemo(
    () => conversations.filter((conversation) => conversationMatchesQuery(conversation, workspaceSearch)),
    [conversations, workspaceSearch],
  );
  const workspaceStats = useMemo(() => getWorkspaceStats(conversations), [conversations]);
  const deleteConfirmTitle = deleteConfirm?.type === "all" ? "清空历史记录" : deleteConfirm?.type === "one" ? "删除对话" : "";
  const deleteConfirmDescription =
    deleteConfirm?.type === "all"
      ? "确认删除全部图片历史记录吗？删除后无法恢复。"
      : deleteConfirm?.type === "one"
        ? "确认删除这条图片对话吗？删除后无法恢复。"
        : "";

  useEffect(() => {
    conversationsRef.current = conversations;
  }, [conversations]);

  useEffect(() => {
    let cancelled = false;
    const loadModels = async () => {
      try {
        const modelsPayload = await fetchAvailableModels();
        if (!cancelled) {
          setAvailableModels(modelsPayload.data.map((item) => item.id).filter(Boolean));
          setImageModelResolutions(
            Object.fromEntries(
              modelsPayload.data.map((item) => [
                item.id.toLowerCase(),
                Array.isArray(item.image_resolutions) ? item.image_resolutions : ["1k", "2k", "4k"],
              ]),
            ),
          );
          setModelQuotaCosts(buildModelQuotaCosts(modelsPayload.data));
        }
        try {
          const costsPayload = await fetchModelQuotaCosts();
          if (!cancelled) {
            setModelQuotaCosts((current) => ({
              ...current,
              ...normalizeModelQuotaCostMap(costsPayload.costs),
            }));
          }
        } catch {
          // Keep quota costs returned by /v1/models for older deployments.
        }
      } catch {
        if (!cancelled) {
          setAvailableModels([]);
          setModelQuotaCosts({});
          setImageModelResolutions({});
        }
      }
    };
    void loadModels();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const supported = imageModelResolutions[activeImageModel.toLowerCase()];
    if (imageResolution !== "auto" && supported && !supported.includes(imageResolution)) {
      setImageResolution("auto");
    }
  }, [activeImageModel, imageModelResolutions, imageResolution]);

  useEffect(() => {
    let cancelled = false;
    void fetchBackgroundTaskStats()
      .then((payload) => {
        if (!cancelled) {
          setTaskConcurrency(Math.max(1, Number(payload.stats.concurrency) || 1));
        }
      })
      .catch(() => {
        // The backend remains authoritative; one local worker is the safe fallback.
      });
    return () => {
      cancelled = true;
    };
  }, [imageConversationOwnerKey]);

  useEffect(() => {
    let cancelled = false;

    const isConversationQueueActive = (conversationId: string) =>
      Array.from(activeImageTurnQueueIds).some((key) =>
        key.startsWith(`${imageConversationOwnerKey}:${conversationId}:`),
      );

    const loadHistory = async ({ resetBeforeLoad = false }: { resetBeforeLoad?: boolean } = {}) => {
      if (resetBeforeLoad) {
        conversationsRef.current = [];
        setIsLoadingHistory(true);
        setConversations([]);
        setSelectedConversationId(null);
      }

      try {
        if (resetBeforeLoad) {
          const storedSize = typeof window !== "undefined" ? window.localStorage.getItem(imageSizeStorageKey) : null;
          const storedResolution = typeof window !== "undefined" ? window.localStorage.getItem(imageResolutionStorageKey) : null;
          const storedQuality = typeof window !== "undefined" ? window.localStorage.getItem(imageQualityStorageKey) : null;
          const storedModeration =
            typeof window !== "undefined" ? window.localStorage.getItem(imageModerationStorageKey) : null;
          const storedTransparentBackground =
            typeof window !== "undefined" ? window.localStorage.getItem(imageTransparentBackgroundStorageKey) : null;
          const storedImageModel = typeof window !== "undefined" ? window.localStorage.getItem(imageModelStorageKey) : null;
          setImageSize(normalizeImageSize(storedSize));
          setImageResolution(storedResolution || "auto");
          if (storedQuality === "auto" || storedQuality === "low" || storedQuality === "medium" || storedQuality === "high") {
            setImageQuality(storedQuality);
          } else {
            setImageQuality(DEFAULT_IMAGE_QUALITY);
          }
          if (storedModeration === "auto" || storedModeration === "low") {
            setImageModeration(storedModeration);
          } else {
            setImageModeration(DEFAULT_IMAGE_MODERATION);
          }
          setImageTransparentBackground(storedTransparentBackground === "true");
          setSelectedImageModel(storedImageModel || defaultImageModel);
        }

        const items = await listImageConversations(imageConversationOwnerKey);
        const normalizedItems = await recoverConversationHistory(items, imageConversationOwnerKey, {
          isConversationQueueActive,
        });
        if (cancelled) {
          return;
        }

        conversationsRef.current = normalizedItems;
        setConversations(normalizedItems);
        const storedConversationId =
          typeof window !== "undefined" ? window.localStorage.getItem(activeConversationStorageKey) : null;
        setSelectedConversationId((currentConversationId) => {
          if (
            currentConversationId &&
            normalizedItems.some((conversation) => conversation.id === currentConversationId)
          ) {
            return currentConversationId;
          }
          return (
            (storedConversationId && normalizedItems.some((conversation) => conversation.id === storedConversationId)
              ? storedConversationId
              : null) ?? pickFallbackConversationId(normalizedItems)
          );
        });
      } catch (error) {
        const message = error instanceof Error ? error.message : "读取会话记录失败";
        toast.error(message);
      } finally {
        if (!cancelled) {
          setIsLoadingHistory(false);
        }
      }
    };

    const handleConversationsChanged = (event: Event) => {
      const detail = (event as CustomEvent<ImageConversationsChangedDetail>).detail;
      if (detail?.ownerKey !== imageConversationOwnerKey) {
        return;
      }
      void loadHistory();
    };

    window.addEventListener(IMAGE_CONVERSATIONS_CHANGED_EVENT, handleConversationsChanged);
    void loadHistory({ resetBeforeLoad: true });
    return () => {
      cancelled = true;
      window.removeEventListener(IMAGE_CONVERSATIONS_CHANGED_EVENT, handleConversationsChanged);
    };
  }, [
    activeConversationStorageKey,
    defaultImageModel,
    imageConversationOwnerKey,
    imageModelStorageKey,
    imageModerationStorageKey,
    imageQualityStorageKey,
    imageResolutionStorageKey,
    imageSizeStorageKey,
    imageTransparentBackgroundStorageKey,
  ]);

  useEffect(() => {
    if (!selectedConversation) {
      return;
    }

    resultsViewportRef.current?.scrollTo({
      top: resultsViewportRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [selectedConversation?.updatedAt, selectedConversation?.turns.length, selectedConversation]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    if (isLoadingHistory) {
      return;
    }

    if (selectedConversationId) {
      window.localStorage.setItem(activeConversationStorageKey, selectedConversationId);
    } else {
      window.localStorage.removeItem(activeConversationStorageKey);
    }
  }, [activeConversationStorageKey, isLoadingHistory, selectedConversationId]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    if (isLoadingHistory) {
      return;
    }

    if (imageSize) {
      window.localStorage.setItem(imageSizeStorageKey, imageSize);
      return;
    }
    window.localStorage.removeItem(imageSizeStorageKey);
  }, [imageSize, imageSizeStorageKey, isLoadingHistory]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    if (isLoadingHistory) {
      return;
    }

    if (imageResolution && imageResolution !== "auto") {
      window.localStorage.setItem(imageResolutionStorageKey, imageResolution);
      return;
    }
    window.localStorage.removeItem(imageResolutionStorageKey);
  }, [imageResolution, imageResolutionStorageKey, isLoadingHistory]);

  useEffect(() => {
    if (typeof window === "undefined" || isLoadingHistory) {
      return;
    }
    if (imageQuality && imageQuality !== DEFAULT_IMAGE_QUALITY) {
      window.localStorage.setItem(imageQualityStorageKey, imageQuality);
      return;
    }
    window.localStorage.removeItem(imageQualityStorageKey);
  }, [imageQuality, imageQualityStorageKey, isLoadingHistory]);

  useEffect(() => {
    if (typeof window === "undefined" || isLoadingHistory) {
      return;
    }
    if (imageModeration && imageModeration !== DEFAULT_IMAGE_MODERATION) {
      window.localStorage.setItem(imageModerationStorageKey, imageModeration);
      return;
    }
    window.localStorage.removeItem(imageModerationStorageKey);
  }, [imageModeration, imageModerationStorageKey, isLoadingHistory]);

  useEffect(() => {
    if (typeof window === "undefined" || isLoadingHistory) {
      return;
    }
    if (imageTransparentBackground) {
      window.localStorage.setItem(imageTransparentBackgroundStorageKey, "true");
      return;
    }
    window.localStorage.removeItem(imageTransparentBackgroundStorageKey);
  }, [imageTransparentBackground, imageTransparentBackgroundStorageKey, isLoadingHistory]);

  useEffect(() => {
    if (typeof window === "undefined" || isLoadingHistory) {
      return;
    }
    const model = activeImageModel.trim();
    if (model) {
      window.localStorage.setItem(imageModelStorageKey, model);
    }
  }, [activeImageModel, imageModelStorageKey, isLoadingHistory]);

  useEffect(() => {
    if (selectableImageModels.length === 0) {
      return;
    }
    if (!selectedImageModel || !selectableImageModels.some((model) => model.toLowerCase() === selectedImageModel.toLowerCase())) {
      setSelectedImageModel(selectableImageModels[0]);
    }
  }, [selectableImageModels, selectedImageModel]);

  useEffect(() => {
    if (selectedConversationId && !conversations.some((conversation) => conversation.id === selectedConversationId)) {
      const timeout = window.setTimeout(() => {
        setSelectedConversationId(pickFallbackConversationId(conversations));
      }, 0);
      return () => window.clearTimeout(timeout);
    }
  }, [conversations, selectedConversationId]);

  const persistConversation = async (conversation: ImageConversation) => {
    const nextConversations = sortImageConversations([
      conversation,
      ...conversationsRef.current.filter((item) => item.id !== conversation.id),
    ]);
    conversationsRef.current = nextConversations;
    setConversations(nextConversations);
    await saveImageConversation(conversation, imageConversationOwnerKey);
  };

  const updateConversation = useCallback(
    async (
      conversationId: string,
      updater: (current: ImageConversation | null) => ImageConversation,
      options: { persist?: boolean } = {},
    ) => {
      const current = conversationsRef.current.find((item) => item.id === conversationId) ?? null;
      const nextConversation = updater(current);
      const nextConversations = sortImageConversations([
        nextConversation,
        ...conversationsRef.current.filter((item) => item.id !== conversationId),
      ]);
      conversationsRef.current = nextConversations;
      setConversations(nextConversations);
      if (options.persist !== false) {
        await saveImageConversation(nextConversation, imageConversationOwnerKey);
      }
    },
    [imageConversationOwnerKey],
  );

  const clearComposerInputs = useCallback(() => {
    setImagePrompt("");
    setImageCount("1");
    setReferenceImageFiles([]);
    setReferenceImages([]);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  }, []);

  const resetComposer = useCallback(() => {
    setImageMode("generate");
    clearComposerInputs();
  }, [clearComposerInputs]);

  const handleCreateDraft = () => {
    setSelectedConversationId(null);
    resetComposer();
    textareaRef.current?.focus();
  };

  const handleDeleteConversation = async (id: string) => {
    const nextConversations = conversations.filter((item) => item.id !== id);
    conversationsRef.current = nextConversations;
    setConversations(nextConversations);
    if (selectedConversationId === id) {
      setSelectedConversationId(pickFallbackConversationId(nextConversations));
      resetComposer();
    }

    try {
      await deleteImageConversation(id, imageConversationOwnerKey);
    } catch (error) {
      const message = error instanceof Error ? error.message : "删除会话失败";
      toast.error(message);
      const items = await listImageConversations(imageConversationOwnerKey);
      conversationsRef.current = items;
      setConversations(items);
    }
  };

  const handleClearHistory = async () => {
    try {
      await clearImageConversations(imageConversationOwnerKey);
      conversationsRef.current = [];
      setConversations([]);
      setSelectedConversationId(null);
      resetComposer();
      toast.success("已清空历史记录");
    } catch (error) {
      const message = error instanceof Error ? error.message : "清空历史记录失败";
      toast.error(message);
    }
  };

  const openDeleteConversationConfirm = (id: string) => {
    setIsHistoryOpen(false);
    setDeleteConfirm({ type: "one", id });
  };

  const openClearHistoryConfirm = () => {
    setIsHistoryOpen(false);
    setDeleteConfirm({ type: "all" });
  };

  const handleConfirmDelete = async () => {
    const target = deleteConfirm;
    setDeleteConfirm(null);
    if (!target) {
      return;
    }
    if (target.type === "all") {
      await handleClearHistory();
      return;
    }
    await handleDeleteConversation(target.id);
  };

  const appendReferenceImages = useCallback(async (files: File[]) => {
    if (files.length === 0) {
      return;
    }

    try {
      const previews = await Promise.all(
        files.map(async (file) => ({
          name: file.name,
          type: file.type || "image/png",
          dataUrl: await readFileAsDataUrl(file),
        })),
      );

      setReferenceImageFiles((prev) => [...prev, ...files]);
      setReferenceImages((prev) => [...prev, ...previews]);
      setImageMode("edit");
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "读取参考图失败";
      toast.error(message);
    }
  }, []);

  const handleReferenceImageChange = useCallback(
    async (files: File[]) => {
      if (files.length === 0) {
        return;
      }

      await appendReferenceImages(files);
    },
    [appendReferenceImages],
  );

  const handleRemoveReferenceImage = useCallback((index: number) => {
    setReferenceImageFiles((prev) => {
      const next = prev.filter((_, currentIndex) => currentIndex !== index);
      if (next.length === 0 && fileInputRef.current) {
        fileInputRef.current.value = "";
      }
      return next;
    });
    setReferenceImages((prev) => prev.filter((_, currentIndex) => currentIndex !== index));
  }, []);

  const handleCreateAnnotatedReferenceImage = useCallback(
    async (_sourceIndex: number, result: AnnotationEditResult) => {
      const nextReferenceImage: StoredReferenceImage = {
        name: result.file.name,
        type: result.file.type || "image/png",
        dataUrl: result.dataUrl,
      };

      setImageMode("edit");
      setReferenceImageFiles((prev) => [...prev, result.file]);
      setReferenceImages((prev) => [...prev, nextReferenceImage]);
      if (result.insertInstruction) {
        setImagePrompt((currentPrompt) => {
          const cleanedPrompt = currentPrompt.trim();
          return cleanedPrompt ? `${cleanedPrompt}\n\n${result.instruction}` : result.instruction;
        });
      }
      window.requestAnimationFrame(() => textareaRef.current?.focus());
    },
    [],
  );

  const handleContinueEdit = useCallback(
    async (conversationId: string, image: StoredImage | StoredReferenceImage) => {
      try {
        const preparedReference =
          "dataUrl" in image
            ? {
                referenceImage: image,
                file: dataUrlToFile(image.dataUrl, image.name, image.type),
              }
            : await buildReferenceImageFromResult(image, `conversation-${conversationId}-${Date.now()}.png`);
        if (!preparedReference) {
          toast.error("这张图没有可用于继续编辑的数据");
          return;
        }

        setSelectedConversationId(conversationId);
        setImageMode("edit");
        setReferenceImages((prev) => [...prev, preparedReference.referenceImage]);
        setReferenceImageFiles((prev) => [...prev, preparedReference.file]);
        setImagePrompt("");
        textareaRef.current?.focus();
      } catch (error) {
        const message = error instanceof Error ? error.message : "读取生成图失败";
        toast.error(message);
      }
    },
    [],
  );

  const openLightbox = useCallback((images: ImageLightboxItem[], index: number) => {
    if (images.length === 0) {
      return;
    }

    setLightboxImages(images);
    setLightboxIndex(Math.max(0, Math.min(index, images.length - 1)));
    setLightboxOpen(true);
  }, []);

  const runConversationQueue = useCallback(
    async (conversationId: string, requestedTurnId?: string) => {
      const ownerPrefix = `${imageConversationOwnerKey}:`;
      const activeCount = Array.from(activeImageTurnQueueIds).filter((key) => key.startsWith(ownerPrefix)).length;
      if (activeCount >= taskConcurrency) {
        return;
      }

      const snapshot = conversationsRef.current.find((conversation) => conversation.id === conversationId);
      const queuedTurn = snapshot?.turns.find(
        (turn) => turn.status === "queued" && (!requestedTurnId || turn.id === requestedTurnId),
      );
      if (!snapshot || !queuedTurn) {
        return;
      }

      const queueId = `${imageConversationOwnerKey}:${conversationId}:${queuedTurn.id}`;
      if (activeImageTurnQueueIds.has(queueId)) {
        return;
      }
      activeImageTurnQueueIds.add(queueId);
      try {
        await updateConversation(conversationId, (current) => {
          const conversation = current ?? snapshot;
          return {
            ...conversation,
            updatedAt: new Date().toISOString(),
            turns: conversation.turns.map((turn) =>
              turn.id === queuedTurn.id
                ? {
                    ...turn,
                    status: "generating",
                    error: undefined,
                  }
                : turn,
            ),
          };
        });

        const referenceFiles = queuedTurn.referenceImages.map((image, index) =>
          dataUrlToFile(image.dataUrl, image.name || `${queuedTurn.id}-${index + 1}.png`, image.type),
        );
        const pendingImages = queuedTurn.images.filter((image) => image.status === "loading");

        if (queuedTurn.mode === "edit" && referenceFiles.length === 0) {
          throw new Error("未找到可用于继续编辑的参考图");
        }

        if (pendingImages.length === 0) {
          const existingFailedCount = queuedTurn.images.filter((image) => image.status === "error").length;
          const existingSuccessCount = queuedTurn.images.filter((image) => image.status === "success").length;
          await updateConversation(conversationId, (current) => {
            const conversation = current ?? snapshot;
            return {
              ...conversation,
              updatedAt: new Date().toISOString(),
              turns: conversation.turns.map((turn) =>
                turn.id === queuedTurn.id
                  ? {
                      ...turn,
                      status: existingFailedCount > 0 ? "error" : existingSuccessCount > 0 ? "success" : "queued",
                      error: existingFailedCount > 0 ? `其中 ${existingFailedCount} 张未成功生成` : undefined,
                    }
                  : turn,
              ),
            };
          });
          return;
        }

        let resumedSuccessCount = 0;
        let resumedFailedCount = 0;
        const resumedFailureMessages: string[] = [];

        for (const pendingImage of pendingImages) {
          const requestId = pendingImage.requestId || createId();
          if (!pendingImage.requestId) {
            await updateConversation(conversationId, (current) => {
              const conversation = current ?? snapshot;
              return {
                ...conversation,
                updatedAt: new Date().toISOString(),
                turns: conversation.turns.map((turn) =>
                  turn.id === queuedTurn.id
                    ? {
                        ...turn,
                        images: turn.images.map((image) =>
                          image.id === pendingImage.id ? { ...image, requestId } : image,
                        ),
                      }
                    : turn,
                ),
              };
            });
          }

          try {
            const recoveredData = await fetchGeneratedImageByRequestId(requestId, session.role);
            const data =
              recoveredData ??
              (await waitForBackgroundTaskResult<ImageResponse>(
                queuedTurn.mode === "edit"
                  ? await createImageEditTask(
                      referenceFiles,
                      queuedTurn.prompt,
                      queuedTurn.model,
                      buildImageRequestOptions(queuedTurn),
                      requestId,
                    )
                  : await createImageGenerationTask(
                      queuedTurn.prompt,
                      queuedTurn.model,
                      buildImageRequestOptions(queuedTurn),
                      requestId,
                    ),
              ));
            const first = data.data?.[0];
            if (!first?.b64_json && !first?.url) {
              throw new Error("未返回图片数据");
            }

            const nextImage: StoredImage = first.url
              ? {
                  id: pendingImage.id,
                  status: "success",
                  url: first.url,
                  requestId,
                }
              : {
                  id: pendingImage.id,
                  status: "success",
                  b64_json: first.b64_json,
                  requestId,
                };

            await updateConversation(
              conversationId,
              (current) => {
                const conversation = current ?? snapshot;
                return {
                  ...conversation,
                  updatedAt: new Date().toISOString(),
                  turns: conversation.turns.map((turn) =>
                    turn.id === queuedTurn.id
                      ? {
                          ...turn,
                          images: turn.images.map((image) => (image.id === nextImage.id ? nextImage : image)),
                        }
                      : turn,
                  ),
                };
              },
              { persist: false },
            );

            resumedSuccessCount += 1;
          } catch (error) {
            const message = error instanceof Error ? error.message : "生成失败";
            const failedImage: StoredImage = {
              id: pendingImage.id,
              status: "error",
              error: message,
              requestId,
            };

            await updateConversation(
              conversationId,
              (current) => {
                const conversation = current ?? snapshot;
                return {
                  ...conversation,
                  updatedAt: new Date().toISOString(),
                  turns: conversation.turns.map((turn) =>
                    turn.id === queuedTurn.id
                      ? {
                          ...turn,
                          images: turn.images.map((image) => (image.id === failedImage.id ? failedImage : image)),
                        }
                      : turn,
                  ),
                };
              },
              { persist: false },
            );

            resumedFailedCount += 1;
            resumedFailureMessages.push(message);
          }
        }
        const existingSuccessCount = queuedTurn.images.filter((image) => image.status === "success").length;
        const existingFailedCount = queuedTurn.images.filter((image) => image.status === "error").length;
        const successCount = existingSuccessCount + resumedSuccessCount;
        const failedCount = existingFailedCount + resumedFailedCount;
        const existingFailureMessages = queuedTurn.images
          .filter((image) => image.status === "error" && image.error)
          .map((image) => image.error as string);
        const failureMessages = [...existingFailureMessages, ...resumedFailureMessages];
        const failureMessage =
          failedCount === 1 && failureMessages[0]
            ? failureMessages[0]
            : failedCount > 0
              ? `其中 ${failedCount} 张未成功生成`
              : undefined;

        await updateConversation(conversationId, (current) => {
          const conversation = current ?? snapshot;
          return {
            ...conversation,
            updatedAt: new Date().toISOString(),
            turns: conversation.turns.map((turn) =>
              turn.id === queuedTurn.id
                ? {
                    ...turn,
                    status: failedCount > 0 ? "error" : "success",
                    error: failureMessage,
                  }
                : turn,
            ),
          };
        });

        if (failureMessage) {
          toast.error(failureMessage);
        }

        window.dispatchEvent(new Event(QUOTA_REFRESH_EVENT));
      } catch (error) {
        const message = error instanceof Error ? error.message : "生成图片失败";
        await updateConversation(conversationId, (current) => {
          const conversation = current ?? snapshot;
          return {
            ...conversation,
            updatedAt: new Date().toISOString(),
            turns: conversation.turns.map((turn) =>
              turn.id === queuedTurn.id
                ? {
                    ...turn,
                    status: "error",
                    error: message,
                    images: turn.images.map((image) =>
                      image.status === "loading" ? { ...image, status: "error", error: message } : image,
                    ),
                  }
                : turn,
            ),
          };
        });
        toast.error(message);
      } finally {
        activeImageTurnQueueIds.delete(queueId);
        setQueueTick((current) => current + 1);
      }
    },
    [imageConversationOwnerKey, session.role, taskConcurrency, updateConversation],
  );

  useEffect(() => {
    const ownerPrefix = `${imageConversationOwnerKey}:`;
    const activeCount = Array.from(activeImageTurnQueueIds).filter((key) => key.startsWith(ownerPrefix)).length;
    const availableSlots = Math.max(0, taskConcurrency - activeCount);
    const queuedTurns = conversations.flatMap((conversation) =>
      conversation.turns
        .filter(
          (turn) =>
            turn.status === "queued" &&
            !activeImageTurnQueueIds.has(`${imageConversationOwnerKey}:${conversation.id}:${turn.id}`),
        )
        .map((turn) => ({ conversationId: conversation.id, turnId: turn.id })),
    );
    for (const item of queuedTurns.slice(0, availableSlots)) {
      void runConversationQueue(item.conversationId, item.turnId);
    }
  }, [conversations, imageConversationOwnerKey, queueTick, runConversationQueue, taskConcurrency]);

  const handleSubmit = async () => {
    const prompt = imagePrompt.trim();
    if (!prompt) {
      toast.error("请输入提示词");
      return;
    }
    if (!activeImageModel) {
      toast.error("没有可用的图片模型，请先启用支持图片生成的渠道");
      return;
    }

    if (imageMode === "edit" && referenceImageFiles.length === 0) {
      toast.error("请先上传参考图");
      return;
    }

    const targetConversation = selectedConversationId
      ? conversationsRef.current.find((conversation) => conversation.id === selectedConversationId) ?? null
      : null;
    const now = new Date().toISOString();
    const conversationId = targetConversation?.id ?? createId();
    const turnId = createId();
    const draftTurn: ImageTurn = {
      id: turnId,
      prompt,
      model: activeImageModel,
      mode: imageMode,
      referenceImages: imageMode === "edit" ? referenceImages : [],
      count: parsedCount,
      size: imageSize,
      resolution: imageResolution,
      quality: imageQuality,
      outputFormat: "png",
      outputCompression: null,
      moderation: imageModeration,
      transparentBackground: imageTransparentBackground,
      images: Array.from({ length: parsedCount }, (_, index) => ({
        id: `${turnId}-${index}`,
        status: "loading" as const,
        requestId: createId(),
      })),
      createdAt: now,
      status: "queued",
    };

    const baseConversation: ImageConversation = targetConversation
      ? {
          ...targetConversation,
          ownerKey: imageConversationOwnerKey,
          updatedAt: now,
          turns: [...targetConversation.turns, draftTurn],
        }
      : {
          id: conversationId,
          ownerKey: imageConversationOwnerKey,
          title: buildConversationTitle(prompt),
          createdAt: now,
          updatedAt: now,
          turns: [draftTurn],
        };

    setSelectedConversationId(conversationId);
    clearComposerInputs();

    await persistConversation(baseConversation);
    void runConversationQueue(conversationId);

    const targetStats = getImageConversationStats(baseConversation);
    if (targetStats.running > 0 || targetStats.queued > 1) {
      toast.success("已加入当前对话队列");
    }
  };

  const handlePolishPrompt = async () => {
    const prompt = imagePrompt.trim();
    if (!prompt) {
      toast.error("请输入提示词");
      return;
    }
    if (isPolishingPrompt) {
      return;
    }

    setIsPolishingPrompt(true);
    try {
      const polished = await polishImagePrompt(prompt, imageMode, defaultImagePromptPolishModel);
      setImagePrompt(polished);
      window.dispatchEvent(new Event(QUOTA_REFRESH_EVENT));
      window.requestAnimationFrame(() => textareaRef.current?.focus());
      toast.success(`提示词已润色，已扣除 ${promptPolishQuotaCostLabel} 点额度`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "AI 润色失败");
    } finally {
      setIsPolishingPrompt(false);
    }
  };

  const handleRegenerateTurn = async (conversationId: string, turn: ImageTurn) => {
    const targetConversation = conversationsRef.current.find((conversation) => conversation.id === conversationId);
    if (!targetConversation) {
      toast.error("未找到要重新生成的会话");
      return;
    }

    if (turn.status === "queued" || turn.status === "generating") {
      toast.error("当前任务仍在处理中");
      return;
    }

    const now = new Date().toISOString();
    const turnId = createId();
    const draftTurn: ImageTurn = {
      id: turnId,
      prompt: turn.prompt,
      model: turn.model,
      mode: turn.mode,
      referenceImages: turn.mode === "edit" ? turn.referenceImages : [],
      count: turn.count,
      size: turn.size,
      resolution: turn.resolution,
      quality: turn.quality,
      outputFormat: "png",
      outputCompression: null,
      moderation: turn.moderation,
      transparentBackground: turn.transparentBackground,
      images: Array.from({ length: Math.max(1, turn.count) }, (_, index) => ({
        id: `${turnId}-${index}`,
        status: "loading" as const,
        requestId: createId(),
      })),
      createdAt: now,
      status: "queued",
    };

    const nextConversation: ImageConversation = {
      ...targetConversation,
      ownerKey: imageConversationOwnerKey,
      updatedAt: now,
      turns: [...targetConversation.turns, draftTurn],
    };

    setSelectedConversationId(conversationId);
    await persistConversation(nextConversation);
    void runConversationQueue(conversationId);
  };

  const handleDeleteTurn = async (conversationId: string, turnId: string) => {
    const targetConversation = conversationsRef.current.find((conversation) => conversation.id === conversationId);
    const targetTurn = targetConversation?.turns.find((turn) => turn.id === turnId);
    if (!targetConversation || !targetTurn) {
      return;
    }
    if (targetTurn.status === "queued" || targetTurn.status === "generating") {
      toast.error("当前任务仍在处理中");
      return;
    }

    const nextTurns = targetConversation.turns.filter((turn) => turn.id !== turnId);
    if (nextTurns.length === 0) {
      await handleDeleteConversation(conversationId);
      toast.success("已删除");
      return;
    }

    await updateConversation(conversationId, (current) => {
      const conversation = current ?? targetConversation;
      return {
        ...conversation,
        updatedAt: new Date().toISOString(),
        turns: conversation.turns.filter((turn) => turn.id !== turnId),
      };
    });
    toast.success("已删除");
  };

  return (
    <>
      <section className="grid h-full min-h-0 w-full min-w-0 grid-cols-1 gap-3 overflow-y-auto lg:grid-cols-[280px_minmax(0,1fr)] lg:overflow-hidden">
        <div className="hidden min-h-0 overflow-hidden rounded-xl border border-white/80 bg-white/88 shadow-[0_20px_70px_-45px_rgba(15,23,42,0.45)] backdrop-blur-xl lg:flex">
          <ImageStudioSidebar
            conversations={filteredConversations}
            isLoadingHistory={isLoadingHistory}
            selectedConversationId={selectedConversationId}
            searchValue={workspaceSearch}
            onSearchChange={setWorkspaceSearch}
            workspaceStats={workspaceStats}
            onCreateDraft={handleCreateDraft}
            onClearHistory={openClearHistoryConfirm}
            onSelectConversation={setSelectedConversationId}
            onDeleteConversation={openDeleteConversationConfirm}
            formatConversationTime={formatConversationTime}
          />
        </div>

        <Dialog open={isHistoryOpen} onOpenChange={setIsHistoryOpen}>
          <DialogContent className="flex h-[88vh] w-[92vw] max-w-[430px] flex-col overflow-hidden rounded-lg p-0">
            <DialogTitle className="sr-only">历史记录</DialogTitle>
            <ImageStudioSidebar
              conversations={filteredConversations}
              isLoadingHistory={isLoadingHistory}
              selectedConversationId={selectedConversationId}
              searchValue={workspaceSearch}
              onSearchChange={setWorkspaceSearch}
              workspaceStats={workspaceStats}
              onCreateDraft={() => {
                handleCreateDraft();
                setIsHistoryOpen(false);
              }}
              onClearHistory={openClearHistoryConfirm}
              onSelectConversation={(id) => {
                setSelectedConversationId(id);
                setIsHistoryOpen(false);
              }}
              onDeleteConversation={openDeleteConversationConfirm}
              formatConversationTime={formatConversationTime}
            />
          </DialogContent>
        </Dialog>

        <div className="flex min-h-0 min-w-0 flex-col gap-3 overflow-hidden">
          <div className="flex items-center justify-between gap-2 lg:hidden">
            <Button
              variant="outline"
              className="h-10 flex-1 rounded-lg border-stone-100 bg-white/75 text-stone-700 shadow-sm"
              onClick={() => setIsHistoryOpen(true)}
            >
              <Menu className="mr-2 size-4" />
              历史记录 ({conversations.length})
            </Button>
            <Button className="h-10 rounded-lg text-white shadow-sm" onClick={handleCreateDraft}>
              <Plus className="size-4" />
              新建
            </Button>
            <Button
              variant="outline"
              className="h-10 rounded-lg border-stone-100 bg-white/75 px-3 text-stone-600 shadow-sm"
              onClick={openClearHistoryConfirm}
              disabled={conversations.length === 0}
            >
              <Trash2 className="size-4" />
            </Button>
          </div>

          <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl">
            <div
              ref={resultsViewportRef}
              className="min-h-0 flex-1 overflow-y-auto px-3 py-3 pb-72 [scrollbar-color:rgba(148,163,184,.45)_transparent] [scrollbar-width:thin] sm:px-5 sm:pb-80 [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-stone-300/65 [&::-webkit-scrollbar-track]:bg-transparent"
            >
              <div className="mx-auto w-full max-w-6xl">
                <ImageResults
                  selectedConversation={selectedConversation}
                  onOpenLightbox={openLightbox}
                  onContinueEdit={handleContinueEdit}
                  onRegenerate={handleRegenerateTurn}
                  onDeleteTurn={handleDeleteTurn}
                  formatConversationTime={formatConversationTime}
                />
              </div>
            </div>

            <div className="pointer-events-none absolute inset-x-0 bottom-4 z-10 px-3 sm:px-6 lg:px-10">
              <div className="pointer-events-auto mx-auto max-w-5xl">
                <ImageComposer
                  mode={imageMode}
                  prompt={imagePrompt}
                  imageCount={imageCount}
                  imageSize={imageSize}
                  imageResolution={imageResolution}
                  imageQuality={imageQuality}
                  imageModeration={imageModeration}
                  imageTransparentBackground={imageTransparentBackground}
                  selectedImageModel={activeImageModel}
                  selectedImageQuotaCost={activeImageQuotaCost}
                  imageModelQuotaCosts={modelQuotaCosts}
                  promptPolishQuotaCost={promptPolishQuotaCost}
                  supportedImageResolutions={
                    imageModelResolutions[activeImageModel.toLowerCase()] ?? ["1k", "2k", "4k"]
                  }
                  imageModelOptions={selectableImageModels}
                  referenceImages={referenceImages}
                  textareaRef={textareaRef}
                  fileInputRef={fileInputRef}
                  onModeChange={setImageMode}
                  onPromptChange={setImagePrompt}
                  onImageCountChange={setImageCount}
                  onImageSizeChange={(value) => setImageSize(normalizeImageSize(value))}
                  onImageResolutionChange={setImageResolution}
                  onImageQualityChange={setImageQuality}
                  onImageModerationChange={setImageModeration}
                  onImageTransparentBackgroundChange={setImageTransparentBackground}
                  onImageModelChange={setSelectedImageModel}
                  onSubmit={handleSubmit}
                  onPolishPrompt={handlePolishPrompt}
                  isPolishingPrompt={isPolishingPrompt}
                  onPickReferenceImage={() => fileInputRef.current?.click()}
                  onReferenceImageChange={handleReferenceImageChange}
                  onRemoveReferenceImage={handleRemoveReferenceImage}
                  onCreateAnnotatedReferenceImage={handleCreateAnnotatedReferenceImage}
                />
              </div>
            </div>
          </div>
        </div>
      </section>

      <ImageLightbox
        images={lightboxImages}
        currentIndex={lightboxIndex}
        open={lightboxOpen}
        onOpenChange={setLightboxOpen}
        onIndexChange={setLightboxIndex}
      />

      {deleteConfirm ? (
        <Dialog open onOpenChange={(open) => (!open ? setDeleteConfirm(null) : null)}>
          <DialogContent showCloseButton={false} className="rounded-lg p-6">
            <DialogHeader className="gap-2">
              <DialogTitle>{deleteConfirmTitle}</DialogTitle>
              <DialogDescription className="text-sm leading-6">
                {deleteConfirmDescription}
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button variant="outline" onClick={() => setDeleteConfirm(null)}>
                取消
              </Button>
              <Button className="bg-neutral-900 text-white hover:bg-black" onClick={() => void handleConfirmDelete()}>
                确认删除
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      ) : null}
    </>
  );
}

function ImageStudioSidebar({
  conversations,
  isLoadingHistory,
  selectedConversationId,
  searchValue,
  onSearchChange,
  workspaceStats,
  onCreateDraft,
  onClearHistory,
  onSelectConversation,
  onDeleteConversation,
  formatConversationTime,
}: {
  conversations: ImageConversation[];
  isLoadingHistory: boolean;
  selectedConversationId: string | null;
  searchValue: string;
  onSearchChange: (value: string) => void;
  workspaceStats: ReturnType<typeof getWorkspaceStats>;
  onCreateDraft: () => void;
  onClearHistory: () => void | Promise<void>;
  onSelectConversation: (id: string) => void;
  onDeleteConversation: (id: string) => void | Promise<void>;
  formatConversationTime: (value: string) => string;
}) {
  return (
    <aside className="flex h-full min-h-0 w-full flex-col bg-white/32">
      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3 [scrollbar-color:rgba(115,115,115,.45)_transparent] [scrollbar-width:thin] [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-stone-300/55 [&::-webkit-scrollbar-track]:bg-transparent">
        <div className="min-h-[320px]">
          <div className="mb-3 flex items-center justify-between gap-2">
            <div>
              <div className="text-xs font-bold text-stone-500">最近会话</div>
              <div className="mt-1 text-[11px] text-stone-400">{conversations.length} 条记录</div>
            </div>
          </div>
          <ImageSidebar
            conversations={conversations}
            isLoadingHistory={isLoadingHistory}
            selectedConversationId={selectedConversationId}
            searchValue={searchValue}
            onSearchChange={onSearchChange}
            searchPlaceholder="搜索作品、提示词、会话"
            onCreateDraft={onCreateDraft}
            onClearHistory={onClearHistory}
            onSelectConversation={onSelectConversation}
            onDeleteConversation={onDeleteConversation}
            formatConversationTime={formatConversationTime}
          />
        </div>
      </div>

      <div className="border-t border-stone-100/70 p-3">
        <div className="grid grid-cols-2 gap-2">
          <SidebarMetric label="今日生成" value={workspaceStats.todayGenerated} />
          <SidebarMetric label="成功率" value={workspaceStats.successRate} />
          <SidebarMetric label="处理中" value={workspaceStats.active} />
          <SidebarMetric label="历史作品" value={workspaceStats.successImages} />
        </div>
      </div>
    </aside>
  );
}

function SidebarMetric({
  label,
  value,
  details = [],
  prominent = false,
  className,
}: {
  label: string;
  value: string | number;
  details?: string[];
  prominent?: boolean;
  className?: string;
}) {
  const visibleDetails = details.filter(Boolean);

  return (
    <div className={cn("rounded-lg bg-gradient-to-br from-white/82 to-stone-50/82 p-2.5", className)}>
      {prominent && visibleDetails.length > 0 ? (
        <div className="grid grid-cols-[minmax(64px,auto)_minmax(0,1fr)] items-center gap-3">
          <div className="min-w-0">
            <div className="text-sm font-medium text-stone-500">{label}</div>
            <div className="mt-0.5 truncate text-3xl font-bold tracking-tight text-stone-950">{value}</div>
          </div>
          <div className="min-w-0 space-y-1 text-right">
            {visibleDetails.map((detail) => (
              <div key={detail} title={detail} className="truncate text-xs leading-4 text-stone-400">
                {detail}
              </div>
            ))}
          </div>
        </div>
      ) : (
        <>
          <div className={cn("font-medium text-stone-500", prominent ? "text-sm" : "text-[11px]")}>{label}</div>
          <div
            className={cn(
              "mt-1 truncate font-bold tracking-tight text-stone-950",
              prominent ? "text-3xl" : "text-lg",
            )}
          >
            {value}
          </div>
          {visibleDetails.map((detail) => (
            <div key={detail} className="mt-1 text-xs text-stone-400">
              {detail}
            </div>
          ))}
        </>
      )}
    </div>
  );
}

export default function ImagePage() {
  const { isCheckingAuth, session } = useAuthGuard();

  if (isCheckingAuth || !session) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <LoaderCircle className="size-5 animate-spin text-stone-400" />
      </div>
    );
  }

  return <ImagePageContent session={session} />;
}
