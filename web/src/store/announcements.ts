"use client";

import { create } from "zustand";

import { fetchAnnouncements, type Announcement } from "@/lib/api";

const READ_STORAGE_KEY = "yanai:announcement-read";
const POPUP_STORAGE_KEY = "yanai:announcement-popup-dismissed";

type VersionMap = Record<string, string>;

type AnnouncementState = {
  items: Announcement[];
  readVersions: VersionMap;
  dismissedPopupVersions: VersionMap;
  isLoading: boolean;
  isLoaded: boolean;
  load: (force?: boolean) => Promise<void>;
  markAllRead: () => void;
  dismissPopup: (announcement: Announcement) => void;
};

let loadPromise: Promise<void> | null = null;

function versionOf(announcement: Announcement) {
  return announcement.updated_at || announcement.created_at || announcement.id;
}

function readVersionMap(key: string): VersionMap {
  if (typeof window === "undefined") return {};
  try {
    const value = JSON.parse(window.localStorage.getItem(key) || "{}");
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
  } catch {
    return {};
  }
}

function writeVersionMap(key: string, value: VersionMap) {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Storage can be unavailable in privacy modes; in-memory state still works.
  }
}

export function isAnnouncementUnread(announcement: Announcement, readVersions: VersionMap) {
  return readVersions[announcement.id] !== versionOf(announcement);
}

export function isAnnouncementPopupPending(announcement: Announcement, dismissedVersions: VersionMap) {
  return announcement.popup && dismissedVersions[announcement.id] !== versionOf(announcement);
}

export const useAnnouncementStore = create<AnnouncementState>((set, get) => ({
  items: [],
  readVersions: {},
  dismissedPopupVersions: {},
  isLoading: false,
  isLoaded: false,

  load: async (force = false) => {
    if (!force && get().isLoaded) return;
    if (!force && loadPromise) return loadPromise;

    const run = async () => {
      set({ isLoading: true });
      try {
        const data = await fetchAnnouncements();
        set({
          items: data.items,
          readVersions: readVersionMap(READ_STORAGE_KEY),
          dismissedPopupVersions: readVersionMap(POPUP_STORAGE_KEY),
          isLoaded: true,
        });
      } finally {
        set({ isLoading: false });
      }
    };

    loadPromise = run().finally(() => {
      loadPromise = null;
    });
    return loadPromise;
  },

  markAllRead: () => {
    const next = { ...get().readVersions };
    for (const announcement of get().items) {
      next[announcement.id] = versionOf(announcement);
    }
    writeVersionMap(READ_STORAGE_KEY, next);
    set({ readVersions: next });
  },

  dismissPopup: (announcement) => {
    const version = versionOf(announcement);
    const dismissedPopupVersions = {
      ...get().dismissedPopupVersions,
      [announcement.id]: version,
    };
    const readVersions = { ...get().readVersions, [announcement.id]: version };
    writeVersionMap(POPUP_STORAGE_KEY, dismissedPopupVersions);
    writeVersionMap(READ_STORAGE_KEY, readVersions);
    set({ dismissedPopupVersions, readVersions });
  },
}));
