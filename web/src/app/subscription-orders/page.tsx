"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { CheckCircle2, LoaderCircle, ReceiptText, RefreshCw, Search, Trash2, XCircle } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  cancelAdminSubscriptionOrder,
  deleteAdminCanceledSubscriptionOrders,
  fetchAdminSubscriptionOrders,
  updateAdminSubscriptionOrderStatus,
  type SubscriptionOrder,
} from "@/lib/api";
import { useAuthGuard } from "@/lib/use-auth-guard";

const OrderStatus = {
  All: "all",
  Pending: "pending",
  Paid: "paid",
  Canceled: "canceled",
} as const;

function normalizeOrderStatus(value: string) {
  const normalized = value.trim().toLowerCase();
  if (normalized === OrderStatus.Pending || normalized === OrderStatus.Paid || normalized === OrderStatus.Canceled) {
    return normalized;
  }
  return OrderStatus.All;
}

function formatTime(value?: string | null) {
  if (!value) return "-";
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

function statusLabel(status?: string) {
  if (status === "paid") return "已支付";
  if (status === "pending") return "待支付";
  if (status === "canceled") return "已取消";
  return status || "-";
}

function statusVariant(status?: string): "success" | "warning" | "danger" | "secondary" {
  if (status === "paid") return "success";
  if (status === "pending") return "warning";
  if (status === "canceled") return "danger";
  return "secondary";
}

function cancelReasonLabel(reason?: string) {
  if (reason === "timeout") return "超时取消";
  if (reason === "admin") return "管理员取消";
  if (reason === "user") return "用户取消";
  return "";
}

function finalTime(item: SubscriptionOrder) {
  if (item.status === "paid") return formatTime(item.paid_at);
  if (item.status === "canceled") return formatTime(item.canceled_at);
  return "-";
}

function SubscriptionOrdersContent() {
  const [items, setItems] = useState<SubscriptionOrder[]>([]);
  const [status, setStatus] = useState<string>(OrderStatus.All);
  const [query, setQuery] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [updatingOrderNo, setUpdatingOrderNo] = useState("");
  const [selectedOrderNos, setSelectedOrderNos] = useState<string[]>([]);
  const [isDeleting, setIsDeleting] = useState(false);
  const didLoadInitialFiltersRef = useRef(false);
  const ignoredInitialStatusEffectRef = useRef(false);
  const skipNextStatusLoadRef = useRef(false);
  const paidCount = useMemo(() => items.filter((item) => item.status === "paid").length, [items]);
  const canceledItems = useMemo(() => items.filter((item) => item.status === "canceled"), [items]);
  const selectedCanceledItems = useMemo(
    () => canceledItems.filter((item) => selectedOrderNos.includes(item.out_trade_no)),
    [canceledItems, selectedOrderNos],
  );
  const allCanceledSelected = canceledItems.length > 0 && canceledItems.every((item) => selectedOrderNos.includes(item.out_trade_no));
  const totalMoney = useMemo(
    () => items.reduce((sum, item) => sum + (item.status === "paid" ? Number(item.money || item.price || 0) : 0), 0),
    [items],
  );

  const load = async (filters: { status?: string; query?: string } = {}) => {
    const nextStatus = filters.status ?? status;
    const nextQuery = filters.query ?? query;
    setIsLoading(true);
    try {
      const data = await fetchAdminSubscriptionOrders({
        status: nextStatus === OrderStatus.All ? undefined : nextStatus,
        query: nextQuery.trim(),
        limit: 300,
      });
      setItems(data.items);
      setSelectedOrderNos((current) =>
        current.filter((orderNo) => data.items.some((item) => item.out_trade_no === orderNo && item.status === "canceled")),
      );
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "加载订单失败");
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    let initialStatus: string = OrderStatus.All;
    let initialQuery = "";
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      initialStatus = normalizeOrderStatus(params.get("status") || "");
      initialQuery = (params.get("query") || "").trim();
    }
    skipNextStatusLoadRef.current = true;
    setStatus(initialStatus);
    setQuery(initialQuery);
    didLoadInitialFiltersRef.current = true;
    void load({ status: initialStatus, query: initialQuery });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!didLoadInitialFiltersRef.current) {
      return;
    }
    if (!ignoredInitialStatusEffectRef.current) {
      ignoredInitialStatusEffectRef.current = true;
      return;
    }
    if (skipNextStatusLoadRef.current) {
      skipNextStatusLoadRef.current = false;
      return;
    }
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);

  const applyUpdatedItem = (updatedItem: SubscriptionOrder) => {
    setItems((current) => {
      if (status !== OrderStatus.All && updatedItem.status !== status) {
        return current.filter((order) => order.out_trade_no !== updatedItem.out_trade_no);
      }
      return current.map((order) => (order.out_trade_no === updatedItem.out_trade_no ? updatedItem : order));
    });
  };

  const toggleSelectCanceled = (checked: boolean) => {
    const canceledOrderNos = canceledItems.map((item) => item.out_trade_no);
    if (checked) {
      setSelectedOrderNos((current) => Array.from(new Set([...current, ...canceledOrderNos])));
      return;
    }
    setSelectedOrderNos((current) => current.filter((orderNo) => !canceledOrderNos.includes(orderNo)));
  };

  const toggleSelectOrder = (item: SubscriptionOrder, checked: boolean) => {
    if (item.status !== "canceled") {
      return;
    }
    setSelectedOrderNos((current) =>
      checked ? Array.from(new Set([...current, item.out_trade_no])) : current.filter((orderNo) => orderNo !== item.out_trade_no),
    );
  };

  const markPaid = async (item: SubscriptionOrder) => {
    setUpdatingOrderNo(item.out_trade_no);
    try {
      const data = await updateAdminSubscriptionOrderStatus(item.out_trade_no, "paid");
      applyUpdatedItem(data.item);
      toast.success(data.granted ? "订单已标记为已支付，额度已发放" : "订单已是已支付状态");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "更新订单状态失败");
    } finally {
      setUpdatingOrderNo("");
    }
  };

  const cancelOrder = async (item: SubscriptionOrder) => {
    if (typeof window !== "undefined" && !window.confirm("确认取消该待支付订单？")) {
      return;
    }
    setUpdatingOrderNo(item.out_trade_no);
    try {
      const data = await cancelAdminSubscriptionOrder(item.out_trade_no);
      applyUpdatedItem(data.item);
      toast.success(data.canceled ? "订单已取消" : "订单已是取消状态");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "取消订单失败");
    } finally {
      setUpdatingOrderNo("");
    }
  };

  const deleteSelectedCanceledOrders = async () => {
    const orderNos = selectedCanceledItems.map((item) => item.out_trade_no);
    if (orderNos.length === 0) {
      toast.error("请先选择已取消订单");
      return;
    }
    if (typeof window !== "undefined" && !window.confirm(`确认删除选中的 ${orderNos.length} 个已取消订单？删除后不可恢复。`)) {
      return;
    }
    setIsDeleting(true);
    try {
      const data = await deleteAdminCanceledSubscriptionOrders(orderNos);
      const removed = new Set(data.removed_ids);
      setItems((current) => current.filter((item) => !removed.has(item.out_trade_no)));
      setSelectedOrderNos((current) => current.filter((orderNo) => !removed.has(orderNo)));
      toast.success(`已删除 ${data.removed} 个已取消订单`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "删除订单失败");
      void load();
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <section className="h-full min-h-0 space-y-5 overflow-y-auto pr-1 pb-8 [scrollbar-color:rgba(148,163,184,.45)_transparent] [scrollbar-width:thin] [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-stone-300/65 [&::-webkit-scrollbar-track]:bg-transparent">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div className="space-y-1">
          <div className="text-xs font-semibold tracking-[0.18em] text-rose-400 uppercase">Orders</div>
          <h1 className="text-2xl font-semibold tracking-tight">订阅订单</h1>
        </div>
        <div className="flex flex-wrap gap-2">
          <Select value={status} onValueChange={setStatus}>
            <SelectTrigger className="h-10 w-[128px] rounded-xl border-stone-200 bg-white">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={OrderStatus.All}>全部状态</SelectItem>
              <SelectItem value={OrderStatus.Pending}>待支付</SelectItem>
              <SelectItem value={OrderStatus.Paid}>已支付</SelectItem>
              <SelectItem value={OrderStatus.Canceled}>已取消</SelectItem>
            </SelectContent>
          </Select>
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void load();
            }}
            placeholder="订单号 / 用户邮箱 / 套餐"
            className="h-10 w-64 rounded-xl border-stone-200 bg-white"
          />
          <Button onClick={() => void load()} disabled={isLoading} className="h-10 rounded-xl bg-stone-950 px-4 text-white hover:bg-stone-800">
            {isLoading ? <LoaderCircle className="size-4 animate-spin" /> : <Search className="size-4" />}
            查询
          </Button>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-3">
        <Card className="rounded-lg border-white/80 bg-white/80 shadow-sm">
          <CardContent className="p-5">
            <div className="text-sm text-stone-500">订单数</div>
            <div className="mt-2 text-2xl font-semibold text-stone-950">{items.length}</div>
          </CardContent>
        </Card>
        <Card className="rounded-lg border-white/80 bg-white/80 shadow-sm">
          <CardContent className="p-5">
            <div className="text-sm text-stone-500">已支付</div>
            <div className="mt-2 text-2xl font-semibold text-emerald-600">{paidCount}</div>
          </CardContent>
        </Card>
        <Card className="rounded-lg border-white/80 bg-white/80 shadow-sm">
          <CardContent className="p-5">
            <div className="text-sm text-stone-500">支付金额</div>
            <div className="mt-2 text-2xl font-semibold text-rose-600">{totalMoney.toFixed(2)}</div>
          </CardContent>
        </Card>
      </div>

      <Card className="overflow-hidden rounded-lg border-white/80 bg-white/80 shadow-sm">
        <CardContent className="p-0">
          <div className="flex items-center justify-between border-b border-stone-100 px-5 py-4 text-sm text-stone-600">
            <span>共 {items.length} 条</span>
            <Button variant="ghost" className="h-8 rounded-lg px-3 text-stone-500" onClick={() => void load()} disabled={isLoading}>
              <RefreshCw className={`size-4 ${isLoading ? "animate-spin" : ""}`} />
              刷新
            </Button>
          </div>
          <div className="flex flex-wrap items-center gap-3 border-b border-stone-100 px-5 py-3">
            <label className="flex items-center gap-2 text-sm text-stone-500">
              <Checkbox
                checked={allCanceledSelected}
                onCheckedChange={(checked) => toggleSelectCanceled(Boolean(checked))}
                disabled={canceledItems.length === 0}
                aria-label="选择全部已取消订单"
              />
              选择已取消
            </label>
            <Button
              variant="ghost"
              className="h-8 rounded-lg px-3 text-rose-500 hover:bg-rose-50 hover:text-rose-600"
              onClick={() => void deleteSelectedCanceledOrders()}
              disabled={selectedCanceledItems.length === 0 || isDeleting}
            >
              {isDeleting ? <LoaderCircle className="size-4 animate-spin" /> : <Trash2 className="size-4" />}
              删除所选
            </Button>
            {selectedCanceledItems.length > 0 ? (
              <span className="rounded-lg bg-stone-100 px-2.5 py-1 text-xs font-medium text-stone-600">
                已选择 {selectedCanceledItems.length} 个已取消订单
              </span>
            ) : null}
          </div>
          <div className="overflow-x-auto">
            <Table className="min-w-[1320px]">
              <TableHeader>
                <TableRow>
                  <TableHead className="w-12"></TableHead>
                  <TableHead>订单号</TableHead>
                  <TableHead>用户</TableHead>
                  <TableHead>套餐</TableHead>
                  <TableHead>金额</TableHead>
                  <TableHead>额度</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>支付单号</TableHead>
                  <TableHead>创建时间</TableHead>
                  <TableHead>支付截止</TableHead>
                  <TableHead>支付/取消时间</TableHead>
                  <TableHead className="w-52">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((item) => (
                  <TableRow key={item.out_trade_no} className="text-stone-600">
                    <TableCell>
                      <Checkbox
                        checked={selectedOrderNos.includes(item.out_trade_no)}
                        onCheckedChange={(checked) => toggleSelectOrder(item, Boolean(checked))}
                        disabled={item.status !== "canceled" || isDeleting}
                        aria-label={`选择订单 ${item.out_trade_no}`}
                      />
                    </TableCell>
                    <TableCell className="font-mono text-xs text-stone-800">{item.out_trade_no}</TableCell>
                    <TableCell>
                      <div className="max-w-[180px] truncate text-stone-800">{item.user_email || item.user_id || "-"}</div>
                    </TableCell>
                    <TableCell>
                      <div className="max-w-[160px] truncate font-medium text-stone-800">{item.plan_name || item.plan_id}</div>
                      <div className="text-xs text-stone-400">{item.valid_months} 个月</div>
                    </TableCell>
                    <TableCell className="font-semibold text-rose-600">{item.money || item.price}</TableCell>
                    <TableCell>{item.quota} 点</TableCell>
                    <TableCell>
                      <Badge variant={statusVariant(item.status)} className="rounded-md">
                        {statusLabel(item.status)}
                      </Badge>
                      {item.status === "canceled" && cancelReasonLabel(item.cancel_reason) ? (
                        <div className="mt-1 text-xs text-stone-400">{cancelReasonLabel(item.cancel_reason)}</div>
                      ) : null}
                    </TableCell>
                    <TableCell className="max-w-[160px] truncate font-mono text-xs">{item.epay_trade_no || "-"}</TableCell>
                    <TableCell className="whitespace-nowrap text-xs">{formatTime(item.created_at)}</TableCell>
                    <TableCell className="whitespace-nowrap text-xs">{formatTime(item.expires_at)}</TableCell>
                    <TableCell className="whitespace-nowrap text-xs">{finalTime(item)}</TableCell>
                    <TableCell>
                      {item.status === "pending" ? (
                        <div className="flex flex-wrap gap-2">
                          <Button
                            variant="outline"
                            className="h-8 rounded-lg border-stone-200 bg-white px-3 text-xs"
                            onClick={() => void markPaid(item)}
                            disabled={Boolean(updatingOrderNo)}
                          >
                            {updatingOrderNo === item.out_trade_no ? (
                              <LoaderCircle className="size-3.5 animate-spin" />
                            ) : (
                              <CheckCircle2 className="size-3.5" />
                            )}
                            标记已支付
                          </Button>
                          <Button
                            variant="outline"
                            className="h-8 rounded-lg border-rose-100 bg-white px-3 text-xs text-rose-600 hover:bg-rose-50"
                            onClick={() => void cancelOrder(item)}
                            disabled={Boolean(updatingOrderNo)}
                          >
                            {updatingOrderNo === item.out_trade_no ? <LoaderCircle className="size-3.5 animate-spin" /> : <XCircle className="size-3.5" />}
                            取消
                          </Button>
                        </div>
                      ) : (
                        <span className="text-xs text-stone-400">-</span>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          {!isLoading && items.length === 0 ? (
            <div className="flex min-h-40 flex-col items-center justify-center gap-3 px-6 py-14 text-center text-sm text-stone-500">
              <ReceiptText className="size-8 text-stone-300" />
              暂无订阅订单
            </div>
          ) : null}
        </CardContent>
      </Card>
    </section>
  );
}

export default function SubscriptionOrdersPage() {
  const { isCheckingAuth, session } = useAuthGuard(["admin"]);

  if (isCheckingAuth || !session || session.role !== "admin") {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <LoaderCircle className="size-5 animate-spin text-stone-400" />
      </div>
    );
  }

  return <SubscriptionOrdersContent />;
}
