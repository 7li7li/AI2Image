import { httpRequest } from "@/lib/request";
import webConfig from "@/constants/common-env";
import { getStoredAuthKey } from "@/store/auth";

export type ImageModel = string;
export type AuthRole = "admin" | "user";

export type SettingsConfig = {
  proxy: string;
  site_title?: string;
  site_icon?: string;
  site_background?: string;
  base_url?: string;
  default_image_model?: string;
  default_text_model?: string;
  image_retention_days?: number | string;
  background_task_max_workers?: number | string;
  background_task_queue_limit?: number | string;
  background_task_user_limit?: number | string;
  log_levels?: string[];
  allow_user_registration?: boolean;
  email_verification_enabled?: boolean;
  email_domain_whitelist_enabled?: boolean;
  email_domain_whitelist?: string[] | string;
  new_user_initial_quota?: number | string;
  new_user_quota_valid_days?: number | string;
  smtp_host?: string;
  smtp_port?: number | string;
  smtp_username?: string;
  smtp_password?: string;
  smtp_password_set?: boolean;
  smtp_from_email?: string;
  smtp_use_ssl?: boolean;
  smtp_use_starttls?: boolean;
  smtp_force_auth_login?: boolean;
  [key: string]: unknown;
};

export type PublicSiteSettings = {
  site_title: string;
  site_icon: string;
  site_background: string;
  default_image_model: string;
  default_text_model: string;
};

export type PublicAuthSettings = {
  allow_user_registration: boolean;
  email_verification_enabled: boolean;
  email_domain_whitelist_enabled: boolean;
  email_domain_whitelist: string[];
};

export type ManagedImage = {
  id?: string;
  record_id?: string;
  name: string;
  date: string;
  size: number;
  url: string;
  created_at: string;
  owner_user_id?: string;
  owner_name?: string;
  owner_email?: string;
  prompt?: string;
  mode?: string;
  model?: string;
  image_size?: string;
  channel?: string;
  request_id?: string;
  quota_cost?: number;
  webdav_url?: string;
  webdav_synced_at?: string;
  webdav_status?: string;
};

export type ManagedImageDeleteTarget = {
  id?: string;
  record_id?: string;
  url: string;
};

export type ImageListPagination = {
  page: number;
  page_size: number;
  total: number;
  page_count: number;
};

export type ImageListResponse = {
  items: ManagedImage[];
  groups: Array<{ date: string; items: ManagedImage[] }>;
  pagination: ImageListPagination;
};

export type ImageWebDAVConfig = {
  enabled: boolean;
  url: string;
  username: string;
  root_path: string;
  password_set: boolean;
  last_sync_at?: string | null;
  last_sync_result?: {
    total?: number;
    uploaded?: number;
    skipped?: number;
    failed?: number;
  } | null;
};

export type ImageWebDAVConfigPayload = {
  enabled: boolean;
  url: string;
  username: string;
  password?: string;
  root_path: string;
};

export type ImageWebDAVSyncResult = {
  scope: "admin" | "user" | string;
  total: number;
  uploaded: number;
  skipped: number;
  failed: number;
  bytes: number;
  errors: Array<{ id?: string; name?: string; error: string }>;
};

export type PromptLibraryItem = {
  id: string;
  title: string;
  description?: string;
  preview?: string;
  reference_image_urls?: string[];
  prompt: string;
  author?: string;
  link?: string;
  mode?: "generate" | "edit" | string;
  image_size?: string;
  image_count?: string;
  icon?: string;
  quick_access?: boolean;
  sort_order?: number;
  category?: string;
  sub_category?: string;
  created?: string;
  updated_at?: string;
  status?: "public" | "personal" | "submitted" | "rejected" | "shared" | string;
  owner_id?: string;
  owner_name?: string;
  owner_email?: string;
  owner_role?: string;
  source_prompt_id?: string;
  imported_from_share_id?: string;
  submitted_at?: string;
  reviewed_at?: string;
  reviewed_by?: string;
  reviewed_by_name?: string;
  rejected_at?: string;
  rejection_reason?: string;
  share_id?: string;
  shared_at?: string;
};

export type PromptLibraryPayload = {
  title: string;
  description?: string;
  preview?: string;
  reference_image_urls?: string[];
  prompt: string;
  author?: string;
  link?: string;
  mode?: "generate" | "edit" | string;
  image_size?: string;
  image_count?: string;
  icon?: string;
  quick_access?: boolean;
  sort_order?: number | null;
  category?: string;
  sub_category?: string;
  source_prompt_id?: string;
};

type PromptLibraryResponse = {
  items: PromptLibraryItem[];
  prompts: PromptLibraryItem[];
  prompt_count: number;
};

export type SystemLog = {
  time: string;
  type: "call" | "audit" | string;
  summary?: string;
  detail?: Record<string, unknown>;
  [key: string]: unknown;
};

export type LogListResponse = {
  items: SystemLog[];
  total: number;
  page: number;
  page_size: number;
  page_count: number;
};

export type ImageResponse = {
  created: number;
  data: Array<{ b64_json?: string; url?: string; revised_prompt?: string }>;
};

export type ChatRole = "system" | "user" | "assistant";

export type ChatTextContentPart = {
  type: "text";
  text: string;
};

export type ChatImageContentPart = {
  type: "image_url";
  image_url: {
    url: string;
    detail?: "auto" | "low" | "high";
  };
};

export type ChatCompletionContent = string | Array<ChatTextContentPart | ChatImageContentPart>;

export type ChatCompletionMessage = {
  role: ChatRole;
  content: ChatCompletionContent;
};

export type ChatCompletionResponse = {
  id: string;
  object: string;
  created: number;
  model: string;
  channel?: string;
  choices: Array<{
    index: number;
    message: {
      role: ChatRole | string;
      content: unknown;
    };
    finish_reason?: string | null;
  }>;
  usage?: Record<string, unknown>;
};

export type ChatStreamEvent =
  | { type: "meta"; model?: string; channel?: string; request_id?: string }
  | { type: "delta"; content: string; request_id?: string }
  | { type: "done"; model?: string; channel?: string; request_id?: string }
  | { type: "error"; error: string; request_id?: string };

export type ModelListItem = {
  id: string;
  object?: string;
  created?: number;
  owned_by?: string;
};

