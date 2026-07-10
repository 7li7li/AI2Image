"use client";

import { useCallback, useEffect, useState } from "react";
import { CalendarDays, CreditCard, LoaderCircle, ReceiptText, RefreshCw, Sparkles, XCircle } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  cancelSubscriptionOrder,
  createSubscriptionOrder,
  fetchMe,
  fetchMySubscriptionOrders,
  fetchPublicSettings,
  paySubscriptionOrder,
  type CurrentUser,
  type SubscriptionOrder,
  type SubscriptionPlan,
} from "@/lib/api";
import { getRouteHref } from "@/lib/routes";
import { useSiteSettingsStore } from "@/lib/site-settings";
import { useAuthGuard } from "@/lib/use-auth-guard";

const QUOTA_REFRESH_EVENT = "yanai:quota-refresh";
const ORDER_REFRESH_INTERVAL_MS = 8000;

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

function validityLabel(months: number) {
  return `${months} 个月`;
}

function orderStatusLabel(status?: string) {
  if (status === "paid") return "已支付";
  if (status === "pending") return "待支付";
  if (status === "canceled") return "已取消";
  return status || "-";
}

function orderStatusVariant(status?: string): "success" | "warning" | "danger" | "secondary" {
  if (status === "paid") return "success";
  if (status === "pending") return "warning";
  if (status === "canceled") return "danger";
  return "secondary";
}

function cancelReasonLabel(reason?: string) {
  if (reason === "timeout") return "超时取消";
  if (reason === "admin") return "管理员取消";
  return "已取消";
}

function orderTimeLabel(order: SubscriptionOrder) {
  if (order.status === "paid") {
    const paidAt = formatQuotaTime(order.paid_at);
    return paidAt ? `支付于 ${paidAt}` : "-";
  }
  if (order.status === "canceled") {
    const canceledAt = formatQuotaTime(order.canceled_at);
    return canceledAt ? `${cancelReasonLabel(order.cancel_reason)} · ${canceledAt}` : cancelReasonLabel(order.cancel_reason);
  }
  if (order.status === "pending") {
    const expiresAt = formatQuotaTime(order.expires_at);
    return expiresAt ? `支付截止 ${expiresAt}` : `创建于 ${formatQuotaTime(order.created_at)}`;
  }
  return formatQuotaTime(order.created_at) || "-";
}

function dispatchQuotaRefresh() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(QUOTA_REFRESH_EVENT));
  }
}

function openPaymentTab() {
  const tab = window.open("about:blank", "_blank");
  if (tab) {
    try {
      tab.opener = null;
    } catch {
      // Ignore browsers that disallow mutating opener.
    }
  }
  return tab;
}

function sendPaymentTabTo(tab: Window | null, url: string) {
  if (!tab || tab.closed) {
    return false;
  }
  tab.location.href = url;
  return true;
}

function closePaymentTab(tab: Window | null) {
  try {
    tab?.close();
  } catch {
    // Best effort only.
  }
}

