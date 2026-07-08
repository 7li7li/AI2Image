"use client";

import { LoaderCircle, PlugZap, Save } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { testProxy, type ProxyTestResult } from "@/lib/api";

import { useSettingsStore } from "../store";

export function ConfigCard() {
  const [isTestingProxy, setIsTestingProxy] = useState(false);
  const [proxyTestResult, setProxyTestResult] = useState<ProxyTestResult | null>(null);
  const logLevelOptions = ["debug", "info", "warning", "error"];
  const config = useSettingsStore((state) => state.config);
  const isLoadingConfig = useSettingsStore((state) => state.isLoadingConfig);
  const isSavingConfig = useSettingsStore((state) => state.isSavingConfig);
  const setImageRetentionDays = useSettingsStore((state) => state.setImageRetentionDays);
  const setBackgroundTaskMaxWorkers = useSettingsStore((state) => state.setBackgroundTaskMaxWorkers);
  const setBackgroundTaskQueueLimit = useSettingsStore((state) => state.setBackgroundTaskQueueLimit);
  const setBackgroundTaskUserLimit = useSettingsStore((state) => state.setBackgroundTaskUserLimit);
  const setLogLevel = useSettingsStore((state) => state.setLogLevel);
  const setProxy = useSettingsStore((state) => state.setProxy);
  const setBaseUrl = useSettingsStore((state) => state.setBaseUrl);
  const setSiteTitle = useSettingsStore((state) => state.setSiteTitle);
  const setSiteIcon = useSettingsStore((state) => state.setSiteIcon);
  const setSiteBackground = useSettingsStore((state) => state.setSiteBackground);
  const setDefaultImageModel = useSettingsStore((state) => state.setDefaultImageModel);
  const setDefaultTextModel = useSettingsStore((state) => state.setDefaultTextModel);
  const saveConfig = useSettingsStore((state) => state.saveConfig);

  const handleTestProxy = async () => {
    const candidate = String(config?.proxy || "").trim();
    if (!candidate) {
      toast.error("请先填写代理地址");
      return;
    }
    setIsTestingProxy(true);
    setProxyTestResult(null);
    try {
      const data = await testProxy(candidate);
      setProxyTestResult(data.result);
      if (data.result.ok) {
        toast.success(`代理可用：${data.result.latency_ms} ms，HTTP ${data.result.status}`);
      } else {
        toast.error(`代理不可用：${data.result.error ?? "未知错误"}`);
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "测试代理失败");
    } finally {
      setIsTestingProxy(false);
    }
  };

  if (isLoadingConfig) {
    return (
      <Card className="rounded-lg border-white/80 bg-white/80 shadow-sm">
        <CardContent className="flex items-center justify-center p-10">
          <LoaderCircle className="size-5 animate-spin text-stone-400" />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="rounded-lg border-white/80 bg-white/80 shadow-sm">
      <CardContent className="space-y-6 p-6">
        <div className="space-y-3">
          <div>
            <h2 className="text-base font-semibold text-stone-900">网站设置</h2>
            <p className="mt-1 text-sm text-stone-500">配置浏览器标题、登录页标题、顶部品牌名和网站图标。</p>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <label className="text-sm text-stone-700">网站标题</label>
              <Input
                value={String(config?.site_title || "")}
                onChange={(event) => setSiteTitle(event.target.value)}
                placeholder="Image Studio"
                className="h-10 rounded-xl border-stone-200 bg-white"
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm text-stone-700">网站图标 URL</label>
              <Input
                value={String(config?.site_icon || "")}
                onChange={(event) => setSiteIcon(event.target.value)}
                placeholder="/favicon.ico"
                className="h-10 rounded-xl border-stone-200 bg-white"
              />
              <p className="text-xs text-stone-500">
                支持站内路径或完整 URL，例如 /favicon.ico 或 https://example.com/icon.png。
              </p>
            </div>
            <div className="space-y-2 md:col-span-2">
              <label className="text-sm text-stone-700">登录页背景 URL</label>
              <Input
                value={String(config?.site_background || "")}
                onChange={(event) => setSiteBackground(event.target.value)}
                placeholder="https://example.com/background.jpg"
                className="h-10 rounded-xl border-stone-200 bg-white"
              />
              <p className="text-xs text-stone-500">
                留空使用默认浅灰白背景；填写图片 URL 后只会在登录页显示。
              </p>
            </div>
          </div>
        </div>

        <div className="space-y-3">
          <div>
            <h2 className="text-base font-semibold text-stone-900">系统设置</h2>
            <p className="mt-1 text-sm text-stone-500">配置代理、图片访问地址、清理周期和日志级别。</p>
          </div>
          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <label className="text-sm text-stone-700">全局代理</label>
              <Input
                value={String(config?.proxy || "")}
                onChange={(event) => {
                  setProxy(event.target.value);
                  setProxyTestResult(null);
                }}
                placeholder="http://127.0.0.1:7890"
                className="h-10 rounded-xl border-stone-200 bg-white"
              />
              <p className="text-xs text-stone-500">留空表示不使用代理，渠道请求会沿用这里的出网代理设置。</p>
              {proxyTestResult ? (
                <div
                  className={`rounded-xl border px-3 py-2 text-xs leading-6 ${
                    proxyTestResult.ok
                      ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                      : "border-rose-200 bg-rose-50 text-rose-800"
                  }`}
                >
                  {proxyTestResult.ok
                    ? `代理可用：HTTP ${proxyTestResult.status}，用时 ${proxyTestResult.latency_ms} ms`
                    : `代理不可用：${proxyTestResult.error ?? "未知错误"}（用时 ${proxyTestResult.latency_ms} ms）`}
                </div>
              ) : null}
              <div className="flex justify-end">
                <Button
                  type="button"
                  variant="outline"
                  className="h-9 rounded-xl border-stone-200 bg-white px-4 text-stone-700"
                  onClick={() => void handleTestProxy()}
                  disabled={isTestingProxy}
                >
                  {isTestingProxy ? <LoaderCircle className="size-4 animate-spin" /> : <PlugZap className="size-4" />}
                  测试代理
                </Button>
              </div>
            </div>
            <div className="space-y-2">
              <label className="text-sm text-stone-700">图片访问地址</label>
              <Input
                value={String(config?.base_url || "")}
                onChange={(event) => setBaseUrl(event.target.value)}
                placeholder="https://example.com"
                className="h-10 rounded-xl border-stone-200 bg-white"
              />
              <p className="text-xs text-stone-500">用于生成图片结果的访问前缀地址。</p>
            </div>
            <div className="space-y-2">
              <label className="text-sm text-stone-700">图片自动清理</label>
              <Input
                value={String(config?.image_retention_days || "")}
                onChange={(event) => setImageRetentionDays(event.target.value)}
                placeholder="30"
                className="h-10 rounded-xl border-stone-200 bg-white"
              />
              <p className="text-xs text-stone-500">自动删除多少天前的本地图片。</p>
            </div>
            <div className="space-y-2">
              <label className="text-sm text-stone-700">后台任务总并发</label>
              <Input
                type="number"
                min={1}
                max={128}
                value={String(config?.background_task_max_workers || "")}
                onChange={(event) => setBackgroundTaskMaxWorkers(event.target.value)}
                placeholder="12"
                className="h-10 rounded-xl border-stone-200 bg-white"
              />
              <p className="text-xs text-stone-500">同一后端进程最多同时处理多少个图片/对话后台任务。</p>
            </div>
            <div className="space-y-2">
              <label className="text-sm text-stone-700">后台任务队列容量</label>
              <Input
                type="number"
                min={1}
                max={10000}
                value={String(config?.background_task_queue_limit || "")}
                onChange={(event) => setBackgroundTaskQueueLimit(event.target.value)}
                placeholder="100"
                className="h-10 rounded-xl border-stone-200 bg-white"
              />
              <p className="text-xs text-stone-500">排队和运行中的后台任务总数达到该值后，新任务会返回繁忙。</p>
            </div>
            <div className="space-y-2">
              <label className="text-sm text-stone-700">单账号任务上限</label>
              <Input
                type="number"
                min={0}
                max={50}
                value={String(config?.background_task_user_limit ?? "")}
                onChange={(event) => setBackgroundTaskUserLimit(event.target.value)}
                placeholder="3"
                className="h-10 rounded-xl border-stone-200 bg-white"
              />
              <p className="text-xs text-stone-500">单个账号排队和运行中的任务上限，填 0 表示不限制。</p>
            </div>
            <div className="space-y-2">
              <label className="text-sm text-stone-700">默认画图模型</label>
              <Input
                value={String(config?.default_image_model || "")}
                onChange={(event) => setDefaultImageModel(event.target.value)}
                placeholder="gpt-image-2"
                className="h-10 rounded-xl border-stone-200 bg-white"
              />
              <p className="text-xs text-stone-500">用于文生图和图生图，请填写已配置渠道支持的模型名。</p>
            </div>
            <div className="space-y-2">
              <label className="text-sm text-stone-700">默认文本对话模型</label>
              <Input
                value={String(config?.default_text_model || "")}
                onChange={(event) => setDefaultTextModel(event.target.value)}
                placeholder="gpt-5.5"
                className="h-10 rounded-xl border-stone-200 bg-white"
              />
              <p className="text-xs text-stone-500">用于文本对话，每次成功回复扣除 1 额度。</p>
            </div>
            <div className="space-y-3 rounded-xl border border-stone-200 bg-white px-4 py-3">
              <div>
                <label className="text-sm text-stone-700">控制台日志级别</label>
                <p className="mt-1 text-xs text-stone-500">不选择时使用默认 info / warning / error。</p>
              </div>
              <div className="grid grid-cols-2 gap-2">
                {logLevelOptions.map((level) => (
                  <label key={level} className="flex items-center gap-2 text-sm capitalize text-stone-700">
                    <Checkbox
                      checked={Boolean(config?.log_levels?.includes(level))}
                      onCheckedChange={(checked) => setLogLevel(level, Boolean(checked))}
                    />
                    {level}
                  </label>
                ))}
              </div>
            </div>
          </div>
        </div>

        <div className="flex justify-end">
          <Button
            className="h-10 rounded-xl bg-stone-950 px-5 text-white hover:bg-stone-800"
            onClick={() => void saveConfig()}
            disabled={isSavingConfig}
          >
            {isSavingConfig ? <LoaderCircle className="size-4 animate-spin" /> : <Save className="size-4" />}
            保存
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