export type ModelListResponse = {
  object: string;
  data: ModelListItem[];
};

export type BackgroundTaskStatus<T = unknown> = {
  id: string;
  task_id: string;
  request_id: string;
  kind: string;
  status: "queued" | "running" | "success" | "error";
  version?: number;
  created_at?: string;
  updated_at?: string;
  result?: T;
  error?: string;
};

export type ChatTaskResult = {
  content?: string;
  model?: string;
  channel?: string;
  request_id?: string;
};

export type ImageQuality = "auto" | "low" | "medium" | "high";
export type ImageOutputFormat = "png" | "jpeg" | "webp";
export type ImageModeration = "auto" | "low";

export type ImageRequestOptions = {
  size?: string;
  resolution?: string;
  quality?: ImageQuality | string;
  output_format?: ImageOutputFormat | string;
  output_compression?: number | null;
  moderation?: ImageModeration | string;
  background?: string;
};

type ImageResolutionTier = "1k" | "2k" | "4k";
type ImagePresetRatio = "1:1" | "3:2" | "2:3" | "16:9" | "9:16" | "4:3" | "3:4" | "21:9" | "9:21";

const IMAGE_SIZE_PATTERN = /^\s*(\d+)\s*[xX]\s*(\d+)\s*$/;
const IMAGE_RATIO_PATTERN = /^\s*(\d+(?:\.\d+)?)\s*[:xX]\s*(\d+(?:\.\d+)?)\s*$/;
const IMAGE_SIZE_MULTIPLE = 16;
const IMAGE_MAX_EDGE = 3840;
const IMAGE_MAX_ASPECT_RATIO = 3;
const IMAGE_MIN_PIXELS = 655_360;
const IMAGE_MAX_PIXELS = 8_294_400;

const IMAGE_RESOLUTION_TIERS: Record<string, ImageResolutionTier> = {
  "1k": "1k",
  "2k": "2k",
  "4k": "4k",
};

const IMAGE_TIER_PIXEL_BUDGET: Record<ImageResolutionTier, number> = {
  "1k": 1_572_864,
  "2k": 4_194_304,
  "4k": IMAGE_MAX_PIXELS,
};

const IMAGE_COMMON_SIZE_PRESETS: Record<ImageResolutionTier, Record<ImagePresetRatio, string>> = {
  "1k": {
    "1:1": "1024x1024",
    "3:2": "1536x1024",
    "2:3": "1024x1536",
    "16:9": "1280x720",
    "9:16": "720x1280",
    "4:3": "1024x768",
    "3:4": "768x1024",
    "21:9": "1920x816",
    "9:21": "816x1920",
  },
  "2k": {
    "1:1": "2048x2048",
    "3:2": "2160x1440",
    "2:3": "1440x2160",
    "16:9": "2560x1440",
    "9:16": "1440x2560",
    "4:3": "2048x1536",
    "3:4": "1536x2048",
    "21:9": "3120x1344",
    "9:21": "1344x3120",
  },
  "4k": {
    "1:1": "2880x2880",
    "3:2": "3456x2304",
    "2:3": "2304x3456",
    "16:9": "3840x2160",
    "9:16": "2160x3840",
    "4:3": "3200x2400",
    "3:4": "2400x3200",
    "21:9": "3840x1648",
    "9:21": "1648x3840",
  },
};

function roundToImageMultiple(value: number) {
  return Math.max(IMAGE_SIZE_MULTIPLE, Math.round(value / IMAGE_SIZE_MULTIPLE) * IMAGE_SIZE_MULTIPLE);
}

function floorToImageMultiple(value: number) {
  return Math.max(IMAGE_SIZE_MULTIPLE, Math.floor(value / IMAGE_SIZE_MULTIPLE) * IMAGE_SIZE_MULTIPLE);
}

function ceilToImageMultiple(value: number) {
  return Math.max(IMAGE_SIZE_MULTIPLE, Math.ceil(value / IMAGE_SIZE_MULTIPLE) * IMAGE_SIZE_MULTIPLE);
}

function normalizeImageDimensions(width: number, height: number) {
  let normalizedWidth = roundToImageMultiple(width);
  let normalizedHeight = roundToImageMultiple(height);

  const scaleToFit = (scale: number) => {
    normalizedWidth = floorToImageMultiple(normalizedWidth * scale);
    normalizedHeight = floorToImageMultiple(normalizedHeight * scale);
  };

  const scaleToFill = (scale: number) => {
    normalizedWidth = ceilToImageMultiple(normalizedWidth * scale);
    normalizedHeight = ceilToImageMultiple(normalizedHeight * scale);
  };

  for (let index = 0; index < 4; index += 1) {
    const maxEdge = Math.max(normalizedWidth, normalizedHeight);
    if (maxEdge > IMAGE_MAX_EDGE) {
      scaleToFit(IMAGE_MAX_EDGE / maxEdge);
    }

    if (normalizedWidth / normalizedHeight > IMAGE_MAX_ASPECT_RATIO) {
      normalizedWidth = floorToImageMultiple(normalizedHeight * IMAGE_MAX_ASPECT_RATIO);
    } else if (normalizedHeight / normalizedWidth > IMAGE_MAX_ASPECT_RATIO) {
      normalizedHeight = floorToImageMultiple(normalizedWidth * IMAGE_MAX_ASPECT_RATIO);
    }

    const pixels = normalizedWidth * normalizedHeight;
    if (pixels > IMAGE_MAX_PIXELS) {
      scaleToFit(Math.sqrt(IMAGE_MAX_PIXELS / pixels));
    } else if (pixels < IMAGE_MIN_PIXELS) {
      scaleToFill(Math.sqrt(IMAGE_MIN_PIXELS / pixels));
    }
  }

  return { width: normalizedWidth, height: normalizedHeight };
}

function parseImageSize(value: string) {
  const match = value.match(IMAGE_SIZE_PATTERN);
  if (!match) {
    return null;
  }
  return { width: Number(match[1]), height: Number(match[2]) };
}

function parseImageRatio(value: string) {
  const match = value.match(IMAGE_RATIO_PATTERN);
  if (!match) {
    return null;
  }

  const width = Number(match[1]);
  const height = Number(match[2]);
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) {
    return null;
  }

  return { width, height };
}

