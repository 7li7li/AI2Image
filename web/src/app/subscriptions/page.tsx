"use client";

import { useEffect, useState } from "react";
import { CreditCard, KeyRound, LoaderCircle, Plus, Save, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  fetchSettingsConfig,
  updateSettingsConfig,
  type PublicSiteSettings,
  type QuotaPurchaseMode,
  type SettingsConfig,
  type SettingsSubscriptionPlan,
  type SubscriptionPlan,
} from "@/lib/api";
import { applySiteSettings, useSiteSettingsStore } from "@/lib/site-settings";
import { useAuthGuard } from "@/lib/use-auth-guard";

function normalizeQuotaPurchaseMode(value: unknown): QuotaPurchaseMode {
  return value === "subscription" ? "subscription" : "url";
}

function strictBoundedNumber(value: unknown, min: number, max: number): number | null {
  if (value === "" || value === null || value === undefined) {
    return null;
  }
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    return null;
  }
  return Math.max(min, Math.min(max, Math.trunc(parsed)));
}

function normalizeSubscriptionPlans(value: unknown): SubscriptionPlan[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((plan, index) => {
      const item = plan && typeof plan === "object" ? (plan as Record<string, unknown>) : {};
      const quota = strictBoundedNumber(item.quota, 1, 1_000_000);
      const validMonths = strictBoundedNumber(item.valid_months, 1, 120);
      const price = String(item.price ?? "").trim();
      if (quota === null || validMonths === null || !price) {
        return null;
      }
      return {
        id: String(item.id || `plan-${index + 1}`).trim(),
        name: String(item.name || "").trim(),
        quota,
        valid_months: validMonths,
        price,
      };
    })
    .filter((plan): plan is SubscriptionPlan => plan !== null && Boolean(plan.id));
}

function syncPublicSiteSettings(config: SettingsConfig) {
  const settings: PublicSiteSettings = {
    site_title: String(config.site_title || "Image Studio"),
    site_icon: String(config.site_icon || "/favicon.ico"),
    site_background: String(config.site_background || ""),
    quota_purchase_url: String(config.quota_purchase_url || ""),
    quota_purchase_mode: normalizeQuotaPurchaseMode(config.quota_purchase_mode),
    subscription_plans: normalizeSubscriptionPlans(config.subscription_plans),
    default_image_model: String(config.default_image_model || "gpt-image-2"),
    default_text_model: String(config.default_text_model || "gpt-5.5"),
  };
  useSiteSettingsStore.getState().setSettings(settings);
  applySiteSettings(settings);
}

function normalizeSettingsConfig(config: SettingsConfig): SettingsConfig {
  return {
    ...config,
    quota_purchase_mode: normalizeQuotaPurchaseMode(config.quota_purchase_mode),
    subscription_plans: normalizeSubscriptionPlans(config.subscription_plans),
    epay_enabled: config.epay_enabled === true,
    epay_url: String(config.epay_url || ""),
    epay_pid: String(config.epay_pid || ""),
    epay_key: "",
    epay_key_set: config.epay_key_set === true,
    epay_type: String(config.epay_type || ""),
    base_url: String(config.base_url || ""),
  };
}

