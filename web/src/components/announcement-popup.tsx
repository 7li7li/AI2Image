"use client";

import { useEffect, useMemo, useState } from "react";
import { Bell } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  announcementCategoryClassName,
  announcementCategoryLabel,
  formatAnnouncementTime,
  sortAnnouncements,
} from "@/lib/announcements";
import { getRouteHref } from "@/lib/routes";
import { getStoredAuthSession } from "@/store/auth";
import { isAnnouncementPopupPending, useAnnouncementStore } from "@/store/announcements";

export function AnnouncementPopup() {
  const items = useAnnouncementStore((state) => state.items);
  const isLoaded = useAnnouncementStore((state) => state.isLoaded);
  const dismissedVersions = useAnnouncementStore((state) => state.dismissedPopupVersions);
  const load = useAnnouncementStore((state) => state.load);
  const dismissPopup = useAnnouncementStore((state) => state.dismissPopup);
  const [canShow, setCanShow] = useState(false);

  useEffect(() => {
    let active = true;
    void getStoredAuthSession().then((session) => {
      if (!active || session?.role !== "user") return;
      setCanShow(true);
      void load().catch(() => undefined);
    });
    return () => {
      active = false;
    };
  }, [load]);

  const announcement = useMemo(
    () =>
      canShow && isLoaded
        ? sortAnnouncements(items).find((item) => isAnnouncementPopupPending(item, dismissedVersions)) || null
        : null,
    [canShow, dismissedVersions, isLoaded, items],
  );

  const handleClose = () => {
    if (announcement) dismissPopup(announcement);
  };

  return (
    <Dialog open={Boolean(announcement)} onOpenChange={(open) => !open && handleClose()}>
      <DialogContent className="max-h-[82vh] overflow-y-auto sm:max-w-lg">
        {announcement ? (
          <>
            <DialogHeader>
              <div className="mb-2 flex items-center gap-2">
                <span className="grid size-9 place-items-center rounded-xl bg-stone-950 text-white">
                  <Bell className="size-4" />
                </span>
                <Badge variant="outline" className={announcementCategoryClassName(announcement.category)}>
                  {announcementCategoryLabel(announcement.category)}
                </Badge>
              </div>
              <DialogTitle className="pr-8 text-left text-xl">{announcement.title}</DialogTitle>
              <DialogDescription className="text-left">
                {formatAnnouncementTime(announcement.updated_at || announcement.created_at)}
              </DialogDescription>
            </DialogHeader>
            <div className="whitespace-pre-wrap break-words rounded-xl bg-stone-50 px-4 py-4 text-sm leading-7 text-stone-700">
              {announcement.content}
            </div>
            <DialogFooter className="gap-2 sm:justify-between">
              <Button variant="outline" asChild>
                <a href={getRouteHref("/announcements")} onClick={handleClose}>
                  查看全部公告
                </a>
              </Button>
              <Button onClick={handleClose}>我知道了</Button>
            </DialogFooter>
          </>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