function gcd(a: number, b: number): number {
  return b === 0 ? a : gcd(b, a % b);
}

function getPresetRatioKey(ratioWidth: number, ratioHeight: number): ImagePresetRatio | null {
  if (!Number.isInteger(ratioWidth) || !Number.isInteger(ratioHeight)) {
    return null;
  }

  const divisor = gcd(ratioWidth, ratioHeight);
  const key = `${ratioWidth / divisor}:${ratioHeight / divisor}`;
  return key in IMAGE_COMMON_SIZE_PRESETS["1k"] ? (key as ImagePresetRatio) : null;
}

function getExactPresetRatioKey(value: string): ImagePresetRatio | null {
  return value in IMAGE_COMMON_SIZE_PRESETS["1k"] ? (value as ImagePresetRatio) : null;
}

function calculateImageSize(tier: ImageResolutionTier, ratio: string) {
  const exactPresetRatioKey = getExactPresetRatioKey(ratio.trim().toLowerCase());
  if (exactPresetRatioKey) {
    return IMAGE_COMMON_SIZE_PRESETS[tier][exactPresetRatioKey];
  }

  const parsed = parseImageRatio(ratio);
  if (!parsed) {
    return null;
  }

  const presetRatioKey = getPresetRatioKey(parsed.width, parsed.height);
  if (presetRatioKey) {
    return IMAGE_COMMON_SIZE_PRESETS[tier][presetRatioKey];
  }

  const targetRatio = parsed.width / parsed.height;
  const pixelBudget = IMAGE_TIER_PIXEL_BUDGET[tier];
  let bestWidth = 0;
  let bestHeight = 0;
  let bestPixels = 0;

  for (let width = IMAGE_SIZE_MULTIPLE; width <= IMAGE_MAX_EDGE; width += IMAGE_SIZE_MULTIPLE) {
    const idealHeight = width / targetRatio;
    const heightCandidates = [
      Math.floor(idealHeight / IMAGE_SIZE_MULTIPLE) * IMAGE_SIZE_MULTIPLE,
      Math.ceil(idealHeight / IMAGE_SIZE_MULTIPLE) * IMAGE_SIZE_MULTIPLE,
    ];

    for (const height of heightCandidates) {
      if (height < IMAGE_SIZE_MULTIPLE || height > IMAGE_MAX_EDGE) {
        continue;
      }

      const pixels = width * height;
      if (pixels > pixelBudget || pixels < IMAGE_MIN_PIXELS) {
        continue;
      }
      if (Math.max(width / height, height / width) > IMAGE_MAX_ASPECT_RATIO) {
        continue;
      }

      const actualRatio = width / height;
      const ratioError = Math.abs(actualRatio - targetRatio) / targetRatio;
      if (ratioError > 0.01) {
        continue;
      }

      if (pixels > bestPixels) {
        bestPixels = pixels;
        bestWidth = width;
        bestHeight = height;
      }
    }
  }

  return bestPixels > 0 ? `${bestWidth}x${bestHeight}` : null;
}

export function resolveImageRequestSize(size?: string, resolution?: string) {
  const normalizedSize = String(size || "").trim().toLowerCase();
  const normalizedResolution = String(resolution || "").trim().toLowerCase();
  const resolutionTier = IMAGE_RESOLUTION_TIERS[normalizedResolution];

  if (resolutionTier) {
    if (!normalizedSize || normalizedSize === "auto") {
      return IMAGE_COMMON_SIZE_PRESETS[resolutionTier]["1:1"];
    }

    const parsedSize = parseImageSize(normalizedSize);
    const ratio = parsedSize ? `${parsedSize.width}:${parsedSize.height}` : normalizedSize;
    return calculateImageSize(resolutionTier, ratio) || IMAGE_COMMON_SIZE_PRESETS[resolutionTier]["1:1"];
  }

  if (!normalizedSize || normalizedSize === "auto") {
    return undefined;
  }
  const parsedSize = parseImageSize(normalizedSize);
  if (parsedSize) {
    const { width, height } = normalizeImageDimensions(parsedSize.width, parsedSize.height);
    return `${width}x${height}`;
  }
  return calculateImageSize("1k", normalizedSize) || normalizedSize;
}

export type LoginResponse = {
  ok: boolean;
  version: string;
  role?: AuthRole;
  subject_id?: string;
  name?: string;
  email?: string;
  quota?: number;
  token?: string;
  verification_required?: boolean;
};

export type CurrentUser = {
  id: string;
  email?: string;
  name: string;
  role: AuthRole;
  status?: "active" | "disabled" | "pending";
  quota?: number;
  quota_used?: number;
  quota_expires_at?: string | null;
  email_verified?: boolean;
  email_verified_at?: string | null;
  image_count?: number;
  spent_quota?: number;
  created_at?: string | null;
  updated_at?: string | null;
  last_login_at?: string | null;
  image_channel?: UserImageChannel;
};

export type UserImageChannel = {
  enabled: boolean;
  name: string;
  base_url: string;
  models: string[];
  timeout: number;
  has_api_key: boolean;
};

export type UserImageChannelPayload = {
  enabled: boolean;
  name: string;
  base_url: string;
  api_key?: string;
  models: string[] | string;
  timeout: number;
};

export type UserImageChannelModelTestPayload = UserImageChannelPayload & {
  test_models?: string[];
};

export type AdminUser = CurrentUser & {
  email: string;
  status: "active" | "disabled" | "pending";
  quota: number;
  quota_used: number;
};

export async function login(input: string | { email: string; password: string }) {
  if (typeof input === "string") {
    const normalizedAuthKey = String(input || "").trim();
    return httpRequest<LoginResponse>("/auth/login", {
      method: "POST",
      body: {},
      headers: {
        Authorization: `Bearer ${normalizedAuthKey}`,
      },
      redirectOnUnauthorized: false,
    });
  }

  return httpRequest<LoginResponse>("/auth/login", {
    method: "POST",
    body: input,
    redirectOnUnauthorized: false,
  });
}

export async function registerUser(payload: { email: string; password: string; name?: string }) {
  return httpRequest<LoginResponse>("/auth/register", {
    method: "POST",
    body: payload,
    redirectOnUnauthorized: false,
  });
}

