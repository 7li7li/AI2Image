"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Bell,
  BellRing,
  CalendarDays,
  CheckCircle2,
  LoaderCircle,
  Pencil,
  Plus,
  Trash2,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import {
  ANNOUNCEMENT_CATEGORY_OPTIONS,
  announcementCategoryClassName,
  announcementCategoryLabel,
  formatAnnouncementTime,
  sortAnnouncements,
} from "@/lib/announcements";
import {
  fetchSettingsConfig,
  updateSettingsConfig,
  type Announcement,
  type AnnouncementCategory,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { useAuthGuard } from "@/lib/use-auth-guard";
import { useAnnouncementStore } from "@/store/announcements";

type AnnouncementDraft = {
  title: string;
  content: string;
  category: AnnouncementCategory;
  enabled: boolean;
  popup: boolean;
};

const EMPTY_DRAFT: AnnouncementDraft = {
  title: "",
  content: "",
  category: "system",
  enabled: true,
  popup: false,
};

function createAnnouncementId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `announcement-${Date.now()}`;
}

function AnnouncementItem({ announcement, compact = false }: { announcement: Announcement; compact?: boolean }) {
  return (
    <article className="border-b border-stone-200 py-5 last:border-b-0">
      <div className="flex min-w-0 items-start gap-3 sm:gap-4">
        <span className="mt-0.5 grid size-9 shrink-0 place-items-center rounded-lg border border-stone-200 bg-white text-stone-700">
          <Bell className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="min-w-0 text-base font-semibold text-stone-950">{announcement.title}</h2>
            <Badge variant="outline" className={announcementCategoryClassName(announcement.category)}>
              {announcementCategoryLabel(announcement.category)}
            </Badge>
          </div>
          <div className="mt-1 flex items-center gap-1.5 text-xs text-stone-400">
            <CalendarDays className="size-3.5" />
            {formatAnnouncementTime(announcement.updated_at || announcement.created_at)}
          </div>
          <div
            className={cn(
              "mt-3 whitespace-pre-wrap break-words text-sm leading-7 text-stone-700",
              compact && "line-clamp-3",
            )}
          >
            {announcement.content}
          </div>
        </div>
      </div>
    </article>
  );
}

