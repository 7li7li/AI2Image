import { create } from "zustand";

import { fetchPublicSettings, type PublicSiteSettings } from "@/lib/api";

const SITE_SETTINGS_STORAGE_KEY = "yanai_site_settings";

const DEFAULT_SITE_SETTINGS: PublicSiteSettings = {
  site_title: "Image Studio",
  site_icon: "/favicon.ico",
  site_background: "",
  quota_purchase_url: "",
  default_image_model: "gpt-image-2",
  default_text_model: "gpt-5.5",
};

type SiteSettingsStore = {
  settings: PublicSiteSettings;
  isLoaded: boolean;
  load: () => Promise<void>;
  setSettings: (settings: Partial<PublicSiteSettings>) => void;
};

function normalizeSiteSettings(settings?: Partial<PublicSiteSettings> | null): PublicSiteSettings {
  return {
    site_title:
      String(settings?.site_title || DEFAULT_SITE_SETTINGS.site_title).trim() || DEFAULT_SITE_SETTINGS.site_title,
    site_icon: String(settings?.site_icon || DEFAULT_SITE_SETTINGS.site_icon).trim() || DEFAULT_SITE_SETTINGS.site_icon,
    site_background: String(settings?.site_background || DEFAULT_SITE_SETTINGS.site_background).trim(),
    quota_purchase_url: String(settings?.quota_purchase_url || DEFAULT_SITE_SETTINGS.quota_purchase_url).trim(),
    default_image_model:
      String(settings?.default_image_model || DEFAULT_SITE_SETTINGS.default_image_model).trim() ||
      DEFAULT_SITE_SETTINGS.default_image_model,
    default_text_model:
      String(settings?.default_text_model || DEFAULT_SITE_SETTINGS.default_text_model).trim() ||
      DEFAULT_SITE_SETTINGS.default_text_model,
  };
}

function readCachedSiteSettings(): PublicSiteSettings {
  if (typeof window === "undefined") {
    return DEFAULT_SITE_SETTINGS;
  }
  try {
    const raw = window.localStorage.getItem(SITE_SETTINGS_STORAGE_KEY);
    if (!raw) {
      return DEFAULT_SITE_SETTINGS;
    }
    return normalizeSiteSettings(JSON.parse(raw) as Partial<PublicSiteSettings>);
  } catch {
    return DEFAULT_SITE_SETTINGS;
  }
}

function writeCachedSiteSettings(settings: PublicSiteSettings) {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.setItem(SITE_SETTINGS_STORAGE_KEY, JSON.stringify(settings));
  } catch {
    // Ignore storage failures; settings still apply for the current page.
  }
}

export const useSiteSettingsStore = create<SiteSettingsStore>((set, get) => ({
  settings: readCachedSiteSettings(),
  isLoaded: false,

  load: async () => {
    const cached = readCachedSiteSettings();
    set({ settings: cached });
    applySiteSettings(cached);

    try {
      const data = await fetchPublicSettings();
      const settings = normalizeSiteSettings(data.settings);
      writeCachedSiteSettings(settings);
      set({ settings, isLoaded: true });
      applySiteSettings(settings);
    } catch {
      set({ settings: cached, isLoaded: true });
    }
  },

  setSettings: (settings) => {
    const nextSettings = normalizeSiteSettings({ ...get().settings, ...settings });
    writeCachedSiteSettings(nextSettings);
    set({ settings: nextSettings, isLoaded: true });
  },
}));

export function applySiteSettings(settings: PublicSiteSettings) {
  if (typeof document === "undefined") {
    return;
  }

  document.title = settings.site_title;

  const selector = "link[rel='icon'], link[rel='shortcut icon'], link[rel='apple-touch-icon']";
  document.head.querySelectorAll<HTMLLinkElement>(selector).forEach((item) => item.remove());
  const icon = document.createElement("link");
  icon.rel = "icon";
  if (settings.site_icon.toLowerCase().split("?", 1)[0]?.endsWith(".png")) {
    icon.type = "image/png";
  }
  icon.href = settings.site_icon;
  document.head.appendChild(icon);
}