export async function verifyEmail(payload: { email: string; code: string }) {
  return httpRequest<LoginResponse>("/auth/verify-email", {
    method: "POST",
    body: payload,
    redirectOnUnauthorized: false,
  });
}

export async function resendEmailVerification(payload: { email: string; password: string }) {
  return httpRequest<LoginResponse>("/auth/resend-verification", {
    method: "POST",
    body: payload,
    redirectOnUnauthorized: false,
  });
}

export async function requestPasswordReset(payload: { email: string }) {
  return httpRequest<{ ok: boolean; version: string }>("/auth/password-reset/request", {
    method: "POST",
    body: payload,
    redirectOnUnauthorized: false,
  });
}

export async function confirmPasswordReset(payload: { email: string; code: string; password: string }) {
  return httpRequest<{ ok: boolean; version: string }>("/auth/password-reset/confirm", {
    method: "POST",
    body: payload,
    redirectOnUnauthorized: false,
  });
}

export async function fetchMe() {
  return httpRequest<{ user: CurrentUser }>("/api/me");
}

export async function fetchAvailableModels() {
  return httpRequest<ModelListResponse>("/v1/models");
}

export async function updateMyProfile(payload: { name?: string }) {
  return httpRequest<{ user: CurrentUser }>("/api/me/profile", {
    method: "POST",
    body: payload,
  });
}

export async function fetchMyImageChannel() {
  return httpRequest<{ channel: UserImageChannel }>("/api/me/image-channel");
}

export async function updateMyImageChannel(payload: UserImageChannelPayload) {
  return httpRequest<{ channel: UserImageChannel; user: CurrentUser }>("/api/me/image-channel", {
    method: "POST",
    body: payload,
  });
}

export async function testMyImageChannelModels(payload: UserImageChannelModelTestPayload) {
  return httpRequest<ChannelModelTestResult>("/api/me/image-channel/models/test", {
    method: "POST",
    body: payload,
  });
}

export async function redeemMyCode(code: string) {
  return httpRequest<{ user: CurrentUser; redeem_code: RedeemCode }>("/api/me/redeem", {
    method: "POST",
    body: { code },
  });
}

function normalizeImageRequestOptions(options: ImageRequestOptions = {}) {
  const payload: Record<string, string | number> = {};
  const resolvedSize = resolveImageRequestSize(options.size, options.resolution);
  if (resolvedSize) {
    payload.size = resolvedSize;
  }
  if (options.quality) {
    payload.quality = options.quality;
  }
  if (options.output_format) {
    payload.output_format = options.output_format;
  }
  if (options.output_format !== "png" && typeof options.output_compression === "number") {
    payload.output_compression = Math.max(0, Math.min(100, Math.round(options.output_compression)));
  }
  if (options.moderation) {
    payload.moderation = options.moderation;
  }
  if (options.background) {
    payload.background = options.background;
  }
  return payload;
}

export async function generateImage(prompt: string, model?: ImageModel, options: ImageRequestOptions = {}) {
  return httpRequest<ImageResponse>(
    "/v1/images/generations",
    {
      method: "POST",
      body: {
        prompt,
        ...(model ? { model } : {}),
        ...normalizeImageRequestOptions(options),
        n: 1,
        response_format: "url",
      },
    },
  );
}

export async function createImageGenerationTask(
  prompt: string,
  model: ImageModel | undefined,
  options: ImageRequestOptions = {},
  requestId: string,
) {
  return httpRequest<BackgroundTaskStatus<ImageResponse>>(
    "/api/tasks/images/generations",
    {
      method: "POST",
      headers: { "x-request-id": requestId },
      body: {
        prompt,
        ...(model ? { model } : {}),
        ...normalizeImageRequestOptions(options),
        n: 1,
        response_format: "url",
      },
    },
  );
}

export async function editImage(files: File | File[], prompt: string, model?: ImageModel, options: ImageRequestOptions = {}) {
  const formData = new FormData();
  const uploadFiles = Array.isArray(files) ? files : [files];

  uploadFiles.forEach((file) => {
    formData.append("image", file);
  });
  formData.append("prompt", prompt);
  if (model) {
    formData.append("model", model);
  }
  const requestOptions = normalizeImageRequestOptions(options);
  for (const [key, value] of Object.entries(requestOptions)) {
    formData.append(key, String(value));
  }
  formData.append("n", "1");
  formData.append("response_format", "url");

  return httpRequest<ImageResponse>(
    "/v1/images/edits",
    {
      method: "POST",
      body: formData,
    },
  );
}

export async function createImageEditTask(
  files: File | File[],
  prompt: string,
  model: ImageModel | undefined,
  options: ImageRequestOptions = {},
  requestId: string,
) {
  const formData = new FormData();
  const uploadFiles = Array.isArray(files) ? files : [files];

  uploadFiles.forEach((file) => {
    formData.append("image", file);
  });
  formData.append("prompt", prompt);
  if (model) {
    formData.append("model", model);
  }
  const requestOptions = normalizeImageRequestOptions(options);
  for (const [key, value] of Object.entries(requestOptions)) {
    formData.append(key, String(value));
  }
  formData.append("n", "1");
  formData.append("response_format", "url");

  return httpRequest<BackgroundTaskStatus<ImageResponse>>(
    "/api/tasks/images/edits",
    {
      method: "POST",
      headers: { "x-request-id": requestId },
      body: formData,
    },
  );
}

export async function createChatCompletion(messages: ChatCompletionMessage[], model?: string) {
  return httpRequest<ChatCompletionResponse>("/api/chat/completions", {
    method: "POST",
    body: {
      ...(model ? { model } : {}),
      messages,
    },
  });
}

export async function createChatCompletionTask(
  messages: ChatCompletionMessage[],
  model: string | undefined,
  requestId: string,
) {
  return httpRequest<BackgroundTaskStatus<ChatTaskResult>>("/api/chat/tasks", {
    method: "POST",
    headers: { "x-request-id": requestId },
    body: {
      ...(model ? { model } : {}),
      messages,
      stream: true,
    },
  });
}

export async function fetchBackgroundTask<T = unknown>(taskId: string) {
  return httpRequest<BackgroundTaskStatus<T>>(`/api/tasks/${encodeURIComponent(taskId)}`);
}

