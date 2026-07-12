"use client";

import { useEffect, useState } from "react";
import { Gift, LoaderCircle, Save, Sparkles } from "lucide-react";
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