function SubscriptionsContent() {
  const [config, setConfig] = useState<SettingsConfig | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const quotaPurchaseMode = normalizeQuotaPurchaseMode(config?.quota_purchase_mode);
  const subscriptionPlans = Array.isArray(config?.subscription_plans) ? config.subscription_plans : [];

  const load = async () => {
    setIsLoading(true);
    try {
      const data = await fetchSettingsConfig();
      setConfig(normalizeSettingsConfig(data.config));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "加载订阅配置失败");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const patchConfig = (updates: Partial<SettingsConfig>) => {
    setConfig((current) => (current ? { ...current, ...updates } : current));
  };

  const addSubscriptionPlan = () => {
    patchConfig({
      subscription_plans: [
        ...subscriptionPlans,
        {
          id: `plan-${Date.now()}`,
          name: "",
          quota: "100",
          valid_months: "1",
          price: "19.9",
        },
      ],
    });
  };

  const updateSubscriptionPlan = (index: number, updates: Partial<SettingsSubscriptionPlan>) => {
    patchConfig({
      subscription_plans: subscriptionPlans.map((plan, planIndex) =>
        planIndex === index ? { ...plan, ...updates } : plan,
      ),
    });
  };

  const removeSubscriptionPlan = (index: number) => {
    patchConfig({
      subscription_plans: subscriptionPlans.filter((_, planIndex) => planIndex !== index),
    });
  };

  const save = async () => {
    if (!config) {
      return;
    }
    setIsSaving(true);
    try {
      const payload: Partial<SettingsConfig> = {
        quota_purchase_url: String(config.quota_purchase_url || "").trim(),
        quota_purchase_mode: normalizeQuotaPurchaseMode(config.quota_purchase_mode),
        subscription_plans: normalizeSubscriptionPlans(config.subscription_plans),
        epay_enabled: config.epay_enabled === true,
        epay_url: String(config.epay_url || "").trim(),
        epay_pid: String(config.epay_pid || "").trim(),
        epay_key: String(config.epay_key || "").trim(),
        epay_type: String(config.epay_type || "").trim(),
        base_url: String(config.base_url || "").trim(),
      };
      const data = await updateSettingsConfig(payload);
      const nextConfig = normalizeSettingsConfig(data.config);
      setConfig(nextConfig);
      syncPublicSiteSettings(nextConfig);
      toast.success("订阅配置已保存");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "保存订阅配置失败");
    } finally {
      setIsSaving(false);
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
    <section className="h-full min-h-0 space-y-6 overflow-y-auto pr-1 pb-8 [scrollbar-color:rgba(148,163,184,.45)_transparent] [scrollbar-width:thin] [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-stone-300/65 [&::-webkit-scrollbar-track]:bg-transparent">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div className="space-y-1">
          <div className="text-xs font-semibold tracking-[0.18em] text-rose-400 uppercase">Billing</div>
          <h1 className="text-2xl font-semibold tracking-tight">订阅配置</h1>
        </div>
        <Button
          className="h-10 rounded-xl bg-stone-950 px-5 text-white hover:bg-stone-800"
          onClick={() => void save()}
          disabled={isSaving}
        >
          {isSaving ? <LoaderCircle className="size-4 animate-spin" /> : <Save className="size-4" />}
          保存
        </Button>
      </div>

      <Card className="rounded-lg border-white/80 bg-white/80 shadow-sm">
        <CardContent className="space-y-5 p-6">
          <div>
            <h2 className="text-base font-semibold text-stone-900">购买入口</h2>
            <p className="mt-1 text-sm text-stone-500">控制用户点击“购买额度”时打开外部链接，还是进入站内订阅套餐页。</p>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <label className="text-sm text-stone-700">入口类型</label>
              <Select
                value={quotaPurchaseMode}
                onValueChange={(value) => patchConfig({ quota_purchase_mode: value })}
              >
                <SelectTrigger className="h-10 rounded-xl border-stone-200 bg-white">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="url">使用额度购买链接</SelectItem>
                  <SelectItem value="subscription">使用订阅套餐页面</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <label className="text-sm text-stone-700">额度购买链接</label>
              <Input
                value={String(config?.quota_purchase_url || "")}
                onChange={(event) => patchConfig({ quota_purchase_url: event.target.value })}
                placeholder="https://example.com/billing"
                className="h-10 rounded-xl border-stone-200 bg-white"
              />
              <p className="text-xs text-stone-500">
                入口类型选择“使用额度购买链接”时生效；支持完整 URL 或站内路径。
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card className="rounded-lg border-white/80 bg-white/80 shadow-sm">
        <CardContent className="space-y-5 p-6">
          <div className="flex items-start gap-3">
            <div className="grid size-9 shrink-0 place-items-center rounded-lg bg-rose-50 text-rose-500">
              <KeyRound className="size-4" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-stone-900">Epay 支付</h2>
              <p className="mt-1 text-sm text-stone-500">配置订阅套餐的站内支付。启用后用户点击套餐会创建订单并跳转到 Epay。</p>
            </div>
          </div>

          <label className="flex w-fit items-center gap-2 text-sm text-stone-700">
            <Checkbox
              checked={config?.epay_enabled === true}
              onCheckedChange={(checked) => patchConfig({ epay_enabled: checked === true })}
            />
            启用 Epay 支付
          </label>

          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2 md:col-span-2">
              <label className="text-sm text-stone-700">站点公开地址（支付回调域名）</label>
              <Input
                value={String(config?.base_url || "")}
                onChange={(event) => patchConfig({ base_url: event.target.value })}
                placeholder="https://your-domain.com"
                className="h-10 rounded-xl border-stone-200 bg-white"
              />
              <p className="text-xs text-stone-500">
                用于生成 Epay notify_url / return_url，服务器部署建议填写公网 HTTPS 域名，不要填写 127.0.0.1 或内网地址。
              </p>
            </div>
            <div className="space-y-2">
              <label className="text-sm text-stone-700">支付网关地址</label>
              <Input
                value={String(config?.epay_url || "")}
                onChange={(event) => patchConfig({ epay_url: event.target.value })}
                placeholder="https://your-epay.example.com"
                className="h-10 rounded-xl border-stone-200 bg-white"
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm text-stone-700">支付方式（可选）</label>
              <Input
                value={String(config?.epay_type || "")}
                onChange={(event) => patchConfig({ epay_type: event.target.value })}
                placeholder="留空由 Epay 选择"
                className="h-10 rounded-xl border-stone-200 bg-white"
              />
              <p className="text-xs text-stone-500">需要固定通道时再填写，例如 alipay。</p>
            </div>
            <div className="space-y-2">
              <label className="text-sm text-stone-700">商户 ID</label>
              <Input
                value={String(config?.epay_pid || "")}
                onChange={(event) => patchConfig({ epay_pid: event.target.value })}
                placeholder="1001"
                className="h-10 rounded-xl border-stone-200 bg-white"
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm text-stone-700">商户密钥</label>
              <Input
                type="password"
                value={String(config?.epay_key || "")}
                onChange={(event) => patchConfig({ epay_key: event.target.value })}
                placeholder={config?.epay_key_set ? "已设置，留空保持不变" : "填写 Epay 通信密钥"}
                className="h-10 rounded-xl border-stone-200 bg-white"
              />
              <p className="text-xs text-stone-500">密钥不会回显；保存时留空会保留当前密钥。</p>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card className="rounded-lg border-white/80 bg-white/80 shadow-sm">
        <CardContent className="space-y-5 p-6">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <div className="flex items-center gap-2 text-base font-semibold text-stone-900">
                <CreditCard className="size-4 text-rose-500" />
                订阅套餐
              </div>
              <p className="mt-1 text-sm text-stone-500">配置用户端订阅页展示的额度、有效期和价格。</p>
            </div>
            <Button
              type="button"
              variant="outline"
              className="h-9 rounded-xl border-stone-200 bg-white px-3 text-stone-700"
              onClick={addSubscriptionPlan}
            >
              <Plus className="size-4" />
              添加套餐
            </Button>
          </div>

          <div className="space-y-3">
            {subscriptionPlans.length === 0 ? (
              <div className="rounded-xl border border-dashed border-stone-200 px-4 py-8 text-center text-sm text-stone-500">
                暂无订阅套餐
              </div>
            ) : (
              subscriptionPlans.map((plan, index) => (
                <div
                  key={`${plan.id}-${index}`}
                  className="grid gap-3 rounded-xl border border-stone-100 bg-stone-50/70 p-3 lg:grid-cols-[1.2fr_0.8fr_0.8fr_0.8fr_auto]"
                >
                  <div className="space-y-1.5">
                    <label className="text-xs font-medium text-stone-500">套餐名</label>
                    <Input
                      value={String(plan.name || "")}
                      onChange={(event) => updateSubscriptionPlan(index, { name: event.target.value })}
                      placeholder="基础套餐"
                      className="h-10 rounded-xl border-stone-200 bg-white"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-xs font-medium text-stone-500">额度</label>
                    <Input
                      type="number"
                      min={1}
                      max={1000000}
                      value={String(plan.quota ?? "")}
                      onChange={(event) => updateSubscriptionPlan(index, { quota: event.target.value })}
                      placeholder="100"
                      className="h-10 rounded-xl border-stone-200 bg-white"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-xs font-medium text-stone-500">有效期（月）</label>
                    <Input
                      type="number"
                      min={1}
                      max={120}
                      value={String(plan.valid_months ?? "")}
                      onChange={(event) => updateSubscriptionPlan(index, { valid_months: event.target.value })}
                      placeholder="1"
                      className="h-10 rounded-xl border-stone-200 bg-white"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <label className="text-xs font-medium text-stone-500">价格</label>
                    <Input
                      value={String(plan.price || "")}
                      onChange={(event) => updateSubscriptionPlan(index, { price: event.target.value })}
                      placeholder="19.9"
                      className="h-10 rounded-xl border-stone-200 bg-white"
                    />
                  </div>
                  <div className="flex items-end">
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="h-10 w-10 rounded-xl text-stone-400 hover:bg-rose-50 hover:text-rose-600"
                      onClick={() => removeSubscriptionPlan(index)}
                      aria-label="删除套餐"
                      title="删除套餐"
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  </div>
                </div>
              ))
            )}
          </div>
        </CardContent>
      </Card>
    </section>
  );
}

export default function SubscriptionsPage() {
  const { isCheckingAuth, session } = useAuthGuard(["admin"]);

  if (isCheckingAuth || !session || session.role !== "admin") {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <LoaderCircle className="size-5 animate-spin text-stone-400" />
      </div>
    );
  }

  return <SubscriptionsContent />;
}
