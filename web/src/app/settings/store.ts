"use client";

import { toast } from "sonner";
import { create } from "zustand";

import { fetchSettingsConfig, updateSettingsConfig, type SettingsConfig } from "@/lib/api";
import { applySiteSettings, useSiteSettingsStore } from "@/lib/site-settings";

function normalizeConfig(config: SettingsConfig): SettingsConfig {
  return {
    ...config,
    site_title: typeof config.site_title === "string" ? config.site_title : "Image Studio",
    site_icon: typeof config.site_icon === "string" ? config.site_icon : "/favicon.ico",
    site_background: typeof config.site_background === "string" ? config.site_background : "",
    default_image_model: typeof config.default_image_model === "string" ? config.default_image_model : "gpt-image-2",
    default_text_model: typeof config.default_text_model === "string" ? config.default_text_model : "gpt-5.5",
    image_retention_days: Number(config.image_retention_days || 30),
    log_levels: Array.isArray(config.log_levels) ? config.log_levels : [],
    proxy: typeof config.proxy === "string" ? config.proxy : "",
    base_url: typeof config.base_url === "string" ? config.base_url : "",
  };
}

function syncSiteSettings(config: SettingsConfig) {
  const settings = {
    site_title: String(config.site_title || "Image Studio"),
    site_icon: String(config.site_icon || "/favicon.ico"),
    site_background: String(config.site_background || ""),
    default_image_model: String(config.default_image_model || "gpt-image-2"),
    default_text_model: String(config.default_text_model || "gpt-5.5"),
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
  setLogLevel: (level: string, enabled: boolean) => void;
  patchConfig: (updates: Partial<SettingsConfig>) => void;
  setProxy: (value: string) => void;
  setBaseUrl: (value: string) => void;
  setSiteTitle: (value: string) => void;
  setSiteIcon: (value: string) => void;
  setSiteBackground: (value: string) => void;
  setDefaultImageModel: (value: string) => void;
  setDefaultTextModel: (value: string) => void;
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
      const data = await updateSettingsConfig({
        ...config,
        site_title: String(config.site_title || "").trim(),
        site_icon: String(config.site_icon || "").trim(),
        site_background: String(config.site_background || "").trim(),
        default_image_model: String(config.default_image_model || "").trim() || "gpt-image-2",
        default_text_model: String(config.default_text_model || "").trim() || "gpt-5.5",
        image_retention_days: Math.max(1, Number(config.image_retention_days) || 30),
        proxy: String(config.proxy || "").trim(),
        base_url: String(config.base_url || "").trim(),
        log_levels: Array.isArray(config.log_levels) ? config.log_levels : [],
      });
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
}));
