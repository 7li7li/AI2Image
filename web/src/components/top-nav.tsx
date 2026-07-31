"use client";

import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import {
  BadgeDollarSign,
  Bell,
  CreditCard,
  ExternalLink,
  FileText,
  Gift,
  Image,
  Images,
  LogOut,
  MessagesSquare,
  PenLine,
  ReceiptText,
  Settings,
  ShoppingCart,
  Sparkles,
  User,
  Users,
  Waypoints,
  type LucideIcon,
} from "lucide-react";

import webConfig from "@/constants/common-env";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { fetchMe, fetchPublicSettings, type CurrentUser, type PublicSiteSettings } from "@/lib/api";
import { getRouteHref, normalizeAppPath } from "@/lib/routes";
import { useSiteSettingsStore } from "@/lib/site-settings";
import { cn } from "@/lib/utils";
import { clearStoredAuthSession, getStoredAuthSession, type StoredAuthSession } from "@/store/auth";
import { isAnnouncementUnread, useAnnouncementStore } from "@/store/announcements";

type NavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
};

type QuotaSummary = {
  value: string;
  compactValue: string;
  spentLabel: string;
  expiryLabel: string;
  subscriptionLabel: string;
  concurrencyLabel: string;
  subscriptionExpiryLabel: string;
  showQuotaExpiry: boolean;
};

type QuotaPurchaseTarget = {
  href: string;
  label: string;
  external: boolean;
};

const QUOTA_REFRESH_EVENT = "yanai:quota-refresh";

const UNKNOWN_QUOTA_SUMMARY: QuotaSummary = {
  value: "--",
  compactValue: "--",
  spentLabel: "",
  expiryLabel: "",
  subscriptionLabel: "",
  concurrencyLabel: "",
  subscriptionExpiryLabel: "",
  showQuotaExpiry: false,
};

function formatQuotaValues(value: unknown) {
  const parsed = Number(value ?? 0);
  const normalized = Number.isFinite(parsed) ? Math.max(0, parsed) : 0;
  return {
    value: String(normalized),
    compactValue: String(Math.floor(normalized)),
  };
}