function parseTaskSseEvent<T>(raw: string): { type: "update"; task: BackgroundTaskStatus<T> } | { type: "error"; error: string } | null {
  const lines = raw.split(/\r?\n/);
  let event = "message";
  const dataLines: string[] = [];
  for (const line of lines) {
    if (line.startsWith("event:")) {
      event = line.slice("event:".length).trim();
      continue;
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).trimStart());
    }
  }
  const dataText = dataLines.join("\n").trim();
  if (!dataText || event === "ping") {
    return null;
  }
  let data: Record<string, unknown>;
  try {
    data = JSON.parse(dataText) as Record<string, unknown>;
  } catch {
    return null;
  }
  if (event === "error") {
    return { type: "error", error: String(data.error || "任务处理失败") };
  }
  if (event === "update") {
    return { type: "update", task: data as BackgroundTaskStatus<T> };
  }
  return null;
}

export async function streamBackgroundTask<T = unknown>(
  taskId: string,
  onUpdate: (task: BackgroundTaskStatus<T>) => void | Promise<void>,
  options: { version?: number } = {},
) {
  const authKey = await getStoredAuthKey();
  const params = new URLSearchParams();
  if (typeof options.version === "number") {
    params.set("version", String(options.version));
  }
  const response = await fetch(apiUrl(`/api/tasks/${encodeURIComponent(taskId)}/events${params.toString() ? `?${params.toString()}` : ""}`), {
    method: "GET",
    headers: {
      Accept: "text/event-stream",
      ...(authKey ? { Authorization: `Bearer ${authKey}` } : {}),
    },
  });
  if (!response.ok) {
    throw new Error(await readErrorResponse(response));
  }
  if (!response.body) {
    throw new Error("浏览器不支持流式响应");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split(/\r?\n\r?\n/);
    buffer = events.pop() || "";
    for (const rawEvent of events) {
      const event = parseTaskSseEvent<T>(rawEvent);
      if (!event) {
        continue;
      }
      if (event.type === "error") {
        throw new Error(event.error);
      }
      await onUpdate(event.task);
    }
  }
  buffer += decoder.decode();
  if (buffer.trim()) {
    const event = parseTaskSseEvent<T>(buffer);
    if (event?.type === "error") {
      throw new Error(event.error);
    }
    if (event?.type === "update") {
      await onUpdate(event.task);
    }
  }
}

function chatCompletionContentToText(content: unknown): string {
  if (typeof content === "string") {
    return content;
  }
  if (!Array.isArray(content)) {
    return "";
  }
  return content
    .map((part) => {
      if (!part || typeof part !== "object") {
        return "";
      }
      const item = part as { text?: unknown; content?: unknown };
      return typeof item.text === "string" ? item.text : typeof item.content === "string" ? item.content : "";
    })
    .join("");
}

export async function polishImagePrompt(prompt: string, mode: "generate" | "edit" | string, model?: string) {
  const normalizedPrompt = prompt.trim();
  if (!normalizedPrompt) {
    throw new Error("请输入提示词");
  }
  const modeLabel = mode === "edit" ? "图生图" : "文生图";
  const response = await createChatCompletion(
    [
      {
        role: "system",
        content:
          "你是专业 AI 图像提示词编辑器。请在不改变用户核心意图的前提下润色提示词，使其更适合图像生成。保留用户使用的主要语言，可补充构图、光线、材质、风格、镜头、色彩和质量细节。不要加入违背原意的新主体，不要解释，不要编号，不要输出 Markdown，只输出润色后的提示词。",
      },
      {
        role: "user",
        content: `当前模式：${modeLabel}\n原始提示词：\n${normalizedPrompt}`,
      },
    ],
    model,
  );
  const content = response.choices[0]?.message?.content;
  const polished = chatCompletionContentToText(content)
    .replace(/^```(?:\w+)?\s*/i, "")
    .replace(/\s*```$/i, "")
    .trim();
  if (!polished) {
    throw new Error("AI 润色结果为空");
  }
  return polished;
}

function apiUrl(path: string) {
  const baseUrl = webConfig.apiUrl.replace(/\/$/, "");
  return `${baseUrl}${path}`;
}

function parseSseEvent(raw: string): ChatStreamEvent | null {
  const lines = raw.split(/\r?\n/);
  let event = "message";
  const dataLines: string[] = [];
  for (const line of lines) {
    if (line.startsWith("event:")) {
      event = line.slice("event:".length).trim();
      continue;
    }
    if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).trimStart());
    }
  }
  const dataText = dataLines.join("\n").trim();
  if (!dataText) {
    return null;
  }
  let data: Record<string, unknown>;
  try {
    data = JSON.parse(dataText) as Record<string, unknown>;
  } catch {
    return null;
  }
  if (event === "delta") {
    return { type: "delta", content: String(data.content || ""), request_id: String(data.request_id || "") };
  }
  if (event === "done") {
    return {
      type: "done",
      model: String(data.model || ""),
      channel: String(data.channel || ""),
      request_id: String(data.request_id || ""),
    };
  }
  if (event === "error") {
    return { type: "error", error: String(data.error || "发送消息失败"), request_id: String(data.request_id || "") };
  }
  if (event === "meta") {
    return {
      type: "meta",
      model: String(data.model || ""),
      channel: String(data.channel || ""),
      request_id: String(data.request_id || ""),
    };
  }
  return null;
}

async function readErrorResponse(response: Response) {
  try {
    const payload = (await response.json()) as { detail?: unknown; error?: unknown; message?: unknown };
    const detail = payload.detail as { error?: unknown } | string | undefined;
    if (typeof detail === "string") {
      return detail;
    }
    if (detail && typeof detail === "object" && typeof detail.error === "string") {
      return detail.error;
    }
    if (typeof payload.error === "string") {
      return payload.error;
    }
    if (typeof payload.message === "string") {
      return payload.message;
    }
  } catch {
    // Fall back to HTTP status below.
  }
  return `请求失败 (${response.status})`;
}

