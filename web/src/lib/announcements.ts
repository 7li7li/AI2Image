import type { Announcement, AnnouncementCategory } from "@/lib/api";

export const ANNOUNCEMENT_CATEGORY_OPTIONS: Array<{
  value: AnnouncementCategory;
  label: string;
}> = [
  { value: "system", label: "系统公告" },
  { value: "update", label: "产品更新" },
  { value: "maintenance", label: "维护通知" },
  { value: "activity", label: "活动通知" },
];

export function announcementCategoryLabel(category: AnnouncementCategory) {
  return ANNOUNCEMENT_CATEGORY_OPTIONS.find((item) => item.value === category)?.label || "系统公告";
}

export function announcementCategoryClassName(category: AnnouncementCategory) {
  if (category === "update") return "border-sky-200 bg-sky-50 text-sky-700";
  if (category === "maintenance") return "border-amber-200 bg-amber-50 text-amber-700";
  if (category === "activity") return "border-violet-200 bg-violet-50 text-violet-700";
  return "border-stone-200 bg-stone-100 text-stone-700";
}

export function formatAnnouncementTime(value: string) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function sortAnnouncements(items: Announcement[]) {
  return [...items].sort((left, right) => {
    const leftTime = Date.parse(left.updated_at || left.created_at) || 0;
    const rightTime = Date.parse(right.updated_at || right.created_at) || 0;
    return rightTime - leftTime;
  });
}