function SubscriptionContent() {
  const setSiteSettings = useSiteSettingsStore((state) => state.setSettings);
  const [plans, setPlans] = useState<SubscriptionPlan[]>([]);
  const [orders, setOrders] = useState<SubscriptionOrder[]>([]);
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isOrdersLoading, setIsOrdersLoading] = useState(false);
  const [payingPlanId, setPayingPlanId] = useState("");
  const [payingOrderNo, setPayingOrderNo] = useState("");
  const [cancelingOrderNo, setCancelingOrderNo] = useState("");

  const refreshAccountAndOrders = useCallback(
    async (options: { showOrdersLoading?: boolean; showErrorToast?: boolean } = {}) => {
      if (options.showOrdersLoading) {
        setIsOrdersLoading(true);
      }
      try {
        const [me, ordersData] = await Promise.all([fetchMe(), fetchMySubscriptionOrders()]);
        setUser(me.user);
        setOrders(ordersData.items);
        dispatchQuotaRefresh();
      } catch (error) {
        if (options.showErrorToast) {
          toast.error(error instanceof Error ? error.message : "加载订单失败");
        }
      } finally {
        if (options.showOrdersLoading) {
          setIsOrdersLoading(false);
        }
      }
    },
    [],
  );

  const loadOrders = async () => {
    try {
      await refreshAccountAndOrders({ showOrdersLoading: true, showErrorToast: true });
    } catch {
      // refreshAccountAndOrders already handles visible errors.
    }
  };

  useEffect(() => {
    let active = true;

    const load = async () => {
      setPlans(useSiteSettingsStore.getState().settings.subscription_plans);
      setIsLoading(true);
      try {
        const [settingsData, me, ordersData] = await Promise.all([
          fetchPublicSettings(),
          fetchMe(),
          fetchMySubscriptionOrders(),
        ]);
        if (!active) {
          return;
        }
        setSiteSettings(settingsData.settings);
        setPlans(settingsData.settings.subscription_plans);
        setUser(me.user);
        setOrders(ordersData.items);
        dispatchQuotaRefresh();
      } catch (error) {
        if (active) {
          toast.error(error instanceof Error ? error.message : "加载订阅套餐失败");
        }
      } finally {
        if (active) {
          setIsLoading(false);
        }
      }
    };

    void load();
    return () => {
      active = false;
    };
  }, [setSiteSettings]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const params = new URLSearchParams(window.location.search);
    const paid = params.get("paid");
    if (paid === "1") {
      toast.success("支付成功，额度已到账");
      void refreshAccountAndOrders({ showErrorToast: false });
      window.history.replaceState(null, "", getRouteHref("/subscription"));
    } else if (paid === "0") {
      toast.error("支付未完成或回调校验失败");
      void refreshAccountAndOrders({ showErrorToast: false });
      window.history.replaceState(null, "", getRouteHref("/subscription"));
    }
  }, [refreshAccountAndOrders]);

  useEffect(() => {
    if (isLoading || typeof window === "undefined") {
      return;
    }

    let active = true;
    const refresh = () => {
      if (!active || document.visibilityState === "hidden") {
        return;
      }
      void refreshAccountAndOrders({ showErrorToast: false });
    };
    const interval = window.setInterval(refresh, ORDER_REFRESH_INTERVAL_MS);

    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      active = false;
      window.clearInterval(interval);
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [isLoading, refreshAccountAndOrders]);

  const payPlan = async (plan: SubscriptionPlan) => {
    if (payingPlanId || payingOrderNo || cancelingOrderNo) {
      return;
    }
    const paymentTab = openPaymentTab();
    if (!paymentTab) {
      toast.error("浏览器阻止了支付标签页，请允许弹窗后重试");
      return;
    }
    setPayingPlanId(plan.id);
    try {
      const data = await createSubscriptionOrder(plan.id);
      setOrders((current) => [data.order, ...current.filter((item) => item.out_trade_no !== data.order.out_trade_no)]);
      if (!sendPaymentTabTo(paymentTab, data.pay_url)) {
        toast.error("支付标签页已关闭，请重新点击支付");
      }
    } catch (error) {
      closePaymentTab(paymentTab);
      toast.error(error instanceof Error ? error.message : "创建支付订单失败");
    } finally {
      setPayingPlanId("");
    }
  };

  const payOrder = async (order: SubscriptionOrder) => {
    if (payingPlanId || payingOrderNo || cancelingOrderNo || order.status !== "pending") {
      return;
    }
    const paymentTab = openPaymentTab();
    if (!paymentTab) {
      toast.error("浏览器阻止了支付标签页，请允许弹窗后重试");
      return;
    }
    setPayingOrderNo(order.out_trade_no);
    try {
      const data = await paySubscriptionOrder(order.out_trade_no);
      setOrders((current) => current.map((item) => (item.out_trade_no === data.order.out_trade_no ? data.order : item)));
      if (!sendPaymentTabTo(paymentTab, data.pay_url)) {
        toast.error("支付标签页已关闭，请重新点击支付");
      }
    } catch (error) {
      closePaymentTab(paymentTab);
      toast.error(error instanceof Error ? error.message : "创建支付链接失败");
      void refreshAccountAndOrders({ showErrorToast: false });
    } finally {
      setPayingOrderNo("");
    }
  };

  const cancelOrder = async (order: SubscriptionOrder) => {
    if (payingPlanId || payingOrderNo || cancelingOrderNo || order.status !== "pending") {
      return;
    }
    if (typeof window !== "undefined" && !window.confirm("确认取消该待支付订单？")) {
      return;
    }
    setCancelingOrderNo(order.out_trade_no);
    try {
      const data = await cancelSubscriptionOrder(order.out_trade_no);
      setOrders((current) => current.map((item) => (item.out_trade_no === data.item.out_trade_no ? data.item : item)));
      toast.success(data.canceled ? "订单已取消" : "订单已是取消状态");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "取消订单失败");
      void refreshAccountAndOrders({ showErrorToast: false });
    } finally {
      setCancelingOrderNo("");
    }
  };

  if (isLoading) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <LoaderCircle className="size-5 animate-spin text-rose-400" />
      </div>
    );
  }

  return (
    <section className="mx-auto h-full min-h-0 w-full max-w-6xl space-y-5 overflow-y-auto pr-1 pb-8 [scrollbar-color:rgba(244,114,182,.45)_transparent] [scrollbar-width:thin] [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-rose-300/55 [&::-webkit-scrollbar-track]:bg-transparent">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div className="space-y-1">
          <div className="text-xs font-semibold tracking-[0.18em] text-rose-400 uppercase">Subscription</div>
          <h1 className="text-2xl font-semibold tracking-tight">订阅套餐</h1>
        </div>
        <Button asChild variant="outline" className="h-10 rounded-xl border-stone-200 bg-white px-4 text-stone-700">
          <a href={getRouteHref("/profile")}>返回个人中心</a>
        </Button>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_280px]">
        <div className="grid min-w-0 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {plans.length === 0 ? (
            <Card className="rounded-lg border-white/80 bg-white/80 shadow-sm md:col-span-2 xl:col-span-3">
              <CardContent className="flex min-h-48 flex-col items-center justify-center gap-3 p-6 text-center">
                <div className="grid size-11 place-items-center rounded-lg bg-stone-100 text-stone-500">
                  <CalendarDays className="size-5" />
                </div>
                <div className="text-sm font-medium text-stone-700">暂无可购买套餐</div>
              </CardContent>
            </Card>
          ) : (
            plans.map((plan) => (
              <Card key={plan.id} className="rounded-lg border-white/80 bg-white/80 shadow-sm">
                <CardContent className="flex h-full flex-col p-6">
                  <div className="min-h-14">
                    <div className="text-lg font-semibold text-stone-950">{plan.name}</div>
                    <div className="mt-1 text-xs text-stone-500">有效期 {validityLabel(plan.valid_months)}</div>
                  </div>
                  <div className="mt-5 flex items-end gap-2">
                    <span className="text-3xl font-bold tracking-tight text-stone-950">{plan.price}</span>
                    <span className="pb-1 text-xs font-medium text-stone-400">价格</span>
                  </div>
                  <div className="mt-5 grid gap-2 text-sm">
                    <div className="flex items-center justify-between rounded-lg bg-rose-50 px-3 py-2">
                      <span className="text-stone-500">额度</span>
                      <span className="font-semibold text-rose-600">{plan.quota} 点</span>
                    </div>
                    <div className="flex items-center justify-between rounded-lg bg-stone-50 px-3 py-2">
                      <span className="text-stone-500">到期时间</span>
                      <span className="font-semibold text-stone-800">{validityLabel(plan.valid_months)}</span>
                    </div>
                  </div>
                  <Button
                    className="mt-5 h-10 rounded-xl bg-stone-950 text-white hover:bg-stone-800"
                    onClick={() => void payPlan(plan)}
                    disabled={Boolean(payingPlanId || payingOrderNo || cancelingOrderNo)}
                  >
                    {payingPlanId === plan.id ? <LoaderCircle className="size-4 animate-spin" /> : <CreditCard className="size-4" />}
                    {payingPlanId === plan.id ? "正在跳转" : "立即支付"}
                  </Button>
                </CardContent>
              </Card>
            ))
          )}
        </div>

        <Card className="rounded-lg border-white/80 bg-white/80 shadow-sm">
          <CardContent className="space-y-3 p-6">
            <div className="w-fit rounded-lg bg-rose-50 p-3 text-rose-500">
              <Sparkles className="size-5" />
            </div>
            <div className="text-sm text-stone-500">当前可用额度</div>
            <div className="text-4xl font-semibold text-rose-600">{user?.quota ?? 0}</div>
            <div className="text-xs text-stone-400">已消耗 {user?.spent_quota ?? user?.quota_used ?? 0} 点</div>
            <div className="text-xs text-stone-400">
              {user?.quota_expires_at ? `有效期至 ${formatQuotaTime(user.quota_expires_at)}` : "额度长期有效"}
            </div>
          </CardContent>
        </Card>
      </div>

      <Card className="rounded-lg border-white/80 bg-white/80 shadow-sm">
        <CardContent className="p-0">
          <div className="flex items-center justify-between border-b border-stone-100 px-5 py-4">
            <div>
              <div className="flex items-center gap-2 text-base font-semibold text-stone-900">
                <ReceiptText className="size-4 text-rose-500" />
                我的订单
              </div>
              <div className="mt-1 text-xs text-stone-500">最近的订阅支付记录</div>
            </div>
            <Button
              variant="ghost"
              className="h-8 rounded-lg px-3 text-stone-500"
              onClick={() => void loadOrders()}
              disabled={isOrdersLoading}
            >
              <RefreshCw className={`size-4 ${isOrdersLoading ? "animate-spin" : ""}`} />
              刷新
            </Button>
          </div>

          {orders.length === 0 ? (
            <div className="flex min-h-36 flex-col items-center justify-center gap-3 px-6 py-12 text-center text-sm text-stone-500">
              <ReceiptText className="size-8 text-stone-300" />
              暂无订阅订单
            </div>
          ) : (
            <div className="divide-y divide-stone-100">
              {orders.map((order) => (
                <div key={order.out_trade_no} className="grid gap-3 px-5 py-4 text-sm lg:grid-cols-[1.2fr_0.9fr_0.8fr_0.8fr_1fr_auto] lg:items-center">
                  <div className="min-w-0">
                    <div className="truncate font-medium text-stone-900">{order.plan_name || order.plan_id}</div>
                    <div className="truncate font-mono text-xs text-stone-400">{order.out_trade_no}</div>
                  </div>
                  <div className="text-stone-600">
                    <span className="font-semibold text-rose-600">{order.money || order.price}</span>
                    <span className="ml-2 text-xs text-stone-400">{order.quota} 点</span>
                  </div>
                  <div className="text-xs text-stone-500">有效期 {order.valid_months} 个月</div>
                  <Badge variant={orderStatusVariant(order.status)} className="w-fit rounded-md">
                    {orderStatusLabel(order.status)}
                  </Badge>
                  <div className="text-xs text-stone-500 lg:text-right">
                    {orderTimeLabel(order)}
                  </div>
                  <div className="flex flex-wrap gap-2 lg:justify-end">
                    {order.status === "pending" ? (
                      <>
                        <Button
                          className="h-8 rounded-lg bg-stone-950 px-3 text-xs text-white hover:bg-stone-800"
                          onClick={() => void payOrder(order)}
                          disabled={Boolean(payingPlanId || payingOrderNo || cancelingOrderNo)}
                        >
                          {payingOrderNo === order.out_trade_no ? <LoaderCircle className="size-3.5 animate-spin" /> : <CreditCard className="size-3.5" />}
                          去支付
                        </Button>
                        <Button
                          variant="outline"
                          className="h-8 rounded-lg border-rose-100 bg-white px-3 text-xs text-rose-600 hover:bg-rose-50"
                          onClick={() => void cancelOrder(order)}
                          disabled={Boolean(payingPlanId || payingOrderNo || cancelingOrderNo)}
                        >
                          {cancelingOrderNo === order.out_trade_no ? <LoaderCircle className="size-3.5 animate-spin" /> : <XCircle className="size-3.5" />}
                          取消
                        </Button>
                      </>
                    ) : (
                      <span className="text-xs text-stone-400">-</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </section>
  );
}

export default function SubscriptionPage() {
  const { isCheckingAuth, session } = useAuthGuard(["user"]);
  if (isCheckingAuth || !session) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <LoaderCircle className="size-5 animate-spin text-rose-400" />
      </div>
    );
  }
  return <SubscriptionContent />;
}
