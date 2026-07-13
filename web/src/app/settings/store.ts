"use client";

import { toast } from "sonner";
import { create } from "zustand";

import {
  fetchSettingsConfig,
  updateSettingsConfig,
  type QuotaPurchaseMode,
  type SettingsConfig,
  type SubscriptionPlan,
} from "@/lib/api";
import { applySiteSettings, useSiteSettingsStore } from "@/lib/site-settings";

function boundedNumber(value: unknown, fallback: number, min: number, max: number): number {
  const parsed = value === "" || value === null || value === undefined ? fallback : Number(value);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return Math.max(min, Math.min(max, parsed));
}

function strictBoundedNumber(value: unknown, min: number, max: number): number | null {
  if (value === "" || value === null || value === undefined) {
    return null;
  }
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return null;
  }
  return Math.max(min, Math.min(max, Math.trunc(parsed)));
}

function normalizeStringList(value: unknown): string[] {
  const items =
    typeof value === "string"
      ? value.replace(/;/g, "\n").replace(/,/g, "\n").split(/\r?\n/)
      : Array.isArray(value)
        ? value
        : [];
  return Array.from(
    new Set(
      items
        .map((item) => String(item || "").trim().toLowerCase().replace(/^@/, ""))
        .filter(Boolean),
    ),
  );
}

function normalizeQuotaPurchaseMode(value: unknown): QuotaPurchaseMode {
  return value === "subscription" ? "subscription" : "url";
}

function normalizeSubscriptionPlans(value: unknown): SubscriptionPlan[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((plan, index) => {
      const item = plan && typeof plan === "object" ? (plan as Record<string, unknown>) : {};
      const quota = strictBoundedNumber(item.quota, 1, 1_000_000);
      const validMonths = strictBoundedNumber(item.valid_months, 1, 120);
      const concurrency = strictBoundedNumber(item.concurrency ?? 1, 1, 50);
      const price = String(item.price ?? "").trim();
      if (quota === null || validMonths === null || concurrency === null || !price) {
        return null;
      }
      return {
        id: String(item.id || `plan-${index + 1}`).trim(),
        name: String(item.name || "").trim(),
        quota,
        valid_months: validMonths,
        concurrency,
        price,
      };
    })
    .filter((plan): plan is SubscriptionPlan => plan !== null && Boolean(plan.id));
}

function normalizeConfig(config: SettingsConfig): SettingsConfig {
  return {
    ...config,
    site_title: typeof config.site_title === "string" ? config.site_title : "Image Studio",
    site_icon: typeof config.site_icon === "string" ? config.site_icon : "/favicon.ico",
    site_background: typeof config.site_background === "string" ? config.site_background : "",
    qq_group_number: typeof config.qq_group_number === "string" ? config.qq_group_number : "",
    qq_group_link: typeof config.qq_group_link === "string" ? config.qq_group_link : "",
    qq_group_subscription_required: Boolean(config.qq_group_subscription_required),
    telegram_group_link: typeof config.telegram_group_link === "string" ? config.telegram_group_link : "",
    telegram_group_subscription_required: Boolean(config.telegram_group_subscription_required),
    quota_purchase_url: typeof config.quota_purchase_url === "string" ? config.quota_purchase_url : "",
    quota_purchase_mode: normalizeQuotaPurchaseMode(config.quota_purchase_mode),
    subscription_plans: normalizeSubscriptionPlans(config.subscription_plans),
    default_image_model: typeof config.default_image_model === "string" ? config.default_image_model : "gpt-image-2",
    default_text_model: typeof config.default_text_model === "string" ? config.default_text_model : "gpt-5.5",
    default_image_prompt_polish_model:
      typeof config.default_image_prompt_polish_model === "string"
        ? config.default_image_prompt_polish_model
        : "gpt-5.5",
    image_retention_days: Number(config.image_retention_days || 30),
    background_task_max_workers: boundedNumber(config.background_task_max_workers, 12, 1, 128),
    background_task_queue_limit: boundedNumber(config.background_task_queue_limit, 100, 1, 10000),
    background_task_user_limit: boundedNumber(config.background_task_user_limit, 3, 0, 50),
    background_task_user_queue_limit: boundedNumber(config.background_task_user_queue_limit, 20, 1, 1000),
    log_levels: Array.isArray(config.log_levels) ? config.log_levels : [],
    proxy: typeof config.proxy === "string" ? config.proxy : "",
    base_url: typeof config.base_url === "string" ? config.base_url : "",
    allow_user_registration: Boolean(config.allow_user_registration),
    email_verification_enabled: Boolean(config.email_verification_enabled),
    email_domain_whitelist_enabled: Boolean(config.email_domain_whitelist_enabled),
    email_domain_whitelist: normalizeStringList(config.email_domain_whitelist),
    new_user_initial_quota: boundedNumber(config.new_user_initial_quota, 0, 0, 1_000_000),
    new_user_quota_valid_days: boundedNumber(config.new_user_quota_valid_days, 0, 0, 3650),
    smtp_host: typeof config.smtp_host === "string" ? config.smtp_host : "",
    smtp_port: boundedNumber(config.smtp_port, 587, 1, 65535),
    smtp_username: typeof config.smtp_username === "string" ? config.smtp_username : "",
    smtp_password: "",
    smtp_password_set: Boolean(config.smtp_password_set),
    smtp_from_email: typeof config.smtp_from_email === "string" ? config.smtp_from_email : "",
    smtp_use_ssl: Boolean(config.smtp_use_ssl),
    smtp_use_starttls: config.smtp_use_starttls === undefined ? true : Boolean(config.smtp_use_starttls),
    smtp_force_auth_login: config.smtp_force_auth_login === undefined ? true : Boolean(config.smtp_force_auth_login),
  };
}