export async function streamChatCompletion(
  messages: ChatCompletionMessage[],
  model: string | undefined,
  onEvent: (event: ChatStreamEvent) => void | Promise<void>,
) {
  const authKey = await getStoredAuthKey();
  const response = await fetch(apiUrl("/api/chat/completions"), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
      ...(authKey ? { Authorization: `Bearer ${authKey}` } : {}),
    },
    body: JSON.stringify({
      ...(model ? { model } : {}),
      messages,
      stream: true,
    }),
  });
  if (!response.ok) {
    throw new Error(await readErrorResponse(response));
  }
  if (!response.body) {
    throw new Error("浏览器不支持流式响应");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let doneReceived = false;
  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split(/\r?\n\r?\n/);
    buffer = events.pop() || "";
    for (const rawEvent of events) {
      const event = parseSseEvent(rawEvent);
      if (!event) {
        continue;
      }
      if (event.type === "done") {
        doneReceived = true;
      }
      if (event.type === "error") {
        throw new Error(event.error);
      }
      await onEvent(event);
    }
  }
  buffer += decoder.decode();
  if (buffer.trim()) {
    const event = parseSseEvent(buffer);
    if (event) {
      if (event.type === "done") {
        doneReceived = true;
      }
      if (event.type === "error") {
        throw new Error(event.error);
      }
      await onEvent(event);
    }
  }
  if (!doneReceived) {
    throw new Error("流式响应中断");
  }
}

export async function fetchSettingsConfig() {
  return httpRequest<{ config: SettingsConfig }>("/api/settings");
}

export async function fetchPublicSettings() {
  return httpRequest<{ settings: PublicSiteSettings }>("/api/public/settings", {
    redirectOnUnauthorized: false,
  });
}

export async function fetchPublicAuthSettings() {
  return httpRequest<{ settings: PublicAuthSettings }>("/api/public/auth-settings", {
    redirectOnUnauthorized: false,
  });
}

export async function updateSettingsConfig(settings: SettingsConfig) {
  return httpRequest<{ config: SettingsConfig }>("/api/settings", {
    method: "POST",
    body: settings,
  });
}

export async function testSmtpSettings(toEmail?: string) {
  return httpRequest<{ ok: boolean }>("/api/settings/smtp/test", {
    method: "POST",
    body: { to_email: toEmail || "" },
  });
}

export async function fetchManagedImages(filters: {
  start_date?: string;
  end_date?: string;
  user_id?: string;
  channel?: string;
  request_id?: string;
  page?: number;
  page_size?: number;
}) {
  const params = new URLSearchParams();
  if (filters.start_date) params.set("start_date", filters.start_date);
  if (filters.end_date) params.set("end_date", filters.end_date);
  if (filters.user_id) params.set("user_id", filters.user_id);
  if (filters.channel) params.set("channel", filters.channel);
  if (filters.request_id) params.set("request_id", filters.request_id);
  if (filters.page) params.set("page", String(filters.page));
  if (filters.page_size) params.set("page_size", String(filters.page_size));
  return httpRequest<ImageListResponse>(`/api/images${params.toString() ? `?${params.toString()}` : ""}`);
}

export async function deleteManagedImages(items: ManagedImageDeleteTarget[]) {
  return httpRequest<{ removed: number; removed_records: number; removed_files: number; ids: string[]; urls: string[] }>(
    "/api/images",
    {
      method: "DELETE",
      body: { items },
    },
  );
}

export async function fetchImagesWebDAVConfig() {
  return httpRequest<{ webdav: ImageWebDAVConfig }>("/api/images/webdav");
}

export async function updateImagesWebDAVConfig(payload: ImageWebDAVConfigPayload) {
  return httpRequest<{ webdav: ImageWebDAVConfig }>("/api/images/webdav", {
    method: "POST",
    body: payload,
  });
}

export async function syncImagesToWebDAV(filters: {
  start_date?: string;
  end_date?: string;
  user_id?: string;
  channel?: string;
  request_id?: string;
  ids?: string[];
}) {
  return httpRequest<{ result: ImageWebDAVSyncResult }>("/api/images/webdav/sync", {
    method: "POST",
    body: filters,
  });
}

export async function fetchPromptLibrary() {
  return httpRequest<PromptLibraryResponse>("/api/prompts");
}

export async function fetchAdminPrompts() {
  return httpRequest<PromptLibraryResponse>("/api/admin/prompts");
}

export async function fetchMyPrompts() {
  return httpRequest<PromptLibraryResponse>("/api/me/prompts");
}

export async function createAdminPrompt(payload: PromptLibraryPayload) {
  return httpRequest<{ item: PromptLibraryItem } & PromptLibraryResponse>("/api/admin/prompts", {
    method: "POST",
    body: payload,
  });
}

export async function createMyPrompt(payload: PromptLibraryPayload) {
  return httpRequest<{ item: PromptLibraryItem } & PromptLibraryResponse>("/api/me/prompts", {
    method: "POST",
    body: payload,
  });
}

export async function updateAdminPrompt(promptId: string, payload: Partial<PromptLibraryPayload>) {
  return httpRequest<{ item: PromptLibraryItem } & PromptLibraryResponse>(`/api/admin/prompts/${promptId}`, {
    method: "POST",
    body: payload,
  });
}

export async function updateMyPrompt(promptId: string, payload: Partial<PromptLibraryPayload>) {
  return httpRequest<{ item: PromptLibraryItem } & PromptLibraryResponse>(`/api/me/prompts/${promptId}`, {
    method: "POST",
    body: payload,
  });
}

export async function deleteAdminPrompt(promptId: string) {
  return httpRequest<PromptLibraryResponse>(`/api/admin/prompts/${promptId}`, {
    method: "DELETE",
  });
}

export async function deleteMyPrompt(promptId: string) {
  return httpRequest<PromptLibraryResponse>(`/api/me/prompts/${promptId}`, {
    method: "DELETE",
  });
}

export async function submitMyPrompt(promptId: string) {
  return httpRequest<{ item: PromptLibraryItem } & PromptLibraryResponse>(`/api/me/prompts/${promptId}/submit`, {
    method: "POST",
  });
}

export async function approveAdminPrompt(promptId: string) {
  return httpRequest<{ item: PromptLibraryItem } & PromptLibraryResponse>(`/api/admin/prompts/${promptId}/approve`, {
    method: "POST",
  });
}

