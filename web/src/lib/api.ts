import { httpRequest } from "@/lib/request";

export type ImageModel = "gpt-image-2" | "codex-gpt-image-2";
export type AuthRole = "admin" | "user";

export type SettingsConfig = {
  proxy: string;
  site_title?: string;
  site_icon?: string;
  site_background?: string;
  base_url?: string;
  image_retention_days?: number | string;
  log_levels?: string[];
  [key: string]: unknown;
};

export type PublicSiteSettings = {
  site_title: string;
  site_icon: string;
  site_background: string;
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

export type LoginResponse = {
  ok: boolean;
  version: string;
  role: AuthRole;
  subject_id: string;
  name: string;
  email?: string;
  quota?: number;
  token?: string;
};

export type CurrentUser = {
  id: string;
  email?: string;
  name: string;
  role: AuthRole;
  status?: "active" | "disabled";
  quota?: number;
  quota_used?: number;
  quota_expires_at?: string | null;
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
  status: "active" | "disabled";
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

export async function fetchMe() {
  return httpRequest<{ user: CurrentUser }>("/api/me");
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
  if (options.size) {
    payload.size = options.size;
  }
  if (options.resolution && options.resolution !== "auto") {
    payload.resolution = options.resolution;
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

export async function fetchSettingsConfig() {
  return httpRequest<{ config: SettingsConfig }>("/api/settings");
}

export async function fetchPublicSettings() {
  return httpRequest<{ settings: PublicSiteSettings }>("/api/public/settings", {
    redirectOnUnauthorized: false,
  });
}

export async function updateSettingsConfig(settings: SettingsConfig) {
  return httpRequest<{ config: SettingsConfig }>("/api/settings", {
    method: "POST",
    body: settings,
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
  page?: number;
  page_size?: number;
}) {
  const params = new URLSearchParams();
  if (filters.start_date) params.set("start_date", filters.start_date);
  if (filters.end_date) params.set("end_date", filters.end_date);
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
  status?: "active" | "disabled";
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
  payload: { email?: string; name?: string; status?: "active" | "disabled"; quota?: number; quota_expires_at?: string | null },
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
  type: "openai_image";
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