function syncSiteSettings(config: SettingsConfig) {
  const settings = {
    site_title: String(config.site_title || "Image Studio"),
    site_icon: String(config.site_icon || "/favicon.ico"),
    site_background: String(config.site_background || ""),
    quota_purchase_url: String(config.quota_purchase_url || ""),
    quota_purchase_mode: normalizeQuotaPurchaseMode(config.quota_purchase_mode),
    subscription_plans: normalizeSubscriptionPlans(config.subscription_plans),
    default_image_model: String(config.default_image_model || "gpt-image-2"),
    default_text_model: String(config.default_text_model || "gpt-5.5"),
    default_image_prompt_polish_model: String(config.default_image_prompt_polish_model || "gpt-5.5"),
  };
  useSiteSettingsStore.getState().setSettings(settings);
  applySiteSettings(settings);
}

type SettingsStore = {
  config: SettingsConfig | null;
  isLoadingConfig: boolean;
  isSavingConfig: boolean;

  initialize: () => Promise<void>;
  loadConfig: () => Promise<void>;
  saveConfig: () => Promise<void>;
  setImageRetentionDays: (value: string) => void;
  setBackgroundTaskMaxWorkers: (value: string) => void;
  setBackgroundTaskQueueLimit: (value: string) => void;
  setBackgroundTaskUserLimit: (value: string) => void;
  setBackgroundTaskUserQueueLimit: (value: string) => void;
  setLogLevel: (level: string, enabled: boolean) => void;
  patchConfig: (updates: Partial<SettingsConfig>) => void;
  setProxy: (value: string) => void;
  setBaseUrl: (value: string) => void;
  setSiteTitle: (value: string) => void;
  setSiteIcon: (value: string) => void;
  setSiteBackground: (value: string) => void;
  setDefaultImageModel: (value: string) => void;
  setDefaultTextModel: (value: string) => void;
  setDefaultImagePromptPolishModel: (value: string) => void;
};