export async function rejectAdminPrompt(promptId: string, reason = "") {
  return httpRequest<{ item: PromptLibraryItem } & PromptLibraryResponse>(`/api/admin/prompts/${promptId}/reject`, {
    method: "POST",
    body: { reason },
  });
}

export async function createPromptShare(payload: PromptLibraryPayload) {
  return httpRequest<{ item: PromptLibraryItem; share_id: string }>("/api/prompts/share", {
    method: "POST",
    body: payload,
  });
}

export async function sharePrompt(promptId: string) {
  return httpRequest<{ item: PromptLibraryItem; share_id: string }>(`/api/prompts/${promptId}/share`, {
    method: "POST",
  });
}

export async function fetchPromptShare(shareId: string) {
  return httpRequest<{ item: PromptLibraryItem; share_id: string }>(`/api/prompts/share/${shareId}`);
}

export async function importPromptShare(shareId: string, targetScope?: "public" | "personal") {
  return httpRequest<{ item: PromptLibraryItem }>(`/api/prompts/share/${shareId}/import`, {
    method: "POST",
    body: { target_scope: targetScope || "" },
  });
}

export async function uploadPromptExampleImage(file: File) {
  const formData = new FormData();
  formData.append("file", file);
  return httpRequest<{ url: string }>("/api/admin/prompt-assets", {
    method: "POST",
    body: formData,
  });
}

export async function uploadMyPromptExampleImage(file: File) {
  const formData = new FormData();
  formData.append("file", file);
  return httpRequest<{ url: string }>("/api/me/prompt-assets", {
    method: "POST",
    body: formData,
  });
}

export async function fetchMyImages(filters: {
  start_date?: string;
  end_date?: string;
  request_id?: string;
  page?: number;
  page_size?: number;
}) {
  const params = new URLSearchParams();
  if (filters.start_date) params.set("start_date", filters.start_date);
  if (filters.end_date) params.set("end_date", filters.end_date);
  if (filters.request_id) params.set("request_id", filters.request_id);
  if (filters.page) params.set("page", String(filters.page));
  if (filters.page_size) params.set("page_size", String(filters.page_size));
  return httpRequest<ImageListResponse>(`/api/me/images${params.toString() ? `?${params.toString()}` : ""}`);
}

export async function deleteMyImages(items: ManagedImageDeleteTarget[]) {
  return httpRequest<{ removed: number; removed_records: number; removed_files: number; ids: string[]; urls: string[] }>(
    "/api/me/images",
    {
      method: "DELETE",
      body: { items },
    },
  );
}

export async function downloadMyImages(items: ManagedImageDeleteTarget[]) {
  return httpRequest<Blob>("/api/me/images/download", {
    method: "POST",
    body: { items },
    responseType: "blob",
  });
}

export async function fetchMyImagesWebDAVConfig() {
  return httpRequest<{ webdav: ImageWebDAVConfig }>("/api/me/images/webdav");
}

export async function updateMyImagesWebDAVConfig(payload: ImageWebDAVConfigPayload) {
  return httpRequest<{ webdav: ImageWebDAVConfig }>("/api/me/images/webdav", {
    method: "POST",
    body: payload,
  });
}

export async function syncMyImagesToWebDAV(filters: {
  start_date?: string;
  end_date?: string;
  ids?: string[];
}) {
  return httpRequest<{ result: ImageWebDAVSyncResult }>("/api/me/images/webdav/sync", {
    method: "POST",
    body: filters,
  });
}

export async function fetchSystemLogs(filters: {
  type?: string;
  start_date?: string;
  end_date?: string;
  request_id?: string;
  status?: string;
  user?: string;
  page?: number;
  page_size?: number;
}) {
  const params = new URLSearchParams();
  if (filters.type) params.set("type", filters.type);
  if (filters.start_date) params.set("start_date", filters.start_date);
  if (filters.end_date) params.set("end_date", filters.end_date);
  if (filters.request_id) params.set("request_id", filters.request_id);
  if (filters.status) params.set("status", filters.status);
  if (filters.user) params.set("user", filters.user);
  if (filters.page) params.set("page", String(filters.page));
  if (filters.page_size) params.set("page_size", String(filters.page_size));
  return httpRequest<LogListResponse>(`/api/logs${params.toString() ? `?${params.toString()}` : ""}`);
}

export async function fetchAdminUsers(filters: { query?: string; status?: string; role?: string } = {}) {
  const params = new URLSearchParams();
  if (filters.query) params.set("query", filters.query);
  if (filters.status) params.set("status", filters.status);
  if (filters.role) params.set("role", filters.role);
  return httpRequest<{ items: AdminUser[] }>(`/api/admin/users${params.toString() ? `?${params.toString()}` : ""}`);
}

export async function createAdminUser(payload: {
  email: string;
  password: string;
  name?: string;
  quota?: number;
  quota_expires_at?: string | null;
  status?: "active" | "disabled" | "pending";
}) {
  return httpRequest<{ item: AdminUser; password: string; session_token: string; items: AdminUser[] }>(
    "/api/admin/users",
    {
      method: "POST",
      body: payload,
    },
  );
}

export async function updateAdminUser(
  userId: string,
  payload: { email?: string; name?: string; status?: "active" | "disabled" | "pending"; quota?: number; quota_expires_at?: string | null },
) {
  return httpRequest<{ item: AdminUser; items: AdminUser[] }>(`/api/admin/users/${userId}`, {
    method: "POST",
    body: payload,
  });
}

export async function deleteAdminUser(userId: string) {
  return httpRequest<{ items: AdminUser[] }>(`/api/admin/users/${userId}`, {
    method: "DELETE",
  });
}

export async function deleteAdminUsers(userIds: string[]) {
  return httpRequest<{ items: AdminUser[]; removed: number }>("/api/admin/users", {
    method: "DELETE",
    body: { ids: userIds },
  });
}

export async function updateAdminUserQuota(
  userId: string,
  payload: { amount: number; mode?: "add" | "set"; quota_expires_at?: string | null },
) {
  return httpRequest<{ item: AdminUser; items: AdminUser[] }>(`/api/admin/users/${userId}/quota`, {
    method: "POST",
    body: payload,
  });
}

