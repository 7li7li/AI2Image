"use client";

import { useEffect, useState } from "react";
import {
  Copy,
  ExternalLink,
  Gift,
  LoaderCircle,
  MessagesSquare,
  Save,
  Sparkles,
} from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  fetchMe,
  redeemMyCode,
  updateMyProfile,
  type CurrentUser,
} from "@/lib/api";
import { useAuthGuard } from "@/lib/use-auth-guard";

function formatTime(value?: string | null) {
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

function hasDifferentExpiry(quotaExpiry?: string | null, subscriptionExpiry?: string | null) {
  if (!subscriptionExpiry) return true;
  return formatTime(quotaExpiry) !== formatTime(subscriptionExpiry);
}

function safeExternalLink(value?: string) {
  const candidate = String(value || "").trim();
  if (!candidate) return "";
  try {
    const url = new URL(candidate);
    return url.protocol === "http:" || url.protocol === "https:" ? candidate : "";
  } catch {
    return "";
  }
}

function QqIcon({ className }: { className?: string }) {
  return (
    <svg aria-hidden="true" className={className} fill="currentColor" viewBox="0 0 24 24">
      <path d="M21.395 15.035a40 40 0 0 0-.803-2.264l-1.079-2.695c.001-.032.014-.562.014-.836C19.526 4.632 17.351 0 12 0S4.474 4.632 4.474 9.241c0 .274.013.804.014.836l-1.08 2.695a39 39 0 0 0-.802 2.264c-1.021 3.283-.69 4.643-.438 4.673.54.065 2.103-2.472 2.103-2.472 0 1.469.756 3.387 2.394 4.771-.612.188-1.363.479-1.845.835-.434.32-.379.646-.301.778.343.578 5.883.369 7.482.189 1.6.18 7.14.389 7.483-.189.078-.132.132-.458-.301-.778-.483-.356-1.233-.646-1.846-.836 1.637-1.384 2.393-3.302 2.393-4.771 0 0 1.563 2.537 2.103 2.472.251-.03.581-1.39-.438-4.673" />
    </svg>
  );
}

function TelegramIcon({ className }: { className?: string }) {
  return (
    <svg aria-hidden="true" className={className} fill="currentColor" viewBox="0 0 24 24">
      <path d="M11.944 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0a12 12 0 0 0-.056 0zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z" />
    </svg>
  );
}

function ProfileContent() {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);

  const load = async () => {
    setIsLoading(true);
    try {
      const me = await fetchMe();
      setUser(me.user);
      setName(me.user.name || "");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "加载个人信息失败");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const handleSave = async () => {
    setIsSaving(true);
    try {
      const data = await updateMyProfile({ name: name.trim() });
      setUser(data.user);
      toast.success("资料已保存");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "保存失败");
    } finally {
      setIsSaving(false);
    }
  };

  const handleRedeem = async () => {
    try {
      const data = await redeemMyCode(code.trim());
      setUser(data.user);
      setCode("");
      const validText = data.redeem_code.valid_months > 0 ? `，有效期 ${data.redeem_code.valid_months} 个月` : "";
      toast.success(`兑换成功，增加 ${data.redeem_code.quota} 点额度${validText}`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "兑换失败");
    }
  };

  const handleCopyQqNumber = async (number: string) => {
    try {
      await navigator.clipboard.writeText(number);
      toast.success("QQ 群号已复制");
    } catch {
      toast.error("复制 QQ 群号失败");
    }
  };

  const qqGroup = user?.community_groups?.qq;
  const telegramGroup = user?.community_groups?.telegram;
  const qqNumber = String(qqGroup?.number || "").trim();
  const qqLink = safeExternalLink(qqGroup?.link);
  const telegramLink = safeExternalLink(telegramGroup?.link);
  const hasCommunityGroups = Boolean(qqNumber || qqLink || telegramLink);

  if (isLoading) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <LoaderCircle className="size-5 animate-spin text-stone-400" />
      </div>
    );
  }

  return (
    <section className="mx-auto h-full min-h-0 w-full max-w-5xl space-y-5 overflow-y-auto pr-1 pb-8 [scrollbar-color:rgba(115,115,115,.45)_transparent] [scrollbar-width:thin] [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-stone-300/55 [&::-webkit-scrollbar-track]:bg-transparent">
      <div className="space-y-1">
        <div className="text-xs font-semibold tracking-[0.18em] text-stone-400 uppercase">Profile</div>
        <h1 className="text-2xl font-semibold tracking-tight">个人中心</h1>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <Card className="rounded-lg border-white/80 bg-white/80 shadow-sm md:col-span-2">
          <CardContent className="space-y-5 p-6">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-sm text-stone-500">当前账号</div>
                <div className="mt-1 text-lg font-semibold text-stone-950">{user?.email}</div>
              </div>
              <Badge variant={user?.status === "disabled" ? "secondary" : "success"}>
                {user?.status === "disabled" ? "已禁用" : "正常"}
              </Badge>
            </div>
            <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
              <Input value={name} onChange={(event) => setName(event.target.value)} placeholder="昵称" className="h-11 rounded-xl border-stone-100 bg-white" />
              <Button className="h-11 rounded-xl bg-neutral-900 text-white hover:bg-black" onClick={() => void handleSave()} disabled={isSaving}>
                {isSaving ? <LoaderCircle className="size-4 animate-spin" /> : <Save className="size-4" />}
                保存资料
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card className="rounded-lg border-white/80 bg-white/80 shadow-sm">
          <CardContent className="space-y-2 p-6">
            <div className="rounded-2xl bg-stone-50 p-3 text-stone-500 w-fit">
              <Sparkles className="size-5" />
            </div>
            <div className="text-sm text-stone-500">可用额度</div>
            <div className="text-4xl font-semibold text-stone-600">{user?.quota ?? 0}</div>
            <div className="text-xs text-stone-400">已消耗 {user?.spent_quota ?? user?.quota_used ?? 0} 点</div>
            {hasDifferentExpiry(user?.quota_expires_at, user?.subscription?.expires_at) ? (
              <div className="text-xs text-stone-400">
                {user?.quota_expires_at ? `额度有效期至 ${formatTime(user.quota_expires_at)}` : "额度长期有效"}
              </div>
            ) : null}
            <div className="mt-4 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-2 border-t border-stone-100 pt-4 text-xs">
              <span className="text-stone-400">当前订阅</span>
              <span className="truncate text-right font-medium text-stone-700">
                {user?.subscription?.plan_name || user?.subscription?.plan_id || "未订阅"}
              </span>
              <span className="text-stone-400">任务并发</span>
              <span className="text-right font-medium text-stone-700">
                {Math.max(1, Number(user?.task_concurrency ?? user?.subscription_concurrency) || 1)} 个任务
              </span>
              {user?.subscription?.expires_at ? (
                <>
                  <span className="text-stone-400">订阅到期</span>
                  <span className="truncate text-right font-medium text-stone-700" title={formatTime(user.subscription.expires_at)}>
                    {formatTime(user.subscription.expires_at)}
                  </span>
                </>
              ) : null}
            </div>
          </CardContent>
        </Card>
      </div>

      {hasCommunityGroups ? (
        <Card className="rounded-lg border-white/80 bg-white/80 shadow-sm">
          <CardContent className="space-y-4 p-6">
            <div className="flex items-center gap-2 text-sm font-semibold text-stone-800">
              <MessagesSquare className="size-4 text-stone-500" />
              用户群组
            </div>
            <div className="divide-y divide-stone-100 rounded-lg border border-stone-100 bg-white">
              {qqNumber || qqLink ? (
                <div className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex min-w-0 items-center gap-3">
                    <div className="grid size-9 shrink-0 place-items-center rounded-lg bg-sky-50 text-[#1ebafc]">
                      <QqIcon className="size-5" />
                    </div>
                    <div className="min-w-0">
                      <div className="text-sm font-medium text-stone-800">QQ 群</div>
                      {qqNumber ? (
                        <div className="mt-1 flex min-w-0 items-center gap-1 text-xs text-stone-500">
                          <span className="truncate">群号：{qqNumber}</span>
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            className="size-7 shrink-0 text-stone-500 hover:text-stone-900"
                            onClick={() => void handleCopyQqNumber(qqNumber)}
                            aria-label="复制 QQ 群号"
                            title="复制 QQ 群号"
                          >
                            <Copy className="size-3.5" />
                          </Button>
                        </div>
                      ) : null}
                    </div>
                  </div>
                  {qqLink ? (
                    <Button asChild variant="outline" size="sm" className="w-full border-stone-200 sm:w-auto">
                      <a href={qqLink} target="_blank" rel="noopener noreferrer">
                        加入 QQ 群
                        <ExternalLink className="size-3.5" />
                      </a>
                    </Button>
                  ) : null}
                </div>
              ) : null}

              {telegramLink ? (
                <div className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex min-w-0 items-center gap-3">
                    <div className="grid size-9 shrink-0 place-items-center rounded-lg bg-sky-50 text-[#26a5e4]">
                      <TelegramIcon className="size-5" />
                    </div>
                    <div className="min-w-0">
                      <div className="text-sm font-medium text-stone-800">Telegram 群</div>
                      <div className="mt-1 text-xs text-stone-500">加入 Telegram 用户群</div>
                    </div>
                  </div>
                  <Button asChild variant="outline" size="sm" className="w-full border-stone-200 sm:w-auto">
                    <a href={telegramLink} target="_blank" rel="noopener noreferrer">
                      加入 TG 群
                      <ExternalLink className="size-3.5" />
                    </a>
                  </Button>
                </div>
              ) : null}
            </div>
          </CardContent>
        </Card>
      ) : null}

      <Card className="rounded-lg border-white/80 bg-white/80 shadow-sm">
        <CardContent className="space-y-4 p-6">
          <div className="flex items-center gap-2 text-sm font-semibold text-stone-800">
            <Gift className="size-4 text-stone-500" />
            兑换额度
          </div>
          <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
            <Input value={code} onChange={(event) => setCode(event.target.value)} placeholder="输入兑换码" className="h-11 rounded-xl border-stone-100 bg-white uppercase" />
            <Button className="h-11 rounded-xl bg-neutral-900 text-white hover:bg-black" onClick={() => void handleRedeem()}>
              立即兑换
            </Button>
          </div>
        </CardContent>
      </Card>
    </section>
  );
}

export default function ProfilePage() {
  const { isCheckingAuth, session } = useAuthGuard(["user"]);
  if (isCheckingAuth || !session) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <LoaderCircle className="size-5 animate-spin text-stone-400" />
      </div>
    );
  }
  return <ProfileContent />;
}