export const useSettingsStore = create<SettingsStore>((set, get) => ({
  config: null,
  isLoadingConfig: true,
  isSavingConfig: false,

  initialize: async () => {
    await get().loadConfig();
  },

  loadConfig: async () => {
    set({ isLoadingConfig: true });
    try {
      const data = await fetchSettingsConfig();
      const config = normalizeConfig(data.config);
      set({ config });
      syncSiteSettings(config);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "加载系统配置失败");
    } finally {
      set({ isLoadingConfig: false });
    }
  },

  saveConfig: async () => {
    const { config } = get();
    if (!config) {
      return;
    }

    set({ isSavingConfig: true });
    try {
      const payload: Partial<SettingsConfig> = {
        site_title: String(config.site_title || "").trim(),
        site_icon: String(config.site_icon || "").trim(),
        site_background: String(config.site_background || "").trim(),
        qq_group_number: String(config.qq_group_number || "").trim(),
        qq_group_link: String(config.qq_group_link || "").trim(),
        qq_group_subscription_required: Boolean(config.qq_group_subscription_required),
        telegram_group_link: String(config.telegram_group_link || "").trim(),
        telegram_group_subscription_required: Boolean(config.telegram_group_subscription_required),
        default_image_model: String(config.default_image_model || "").trim() || "gpt-image-2",
        default_text_model: String(config.default_text_model || "").trim() || "gpt-5.5",
        default_image_prompt_polish_model:
          String(config.default_image_prompt_polish_model || "").trim() || "gpt-5.5",
        image_retention_days: Math.max(1, Number(config.image_retention_days) || 30),
        background_task_max_workers: boundedNumber(config.background_task_max_workers, 12, 1, 128),
        background_task_queue_limit: boundedNumber(config.background_task_queue_limit, 100, 1, 10000),
        background_task_user_limit: boundedNumber(config.background_task_user_limit, 3, 0, 50),
        background_task_user_queue_limit: boundedNumber(config.background_task_user_queue_limit, 20, 1, 1000),
        proxy: String(config.proxy || "").trim(),
        base_url: String(config.base_url || "").trim(),
        log_levels: Array.isArray(config.log_levels) ? config.log_levels : [],
        allow_user_registration: Boolean(config.allow_user_registration),
        email_verification_enabled: Boolean(config.email_verification_enabled),
        email_domain_whitelist_enabled: Boolean(config.email_domain_whitelist_enabled),
        email_domain_whitelist: normalizeStringList(config.email_domain_whitelist),
        new_user_initial_quota: boundedNumber(config.new_user_initial_quota, 0, 0, 1_000_000),
        new_user_quota_valid_days: boundedNumber(config.new_user_quota_valid_days, 0, 0, 3650),
        smtp_host: String(config.smtp_host || "").trim(),
        smtp_port: boundedNumber(config.smtp_port, 587, 1, 65535),
        smtp_username: String(config.smtp_username || "").trim(),
        smtp_password: String(config.smtp_password || ""),
        smtp_from_email: String(config.smtp_from_email || "").trim(),
        smtp_use_ssl: Boolean(config.smtp_use_ssl),
        smtp_use_starttls: Boolean(config.smtp_use_starttls),
        smtp_force_auth_login: Boolean(config.smtp_force_auth_login),
      };
      const data = await updateSettingsConfig(payload);
      const nextConfig = normalizeConfig(data.config);
      set({ config: nextConfig });
      syncSiteSettings(nextConfig);
      toast.success("配置已保存");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "保存系统配置失败");
    } finally {
      set({ isSavingConfig: false });
    }
  },

  setImageRetentionDays: (value) => {
    set((state) => (state.config ? { config: { ...state.config, image_retention_days: value } } : {}));
  },

  setBackgroundTaskMaxWorkers: (value) => {
    set((state) => (state.config ? { config: { ...state.config, background_task_max_workers: value } } : {}));
  },

  setBackgroundTaskQueueLimit: (value) => {
    set((state) => (state.config ? { config: { ...state.config, background_task_queue_limit: value } } : {}));
  },

  setBackgroundTaskUserLimit: (value) => {
    set((state) => (state.config ? { config: { ...state.config, background_task_user_limit: value } } : {}));
  },

  setBackgroundTaskUserQueueLimit: (value) => {
    set((state) => (state.config ? { config: { ...state.config, background_task_user_queue_limit: value } } : {}));
  },

  setLogLevel: (level, enabled) => {
    set((state) => {
      if (!state.config) return {};
      const levels = new Set(state.config.log_levels || []);
      if (enabled) levels.add(level);
      else levels.delete(level);
      return { config: { ...state.config, log_levels: Array.from(levels) } };
    });
  },

  patchConfig: (updates) => {
    set((state) => (state.config ? { config: { ...state.config, ...updates } } : {}));
  },

  setProxy: (value) => {
    set((state) => (state.config ? { config: { ...state.config, proxy: value } } : {}));
  },

  setBaseUrl: (value) => {
    set((state) => (state.config ? { config: { ...state.config, base_url: value } } : {}));
  },

  setSiteTitle: (value) => {
    set((state) => (state.config ? { config: { ...state.config, site_title: value } } : {}));
  },

  setSiteIcon: (value) => {
    set((state) => (state.config ? { config: { ...state.config, site_icon: value } } : {}));
  },

  setSiteBackground: (value) => {
    set((state) => (state.config ? { config: { ...state.config, site_background: value } } : {}));
  },

  setDefaultImageModel: (value) => {
    set((state) => (state.config ? { config: { ...state.config, default_image_model: value } } : {}));
  },

  setDefaultTextModel: (value) => {
    set((state) => (state.config ? { config: { ...state.config, default_text_model: value } } : {}));
  },

  setDefaultImagePromptPolishModel: (value) => {
    set((state) =>
      state.config ? { config: { ...state.config, default_image_prompt_polish_model: value } } : {},
    );
  },
}));