export async function resetAdminUserPassword(userId: string, password?: string) {
  return httpRequest<{ item: AdminUser; password: string }>(`/api/admin/users/${userId}/reset-password`, {
    method: "POST",
    body: { password: password || "" },
  });
}

export type RedeemCode = {
  id: string;
  code: string;
  quota: number;
  status: "enabled" | "disabled";
  max_uses: number;
  valid_months: number;
  used_count: number;
  used_by: Array<{
    user_id: string;
    email: string;
    quota: number;
    valid_months?: number;
    quota_expires_at?: string | null;
    used_at: string;
  }>;
  expires_at?: string | null;
  created_at: string;
  created_by?: string;
  note?: string;
};

export async function fetchRedeemCodes(filters: { query?: string; status?: string } = {}) {
  const params = new URLSearchParams();
  if (filters.query) params.set("query", filters.query);
  if (filters.status) params.set("status", filters.status);
  return httpRequest<{ items: RedeemCode[] }>(
    `/api/admin/redeem-codes${params.toString() ? `?${params.toString()}` : ""}`,
  );
}

export async function createRedeemCodes(payload: {
  quota: number;
  count: number;
  max_uses?: number;
  valid_months?: number;
  expires_at?: string;
  note?: string;
}) {
  return httpRequest<{ items: RedeemCode[]; created: RedeemCode[] }>("/api/admin/redeem-codes/batch", {
    method: "POST",
    body: payload,
  });
}

export async function updateRedeemCode(
  codeId: string,
  payload: {
    status?: "enabled" | "disabled";
    quota?: number;
    max_uses?: number;
    valid_months?: number;
    expires_at?: string;
    note?: string;
  },
) {
  return httpRequest<{ item: RedeemCode; items: RedeemCode[] }>(`/api/admin/redeem-codes/${codeId}`, {
    method: "POST",
    body: payload,
  });
}

export async function deleteRedeemCodes(codeIds: string[]) {
  return httpRequest<{ items: RedeemCode[]; removed: number }>("/api/admin/redeem-codes", {
    method: "DELETE",
    body: { ids: codeIds },
  });
}

export type Channel = {
  id: string;
  name: string;
  type: "openai_image" | "gemini";
  base_url: string;
  models: string[];
  weight: number;
  priority: number;
  timeout: number;
  enabled: boolean;
  has_api_key: boolean;
  created_at?: string | null;
  updated_at?: string | null;
};

export type ChannelModelTestResult = {
  ok: boolean;
  channel: Channel;
  models: string[];
  model_count: number;
  tested_models: string[];
  missing_models: string[];
  latency_ms: number;
  error: string;
};

export type ModelPricing = {
  model: string;
  enabled: boolean;
  billing_mode: "tokens" | "fixed";
  currency: string;
  input_price_per_million: number;
  output_price_per_million: number;
  model_ratio: number;
  completion_ratio: number;
  model_price: number;
  note: string;
};

export type ModelChannelSummary = {
  id: string;
  name: string;
  type: "openai_image" | string;
  enabled: boolean;
  base_url?: string;
  models?: string[];
  model_count?: number;
};

export type ManagedModel = {
  id: string;
  model: string;
  source: "channel" | "custom";
  channel_count: number;
  channels: ModelChannelSummary[];
  enabled: boolean;
  configured: boolean;
  pricing: ModelPricing;
};

export type ModelCatalogResponse = {
  items: ManagedModel[];
  channels: ModelChannelSummary[];
  pricing: Record<string, ModelPricing>;
};

export type ModelPricingPayload = Partial<Omit<ModelPricing, "model">> & {
  model: string;
};

export async function fetchChannels() {
  return httpRequest<{ items: Channel[] }>("/api/admin/channels");
}

export async function createChannel(payload: {
  type?: Channel["type"];
  name: string;
  base_url: string;
  api_key: string;
  models: string[] | string;
  weight: number;
  priority: number;
  timeout: number;
  enabled: boolean;
}) {
  return httpRequest<{ item: Channel; items: Channel[] }>("/api/admin/channels", {
    method: "POST",
    body: payload,
  });
}

export async function updateChannel(
  channelId: string,
  payload: Partial<{
    type: Channel["type"];
    name: string;
    base_url: string;
    api_key: string;
    models: string[] | string;
    weight: number;
    priority: number;
    timeout: number;
    enabled: boolean;
  }>,
) {
  return httpRequest<{ item: Channel; items: Channel[] }>(`/api/admin/channels/${channelId}`, {
    method: "POST",
    body: payload,
  });
}

export async function deleteChannel(channelId: string) {
  return httpRequest<{ items: Channel[] }>(`/api/admin/channels/${channelId}`, {
    method: "DELETE",
  });
}

export async function fetchModelCatalog() {
  return httpRequest<ModelCatalogResponse>("/api/admin/models");
}

export async function updateModelPricing(payload: ModelPricingPayload) {
  return httpRequest<ModelCatalogResponse & { item: ModelPricing }>("/api/admin/models/pricing", {
    method: "POST",
    body: payload,
  });
}

export async function refreshChannelModels(channelId: string) {
  return httpRequest<ModelCatalogResponse & { channel: Channel; models: string[] }>(
    `/api/admin/channels/${channelId}/models/refresh`,
    { method: "POST" },
  );
}

export async function testChannelModels(channelId: string, models: string[] = []) {
  return httpRequest<ChannelModelTestResult>(`/api/admin/channels/${channelId}/models/test`, {
    method: "POST",
    body: { models },
  });
}

// ── Upstream proxy ────────────────────────────────────────────────

export type ProxySettings = {
  enabled: boolean;
  url: string;
};

export type ProxyTestResult = {
  ok: boolean;
  status: number;
  latency_ms: number;
  error: string | null;
};

export async function fetchProxy() {
  return httpRequest<{ proxy: ProxySettings }>("/api/proxy");
}

export async function updateProxy(updates: { enabled?: boolean; url?: string }) {
  return httpRequest<{ proxy: ProxySettings }>("/api/proxy", {
    method: "POST",
    body: updates,
  });
}

export async function testProxy(url?: string) {
  return httpRequest<{ result: ProxyTestResult }>("/api/proxy/test", {
    method: "POST",
    body: { url: url ?? "" },
  });
}