function UserAnnouncements() {
  const items = useAnnouncementStore((state) => state.items);
  const isLoading = useAnnouncementStore((state) => state.isLoading);
  const isLoaded = useAnnouncementStore((state) => state.isLoaded);
  const load = useAnnouncementStore((state) => state.load);
  const markAllRead = useAnnouncementStore((state) => state.markAllRead);
  const [category, setCategory] = useState<AnnouncementCategory | "all">("all");

  useEffect(() => {
    void load().catch((error) => toast.error(error instanceof Error ? error.message : "加载公告失败"));
  }, [load]);

  useEffect(() => {
    if (isLoaded) markAllRead();
  }, [isLoaded, markAllRead]);

  const sortedItems = useMemo(() => sortAnnouncements(items), [items]);
  const visibleItems = category === "all" ? sortedItems : sortedItems.filter((item) => item.category === category);
  const availableCategories = ANNOUNCEMENT_CATEGORY_OPTIONS.filter((option) =>
    sortedItems.some((item) => item.category === option.value),
  );

  return (
    <section className="h-full min-h-0 overflow-y-auto bg-white px-4 py-6 sm:px-8 sm:py-8">
      <div className="mx-auto max-w-4xl">
        <header className="flex flex-col gap-4 border-b border-stone-200 pb-6 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <div className="flex items-center gap-2 text-xs font-semibold text-stone-400 uppercase">
              <BellRing className="size-4" />
              Announcements
            </div>
            <h1 className="mt-2 text-2xl font-semibold text-stone-950">系统公告</h1>
          </div>
          {sortedItems.length > 0 ? (
            <div className="flex flex-wrap gap-1 rounded-lg bg-stone-100 p-1" aria-label="公告分类">
              <button
                type="button"
                className={cn(
                  "h-8 rounded-md px-3 text-xs font-medium transition",
                  category === "all" ? "bg-white text-stone-950 shadow-sm" : "text-stone-500 hover:text-stone-900",
                )}
                onClick={() => setCategory("all")}
              >
                全部
              </button>
              {availableCategories.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  className={cn(
                    "h-8 rounded-md px-3 text-xs font-medium transition",
                    category === option.value
                      ? "bg-white text-stone-950 shadow-sm"
                      : "text-stone-500 hover:text-stone-900",
                  )}
                  onClick={() => setCategory(option.value)}
                >
                  {option.label}
                </button>
              ))}
            </div>
          ) : null}
        </header>

        {isLoading && !isLoaded ? (
          <div className="grid min-h-64 place-items-center text-stone-400">
            <LoaderCircle className="size-5 animate-spin" />
          </div>
        ) : visibleItems.length > 0 ? (
          <div>{visibleItems.map((item) => <AnnouncementItem key={item.id} announcement={item} />)}</div>
        ) : (
          <div className="grid min-h-64 place-items-center text-center">
            <div>
              <Bell className="mx-auto size-7 text-stone-300" />
              <p className="mt-3 text-sm font-medium text-stone-600">暂无公告</p>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

function AdminAnnouncements() {
  const [items, setItems] = useState<Announcement[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [editing, setEditing] = useState<Announcement | null | undefined>(undefined);
  const [deleting, setDeleting] = useState<Announcement | null>(null);
  const [draft, setDraft] = useState<AnnouncementDraft>(EMPTY_DRAFT);

  useEffect(() => {
    let active = true;
    void fetchSettingsConfig()
      .then((data) => {
        if (active) setItems(sortAnnouncements(data.config.announcements || []));
      })
      .catch((error) => toast.error(error instanceof Error ? error.message : "加载公告失败"))
      .finally(() => active && setIsLoading(false));
    return () => {
      active = false;
    };
  }, []);

  const openCreate = () => {
    setDraft(EMPTY_DRAFT);
    setEditing(null);
  };

  const openEdit = (announcement: Announcement) => {
    setDraft({
      title: announcement.title,
      content: announcement.content,
      category: announcement.category,
      enabled: announcement.enabled,
      popup: announcement.popup,
    });
    setEditing(announcement);
  };

  const persist = async (nextItems: Announcement[], message: string) => {
    setIsSaving(true);
    try {
      const data = await updateSettingsConfig({ announcements: nextItems });
      setItems(sortAnnouncements(data.config.announcements || []));
      toast.success(message);
      return true;
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "保存公告失败");
      return false;
    } finally {
      setIsSaving(false);
    }
  };

  const saveDraft = async () => {
    const title = draft.title.trim();
    const content = draft.content.trim();
    if (!title || !content) {
      toast.error("请填写公告标题和正文");
      return;
    }
    const now = new Date().toISOString();
    const next: Announcement = {
      id: editing?.id || createAnnouncementId(),
      title,
      content,
      category: draft.category,
      enabled: draft.enabled,
      popup: draft.popup,
      created_at: editing?.created_at || now,
      updated_at: now,
    };
    const nextItems = editing
      ? items.map((item) => (item.id === editing.id ? next : item))
      : [next, ...items];
    if (await persist(nextItems, editing ? "公告已更新" : "公告已创建")) setEditing(undefined);
  };

  const deleteAnnouncement = async () => {
    if (!deleting) return;
    if (await persist(items.filter((item) => item.id !== deleting.id), "公告已删除")) setDeleting(null);
  };

  return (
    <section className="h-full min-h-0 overflow-y-auto bg-[#f7f7f8] px-3 py-5 sm:px-6 sm:py-7">
      <div className="mx-auto max-w-5xl">
        <header className="flex items-start justify-between gap-4 border-b border-stone-200 pb-5">
          <div>
            <div className="text-xs font-semibold text-stone-400 uppercase">Announcements</div>
            <h1 className="mt-1 text-2xl font-semibold text-stone-950">公告管理</h1>
            <p className="mt-1 text-sm text-stone-500">发布站内公告，并控制是否向用户弹窗提示。</p>
          </div>
          <Button onClick={openCreate}>
            <Plus className="size-4" />
            新建公告
          </Button>
        </header>

        {isLoading ? (
          <div className="grid min-h-72 place-items-center text-stone-400">
            <LoaderCircle className="size-5 animate-spin" />
          </div>
        ) : items.length > 0 ? (
          <div className="mt-5 overflow-hidden rounded-lg border border-stone-200 bg-white px-4 sm:px-5">
            {items.map((item) => (
              <div key={item.id} className="flex gap-3 border-b border-stone-200 py-5 last:border-b-0">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <h2 className="font-semibold text-stone-950">{item.title}</h2>
                    <Badge variant="outline" className={announcementCategoryClassName(item.category)}>
                      {announcementCategoryLabel(item.category)}
                    </Badge>
                    <Badge variant="outline" className={item.enabled ? "border-emerald-200 bg-emerald-50 text-emerald-700" : "text-stone-500"}>
                      {item.enabled ? "已发布" : "草稿"}
                    </Badge>
                    {item.popup ? <Badge variant="outline">弹窗提示</Badge> : null}
                  </div>
                  <p className="mt-2 line-clamp-2 whitespace-pre-wrap text-sm leading-6 text-stone-600">{item.content}</p>
                  <p className="mt-2 text-xs text-stone-400">更新于 {formatAnnouncementTime(item.updated_at || item.created_at)}</p>
                </div>
                <div className="flex shrink-0 items-start gap-1">
                  <Button variant="ghost" size="icon" aria-label="编辑公告" title="编辑公告" onClick={() => openEdit(item)}>
                    <Pencil className="size-4" />
                  </Button>
                  <Button variant="ghost" size="icon" aria-label="删除公告" title="删除公告" onClick={() => setDeleting(item)}>
                    <Trash2 className="size-4 text-red-500" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="mt-5 grid min-h-72 place-items-center rounded-lg border border-dashed border-stone-300 bg-white text-center">
            <div>
              <Bell className="mx-auto size-8 text-stone-300" />
              <p className="mt-3 text-sm font-medium text-stone-700">还没有公告</p>
              <Button className="mt-4" variant="outline" onClick={openCreate}>
                <Plus className="size-4" />
                新建第一条公告
              </Button>
            </div>
          </div>
        )}
      </div>

      <Dialog open={editing !== undefined} onOpenChange={(open) => !open && setEditing(undefined)}>
        <DialogContent className="sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>{editing ? "编辑公告" : "新建公告"}</DialogTitle>
            <DialogDescription>公告保存后，已发布内容会立即出现在用户公告中心。</DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-1">
            <label className="grid gap-1.5 text-sm font-medium text-stone-700">
              标题
              <Input maxLength={120} value={draft.title} onChange={(event) => setDraft((current) => ({ ...current, title: event.target.value }))} placeholder="输入公告标题" />
            </label>
            <label className="grid gap-1.5 text-sm font-medium text-stone-700">
              分类
              <Select value={draft.category} onValueChange={(value) => setDraft((current) => ({ ...current, category: value as AnnouncementCategory }))}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  {ANNOUNCEMENT_CATEGORY_OPTIONS.map((option) => <SelectItem key={option.value} value={option.value}>{option.label}</SelectItem>)}
                </SelectContent>
              </Select>
            </label>
            <label className="grid gap-1.5 text-sm font-medium text-stone-700">
              正文
              <Textarea maxLength={10000} value={draft.content} onChange={(event) => setDraft((current) => ({ ...current, content: event.target.value }))} placeholder="输入公告正文" className="min-h-40" />
            </label>
            <div className="grid gap-3 rounded-lg border border-stone-200 bg-stone-50 px-4 py-3 sm:grid-cols-2">
              <label className="flex cursor-pointer items-start gap-3 text-sm">
                <Checkbox checked={draft.enabled} onCheckedChange={(checked) => setDraft((current) => ({ ...current, enabled: checked === true }))} />
                <span><span className="block font-medium text-stone-800">立即发布</span><span className="mt-0.5 block text-xs text-stone-500">关闭后保存为草稿</span></span>
              </label>
              <label className="flex cursor-pointer items-start gap-3 text-sm">
                <Checkbox checked={draft.popup} onCheckedChange={(checked) => setDraft((current) => ({ ...current, popup: checked === true }))} />
                <span><span className="block font-medium text-stone-800">弹窗提示</span><span className="mt-0.5 block text-xs text-stone-500">每个版本向用户提示一次</span></span>
              </label>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditing(undefined)}>取消</Button>
            <Button disabled={isSaving} onClick={() => void saveDraft()}>
              {isSaving ? <LoaderCircle className="size-4 animate-spin" /> : <CheckCircle2 className="size-4" />}
              保存公告
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(deleting)} onOpenChange={(open) => !open && setDeleting(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>删除公告</DialogTitle>
            <DialogDescription>确认删除“{deleting?.title}”吗？此操作无法撤销。</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleting(null)}>取消</Button>
            <Button variant="destructive" disabled={isSaving} onClick={() => void deleteAnnouncement()}>
              {isSaving ? <LoaderCircle className="size-4 animate-spin" /> : <Trash2 className="size-4" />}
              删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}

export default function AnnouncementsPage() {
  const { isCheckingAuth, session } = useAuthGuard();
  if (isCheckingAuth || !session) {
    return <div className="grid h-full place-items-center"><LoaderCircle className="size-5 animate-spin text-stone-400" /></div>;
  }
  return session.role === "admin" ? <AdminAnnouncements /> : <UserAnnouncements />;
}
