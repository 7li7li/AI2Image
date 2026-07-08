"use client";

import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import {
  BadgeDollarSign,
  FileText,
  Gift,
  Image,
  Images,
  LogOut,
  MessagesSquare,
  PenLine,
  Settings,
  Sparkles,
  User,
  Users,
  Waypoints,
  type LucideIcon,
} from "lucide-react";

import webConfig from "@/constants/common-env";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { fetchMe, type CurrentUser } from "@/lib/api";
import { getRouteHref, normalizeAppPath } from "@/lib/routes";
import { useSiteSettingsStore } from "@/lib/site-settings";
import { cn } from "@/lib/utils";
import { clearStoredAuthSession, getStoredAuthSession, type StoredAuthSession } from "@/store/auth";

type NavItem = {
  href: string;
  label: string;
  icon: LucideIcon;
};

type QuotaSummary = {
  value: string;
  spentLabel: string;
  expiryLabel: string;
};

const QUOTA_REFRESH_EVENT = "yanai:quota-refresh";

const UNKNOWN_QUOTA_SUMMARY: QuotaSummary = {
  value: "--",
  spentLabel: "",
  expiryLabel: "",
};

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
  return {
    value: String(user.quota ?? 0),
    spentLabel: `已消耗 ${user.spent_quota ?? user.quota_used ?? 0} 点`,
    expiryLabel: user.quota_expires_at ? `有效期至 ${formatQuotaTime(user.quota_expires_at)}` : "额度长期有效",
  };
}

function getStoredQuotaSummary(session: StoredAuthSession | null | undefined): QuotaSummary {
  if (session?.role === "user" && typeof session.quota === "number") {
    return {
      ...UNKNOWN_QUOTA_SUMMARY,
      value: String(session.quota),
    };
  }
  return UNKNOWN_QUOTA_SUMMARY;
}

const adminNavItems = [
  { href: "/chat", label: "对话", icon: MessagesSquare },
  { href: "/image", label: "画图", icon: Sparkles },
  { href: "/users", label: "用户", icon: Users },
  { href: "/prompt-manager", label: "提示词", icon: PenLine },
  { href: "/image-manager", label: "图库", icon: Images },
  { href: "/channels", label: "渠道", icon: Waypoints },
  { href: "/models", label: "模型", icon: BadgeDollarSign },
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
  const siteTitle = useSiteSettingsStore((state) => state.settings.site_title);
  const siteIcon = useSiteSettingsStore((state) => state.settings.site_icon);
  const [failedSiteIcon, setFailedSiteIcon] = useState("");
  const normalizedSiteIcon = siteIcon.trim();
  const showSiteIcon = Boolean(normalizedSiteIcon && failedSiteIcon !== normalizedSiteIcon);
  const brandMark = siteTitle.trim().slice(0, 1) || "颜";

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

  const handleLogout = async () => {
    await clearStoredAuthSession();
    window.location.replace(getRouteHref("/login"));
  };

  if (normalizedPathname === "/login" || session === undefined || !session) {
    return null;
  }

  const navItems = session.role === "admin" ? adminNavItems : userNavItems;
  const roleLabel = session.role === "admin" ? "管理员" : "个人用户";
  const profileActive = normalizedPathname === "/profile";
  const quotaSpentLabel = quotaSummary.spentLabel || "已消耗 -- 点";
  const quotaExpiryLabel = quotaSummary.expiryLabel || "有效期 --";

  return (
    <aside className="flex h-full w-[72px] shrink-0 flex-col items-center border-r border-stone-200/70 bg-white/92 px-2 py-4 backdrop-blur-xl sm:w-[76px]">
      <a
        href={getRouteHref("/image")}
        className="group grid size-11 shrink-0 place-items-center overflow-hidden rounded-lg transition hover:bg-stone-100"
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

      <div className="mt-2 w-full text-center text-[10px] font-semibold leading-tight text-stone-500">
        <span className="block truncate">ikun</span>
        <span className="block truncate">studio</span>
      </div>

      <nav className="hide-scrollbar mt-5 flex min-h-0 w-full flex-1 flex-col items-center justify-center gap-1 overflow-y-auto">
        {navItems.map((item) => {
          const active = normalizedPathname === item.href;
          const Icon = item.icon;
          return (
            <a
              key={item.href}
              href={getRouteHref(item.href)}
              title={item.label}
              className={cn(
                "group flex min-h-[54px] w-full flex-col items-center justify-center gap-1 rounded-lg px-1 text-center text-[11px] font-medium leading-none transition",
                active
                  ? "bg-stone-950 text-white shadow-sm"
                  : "text-stone-500 hover:bg-stone-100 hover:text-stone-950",
              )}
            >
              <Icon className={cn("size-5", active ? "text-white" : "text-stone-700 group-hover:text-stone-950")} />
              <span className="max-w-full truncate">{item.label}</span>
            </a>
          );
        })}
      </nav>

      <div className="mt-4 flex w-full shrink-0 flex-col items-center gap-1.5">
        {session.role === "user" ? (
          <>
            <Popover>
              <PopoverTrigger asChild>
                <button
                  type="button"
                  className="flex min-h-[56px] w-full flex-col items-center justify-center gap-1 rounded-lg border border-stone-200 bg-white px-1 text-center text-[11px] font-medium leading-none text-stone-500 shadow-sm transition hover:bg-sky-50 hover:text-sky-700"
                  title={`剩余额度 ${quotaSummary.value}`}
                  aria-label={`剩余额度 ${quotaSummary.value}`}
                >
                  <span className="flex max-w-full items-center justify-center gap-1">
                    <Sparkles className="size-4 shrink-0 text-sky-600" />
                    <span className="min-w-0 truncate text-xs font-bold text-sky-600">{quotaSummary.value}</span>
                  </span>
                  <span className="h-px w-8 bg-stone-200" aria-hidden="true" />
                  <span className="max-w-full truncate text-[10px] text-sky-600">{roleLabel}</span>
                </button>
              </PopoverTrigger>
              <PopoverContent side="right" align="end" sideOffset={10} className="w-60 p-3">
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
                  <span className="text-stone-400">有效期</span>
                  <span className="truncate text-right font-medium text-stone-700" title={quotaExpiryLabel}>
                    {quotaExpiryLabel}
                  </span>
                </div>
              </PopoverContent>
            </Popover>
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