function formatQuotaTime(value?: string | null) {
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

function getQuotaSummary(user: CurrentUser): QuotaSummary {
  const quotaExpiry = user.quota_expires_at ? formatQuotaTime(user.quota_expires_at) : "";
  const subscriptionExpiry = user.subscription?.expires_at ? formatQuotaTime(user.subscription.expires_at) : "";
  return {
    ...formatQuotaValues(user.quota),
    spentLabel: `已消耗 ${user.spent_quota ?? user.quota_used ?? 0} 点`,
    expiryLabel: quotaExpiry ? `有效期至 ${quotaExpiry}` : "额度长期有效",
    subscriptionLabel: user.subscription?.plan_name || user.subscription?.plan_id || "未订阅",
    concurrencyLabel: `${Math.max(1, Number(user.task_concurrency ?? user.subscription_concurrency) || 1)} 个任务`,
    subscriptionExpiryLabel: subscriptionExpiry,
    showQuotaExpiry: !subscriptionExpiry || quotaExpiry !== subscriptionExpiry,
  };
}

function getStoredQuotaSummary(session: StoredAuthSession | null | undefined): QuotaSummary {
  if (session?.role === "user" && typeof session.quota === "number") {
    return {
      ...UNKNOWN_QUOTA_SUMMARY,
      ...formatQuotaValues(session.quota),
    };
  }
  return UNKNOWN_QUOTA_SUMMARY;
}

function safeConfiguredHref(value: string) {
  const href = value.trim();
  if (/^(https?:|mailto:|\/)/i.test(href)) {
    return href;
  }
  if (!/[\s<>]/.test(href) && /^[\w.-]+\.[a-z]{2,}(?::\d+)?(?:[/?#]|$)/i.test(href)) {
    return `https://${href}`;
  }
  return "";
}

function isExternalHref(href: string) {
  return /^(https?:|mailto:)/i.test(href);
}

function getQuotaPurchaseTarget(
  settings: Pick<PublicSiteSettings, "quota_purchase_url" | "quota_purchase_mode">,
): QuotaPurchaseTarget | null {
  if (settings.quota_purchase_mode === "subscription") {
    return {
      href: getRouteHref("/subscription"),
      label: "购买订阅",
      external: false,
    };
  }

  const href = safeConfiguredHref(settings.quota_purchase_url);
  if (!href) {
    return null;
  }
  return {
    href,
    label: "购买额度",
    external: isExternalHref(href),
  };
}

const adminNavItems = [
  { href: "/chat", label: "对话", icon: MessagesSquare },
  { href: "/image", label: "画图", icon: Sparkles },
  { href: "/image-manager", label: "图库", icon: Images },
  { href: "/prompt-manager", label: "提示词", icon: PenLine },
  { href: "/announcements", label: "公告", icon: Bell },
  { href: "/users", label: "用户", icon: Users },
  { href: "/channels", label: "渠道", icon: Waypoints },
  { href: "/models", label: "模型", icon: BadgeDollarSign },
  { href: "/subscriptions", label: "订阅", icon: CreditCard },
  { href: "/subscription-orders", label: "订单", icon: ReceiptText },
  { href: "/redeem-codes", label: "兑换码", icon: Gift },
  { href: "/logs", label: "日志", icon: FileText },
  { href: "/settings", label: "设置", icon: Settings },
] satisfies NavItem[];

const userNavItems = [
  { href: "/chat", label: "对话", icon: MessagesSquare },
  { href: "/image", label: "画图", icon: Sparkles },
  { href: "/my-images", label: "图库", icon: Image },
  { href: "/prompt-manager", label: "提示词", icon: PenLine },
] satisfies NavItem[];

export function TopNav() {
  const pathname = usePathname();
  const normalizedPathname = normalizeAppPath(pathname);
  const [session, setSession] = useState<StoredAuthSession | null | undefined>(undefined);
  const [quotaSummary, setQuotaSummary] = useState<QuotaSummary>(UNKNOWN_QUOTA_SUMMARY);
  const announcements = useAnnouncementStore((state) => state.items);
  const announcementReadVersions = useAnnouncementStore((state) => state.readVersions);
  const loadAnnouncements = useAnnouncementStore((state) => state.load);
  const siteTitle = useSiteSettingsStore((state) => state.settings.site_title);
  const siteIcon = useSiteSettingsStore((state) => state.settings.site_icon);
  const quotaPurchaseUrl = useSiteSettingsStore((state) => state.settings.quota_purchase_url);
  const quotaPurchaseMode = useSiteSettingsStore((state) => state.settings.quota_purchase_mode);
  const setSiteSettings = useSiteSettingsStore((state) => state.setSettings);
  const [failedSiteIcon, setFailedSiteIcon] = useState("");
  const [isRefreshingPurchaseSettings, setIsRefreshingPurchaseSettings] = useState(false);
  const [quotaPurchaseSettingsOverride, setQuotaPurchaseSettingsOverride] = useState<Pick<
    PublicSiteSettings,
    "quota_purchase_url" | "quota_purchase_mode"
  > | null>(null);
  const normalizedSiteIcon = siteIcon.trim();
  const showSiteIcon = Boolean(normalizedSiteIcon && failedSiteIcon !== normalizedSiteIcon);
  const brandMark = siteTitle.trim().slice(0, 1) || "颜";
  const quotaPurchaseTarget = getQuotaPurchaseTarget(
    quotaPurchaseSettingsOverride ?? {
      quota_purchase_url: quotaPurchaseUrl,
      quota_purchase_mode: quotaPurchaseMode,
    },
  );

  useEffect(() => {
    let active = true;

    const load = async () => {
      if (normalizedPathname === "/login") {
        if (active) setSession(null);
        return;
      }
      const storedSession = await getStoredAuthSession();
      if (!active) {
        return;
      }
      setSession(storedSession);
      setQuotaSummary(getStoredQuotaSummary(storedSession));
    };

    void load();
    return () => {
      active = false;
    };
  }, [normalizedPathname]);

  useEffect(() => {
    if (!session || session.role !== "user") {
      return;
    }

    let active = true;

    const loadQuota = async () => {
      try {
        const data = await fetchMe();
        if (active) {
          setQuotaSummary(getQuotaSummary(data.user));
        }
      } catch {
        if (active) {
          setQuotaSummary((current) => (current.value === UNKNOWN_QUOTA_SUMMARY.value ? UNKNOWN_QUOTA_SUMMARY : current));
        }
      }
    };

    void loadQuota();
    window.addEventListener("focus", loadQuota);
    window.addEventListener(QUOTA_REFRESH_EVENT, loadQuota);
    return () => {
      active = false;
      window.removeEventListener("focus", loadQuota);
      window.removeEventListener(QUOTA_REFRESH_EVENT, loadQuota);
    };
  }, [session]);

  useEffect(() => {
    if (session?.role !== "user") return;
    void loadAnnouncements().catch(() => undefined);
  }, [loadAnnouncements, session]);

  useEffect(() => {
    if (!session || session.role !== "user") {
      return;
    }

    let active = true;

    const loadPurchaseSettings = async () => {
      try {
        const data = await fetchPublicSettings();
        if (active) {
          setSiteSettings(data.settings);
          setQuotaPurchaseSettingsOverride(data.settings);
        }
      } catch {
        if (active) {
          setQuotaPurchaseSettingsOverride(null);
        }
      }
    };

    void loadPurchaseSettings();
    return () => {
      active = false;
    };
  }, [session, setSiteSettings]);

  const handleLogout = async () => {
    await clearStoredAuthSession();
    window.location.replace(getRouteHref("/login"));
  };

  const handleQuotaPopoverOpenChange = (open: boolean) => {
    if (open) {
      setIsRefreshingPurchaseSettings(true);
      void (async () => {
        try {
          const data = await fetchPublicSettings();
          setSiteSettings(data.settings);
          setQuotaPurchaseSettingsOverride(data.settings);
        } catch {
          setQuotaPurchaseSettingsOverride(null);
        } finally {
          setIsRefreshingPurchaseSettings(false);
        }
      })();
    }
  };

  if (normalizedPathname === "/login" || session === undefined || !session) {
    return null;
  }

  const navItems = session.role === "admin" ? adminNavItems : userNavItems;
  const roleLabel = session.role === "admin" ? "管理员" : "个人用户";
  const announcementActive = normalizedPathname === "/announcements";
  const profileActive = normalizedPathname === "/profile";
  const quotaSpentLabel = quotaSummary.spentLabel || "已消耗 -- 点";
  const quotaExpiryLabel = quotaSummary.expiryLabel || "有效期 --";
  const subscriptionLabel = quotaSummary.subscriptionLabel || "未订阅";
  const concurrencyLabel = quotaSummary.concurrencyLabel || "--";
  const subscriptionExpiryLabel = quotaSummary.subscriptionExpiryLabel || "--";
  const quotaButtonLabel = quotaSummary.subscriptionExpiryLabel ? subscriptionLabel : roleLabel;
  const unreadAnnouncementCount = announcements.filter((item) =>
    isAnnouncementUnread(item, announcementReadVersions),
  ).length;

  return (
    <aside className="flex h-full w-[72px] shrink-0 flex-col items-center border-r border-stone-200/70 bg-white/92 px-2 py-4 backdrop-blur-xl sm:w-[76px]">
      <a
        href={getRouteHref("/image")}
        className="group grid h-9 w-11 shrink-0 place-items-center overflow-hidden rounded-lg transition hover:bg-stone-100"
        title={siteTitle}
        aria-label={siteTitle}
      >
        <span
          className={cn(
            "grid size-9 place-items-center overflow-hidden rounded-lg transition group-hover:brightness-105",
            showSiteIcon ? "bg-white p-1" : "yan-mark-gradient text-sm font-black text-white",
          )}
        >
          {showSiteIcon ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={normalizedSiteIcon} alt="" className="size-full object-contain" onError={() => setFailedSiteIcon(normalizedSiteIcon)} />
          ) : (
            brandMark
          )}
        </span>
      </a>

      <div className="mt-0.5 w-full text-center text-[10px] font-semibold leading-tight text-stone-500">
        <span className="block truncate">ikun</span>
        <span className="block truncate">studio</span>
      </div>

      <nav className="hide-scrollbar mt-5 min-h-0 w-full flex-1 overflow-y-auto">
        <div className="flex min-h-full w-full flex-col items-center justify-center gap-1 py-1">
          {navItems.map((item) => {
            const active = normalizedPathname === item.href;
            const Icon = item.icon;
            return (
              <a
                key={item.href}
                href={getRouteHref(item.href)}
                title={item.label}
                className={cn(
                  "group relative flex min-h-[54px] w-full flex-col items-center justify-center gap-1 rounded-lg px-1 text-center text-[11px] font-medium leading-none transition",
                  active
                    ? "bg-stone-950 text-white shadow-sm"
                    : "text-stone-500 hover:bg-stone-100 hover:text-stone-950",
                )}
              >
                <Icon className={cn("size-5", active ? "text-white" : "text-stone-700 group-hover:text-stone-950")} />
                {item.href === "/announcements" && session.role === "user" && unreadAnnouncementCount > 0 ? (
                  <span className="absolute top-1.5 right-2.5 grid min-w-4 place-items-center rounded-full bg-red-500 px-1 text-[9px] font-bold leading-4 text-white shadow-sm">
                    {unreadAnnouncementCount > 99 ? "99+" : unreadAnnouncementCount}
                  </span>
                ) : null}
                <span className="max-w-full truncate">{item.label}</span>
              </a>
            );
          })}
        </div>
      </nav>

      <div className="mt-4 flex w-full shrink-0 flex-col items-center gap-1.5">
        {session.role === "user" ? (
          <>
            <Popover onOpenChange={handleQuotaPopoverOpenChange}>
              <PopoverTrigger asChild>
                <button
                  type="button"
                  className="flex min-h-[56px] w-full flex-col items-center justify-center gap-1 rounded-lg border border-stone-200 bg-white px-1 text-center text-[11px] font-medium leading-none text-stone-500 shadow-sm transition hover:bg-sky-50 hover:text-sky-700"
                  title={`剩余额度 ${quotaSummary.value} · ${quotaButtonLabel}`}
                  aria-label={`剩余额度 ${quotaSummary.value}，${quotaButtonLabel}`}
                >
                  <span className="flex max-w-full items-center justify-center gap-1">
                    <Sparkles className="size-4 shrink-0 text-sky-600" />
                    <span className="min-w-0 truncate text-xs font-bold text-sky-600">{quotaSummary.compactValue}</span>
                  </span>
                  <span className="h-px w-8 bg-stone-200" aria-hidden="true" />
                  <span className="max-w-full truncate text-[10px] text-sky-600" title={quotaButtonLabel}>
                    {quotaButtonLabel}
                  </span>
                </button>
              </PopoverTrigger>
              <PopoverContent side="right" align="end" sideOffset={10} className="w-64 p-3">
                <div className="text-sm font-semibold text-stone-950">本地额度</div>
                <div className="mt-2 flex items-end gap-1">
                  <span className="text-3xl font-bold tracking-tight text-stone-950">{quotaSummary.value}</span>
                  <span className="pb-1 text-xs font-medium text-stone-400">剩余</span>
                </div>
                <div className="mt-3 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-2 text-xs">
                  <span className="text-stone-400">消耗</span>
                  <span className="truncate text-right font-medium text-stone-700" title={quotaSpentLabel}>
                    {quotaSpentLabel}
                  </span>
                  {quotaSummary.showQuotaExpiry ? (
                    <>
                      <span className="text-stone-400">额度有效期</span>
                      <span className="truncate text-right font-medium text-stone-700" title={quotaExpiryLabel}>
                        {quotaExpiryLabel}
                      </span>
                    </>
                  ) : null}
                  <span className="text-stone-400">当前订阅</span>
                  <span className="truncate text-right font-medium text-stone-700" title={subscriptionLabel}>
                    {subscriptionLabel}
                  </span>
                  <span className="text-stone-400">任务并发</span>
                  <span className="truncate text-right font-medium text-stone-700">{concurrencyLabel}</span>
                  {quotaSummary.subscriptionExpiryLabel ? (
                    <>
                      <span className="text-stone-400">订阅到期</span>
                      <span className="truncate text-right font-medium text-stone-700" title={subscriptionExpiryLabel}>
                        {subscriptionExpiryLabel}
                      </span>
                    </>
                  ) : null}
                </div>
                {isRefreshingPurchaseSettings ? (
                  <div className="mt-3 flex h-10 w-full items-center justify-center rounded-lg bg-stone-100 px-3 text-sm font-medium text-stone-500">
                    正在加载购买入口
                  </div>
                ) : quotaPurchaseTarget ? (
                  <a
                    href={quotaPurchaseTarget.href}
                    target={quotaPurchaseTarget.external ? "_blank" : undefined}
                    rel={quotaPurchaseTarget.external ? "noreferrer" : undefined}
                    className="mt-3 inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg bg-stone-950 px-3 text-sm font-medium text-white transition hover:bg-stone-800"
                  >
                    <ShoppingCart className="size-4" />
                    <span>{quotaPurchaseTarget.label}</span>
                    {quotaPurchaseTarget.external ? <ExternalLink className="size-3.5 opacity-70" /> : null}
                  </a>
                ) : null}
              </PopoverContent>
            </Popover>
            <a
              href={getRouteHref("/announcements")}
              title="系统公告"
              className={cn(
                "group relative flex min-h-[54px] w-full flex-col items-center justify-center gap-1 rounded-lg px-1 text-center text-[11px] font-medium leading-none transition",
                announcementActive
                  ? "bg-stone-950 text-white shadow-sm"
                  : "text-stone-500 hover:bg-stone-100 hover:text-stone-950",
              )}
            >
              <Bell
                className={cn(
                  "size-5",
                  announcementActive ? "text-white" : "text-stone-700 group-hover:text-stone-950",
                )}
              />
              {unreadAnnouncementCount > 0 ? (
                <span className="absolute top-1.5 right-2.5 grid min-w-4 place-items-center rounded-full bg-red-500 px-1 text-[9px] font-bold leading-4 text-white shadow-sm">
                  {unreadAnnouncementCount > 99 ? "99+" : unreadAnnouncementCount}
                </span>
              ) : null}
              <span className="max-w-full truncate">系统公告</span>
            </a>
            <a
              href={getRouteHref("/profile")}
              title={`个人中心 · v${webConfig.appVersion}`}
              className={cn(
                "group flex min-h-[54px] w-full flex-col items-center justify-center gap-1 rounded-lg px-1 text-center text-[11px] font-medium leading-none transition",
                profileActive
                  ? "bg-stone-950 text-white shadow-sm"
                  : "text-stone-500 hover:bg-stone-100 hover:text-stone-950",
              )}
            >
              <User className={cn("size-5", profileActive ? "text-white" : "text-stone-700 group-hover:text-stone-950")} />
              <span className="max-w-full truncate">个人中心</span>
            </a>
          </>
        ) : (
          <Popover>
            <PopoverTrigger asChild>
              <button
                type="button"
                className="flex min-h-[56px] w-full flex-col items-center justify-center gap-1 rounded-lg border border-stone-200 bg-white px-1 text-center text-[11px] font-medium leading-none text-stone-500 shadow-sm transition hover:bg-stone-100 hover:text-stone-950"
                title={`${roleLabel} · v${webConfig.appVersion}`}
                aria-label={`${roleLabel}账号信息`}
              >
                <span className="grid size-5 shrink-0 place-items-center rounded-md bg-stone-100 text-[11px] font-bold text-stone-700">
                  {session.name.trim().slice(0, 1) || "管"}
                </span>
                <span className="h-px w-8 bg-stone-200" aria-hidden="true" />
                <span className="max-w-full truncate text-[10px]">{roleLabel}</span>
              </button>
            </PopoverTrigger>
            <PopoverContent side="right" align="end" sideOffset={10} className="w-60 p-3">
              <div className="text-sm font-semibold text-stone-950">{session.name || roleLabel}</div>
              {session.email ? <div className="mt-1 truncate text-xs text-stone-500">{session.email}</div> : null}
              <div className="mt-3 flex items-center justify-between border-t border-stone-100 pt-3 text-xs">
                <span className="text-stone-400">当前身份</span>
                <span className="font-medium text-stone-700">{roleLabel}</span>
              </div>
              <div className="mt-2 flex items-center justify-between text-xs">
                <span className="text-stone-400">版本</span>
                <span className="font-medium text-stone-700">v{webConfig.appVersion}</span>
              </div>
            </PopoverContent>
          </Popover>
        )}
        <button
          type="button"
          className="inline-flex size-9 items-center justify-center rounded-lg text-stone-500 transition hover:bg-stone-100 hover:text-stone-950"
          onClick={() => void handleLogout()}
          aria-label="退出登录"
          title="退出登录"
        >
          <LogOut className="size-4" />
        </button>
      </div>
    </aside>
  );
}
