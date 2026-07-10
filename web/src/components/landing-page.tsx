"use client";

import {
  ArrowRight,
  Bot,
  Check,
  Eraser,
  ImageIcon,
  ImagePlus,
  Maximize2,
  MessageSquareText,
  ScanSearch,
  Sparkles,
  UserPlus,
  WandSparkles,
  type LucideIcon,
} from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { useEffect, useState } from "react";

import { fetchPublicModels, type PublicModelItem } from "@/lib/api";
import { isImageGenerationModel } from "@/lib/model-options";
import { getRouteHref } from "@/lib/routes";
import { useSiteSettingsStore } from "@/lib/site-settings";

const features: Array<{
  title: string;
  description: string;
  icon: LucideIcon;
  iconClass: string;
  iconBackground: string;
}> = [
  {
    title: "顶级模型生图",
    description: "接入 GPT-Image 2、Nano Banana 等先进模型，准确理解复杂创意。",
    icon: WandSparkles,
    iconClass: "text-[#3f78e0]",
    iconBackground: "bg-[#f1f5fd]",
  },
  {
    title: "多轮智能对话",
    description: "使用顶级语言模型讨论创意、优化提示词并完成内容写作。",
    icon: MessageSquareText,
    iconClass: "text-[#45c4a0]",
    iconBackground: "bg-[#f1fbf8]",
  },
  {
    title: "参考图创作",
    description: "上传图片即可延续角色、构图与视觉风格，创作更连贯。",
    icon: ImagePlus,
    iconClass: "text-[#f78b77]",
    iconBackground: "bg-[#fef6f5]",
  },
  {
    title: "局部精细编辑",
    description: "通过局部重绘快速调整画面细节，不必从头重新生成。",
    icon: ScanSearch,
    iconClass: "text-[#d16b86]",
    iconBackground: "bg-[#fcf4f6]",
  },
  {
    title: "扩图与裁切",
    description: "灵活改变画面比例和边界，适配海报、社交媒体与商品图。",
    icon: Maximize2,
    iconClass: "text-[#747ed1]",
    iconBackground: "bg-[#f5f5fc]",
  },
  {
    title: "去背景与换风格",
    description: "常用图片工具开箱即用，让素材处理和风格转换更加高效。",
    icon: Eraser,
    iconClass: "text-[#fab758]",
    iconBackground: "bg-[#fffaf2]",
  },
];

const showcaseImages = [
  {
    src: "/landing-cases/chicken.jpg",
    alt: "鸡主题案例图",
    title: "鸡",
  },
  {
    src: "/landing-cases/mud.jpg",
    alt: "泥主题案例图",
    title: "泥",
  },
  {
    src: "/landing-cases/tai-chi.jpg",
    alt: "太主题案例图",
    title: "太",
  },
  {
    src: "/landing-cases/beauty.jpg",
    alt: "美主题案例图",
    title: "美",
  },
];

function Brand() {
  const siteTitle = useSiteSettingsStore((state) => state.settings.site_title);
  const siteIcon = useSiteSettingsStore((state) => state.settings.site_icon);
  const [iconFailed, setIconFailed] = useState(false);
  const showIcon = Boolean(siteIcon.trim() && !iconFailed);

  return (
    <span className="inline-flex min-w-0 items-center gap-3">
      <span className="grid size-10 shrink-0 place-items-center overflow-hidden rounded-md border border-[#dfe6f1] bg-white text-[#3f78e0] shadow-[0_6px_20px_rgba(52,63,82,0.08)]">
        {showIcon ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={siteIcon} alt="" className="size-full object-contain p-1.5" onError={() => setIconFailed(true)} />
        ) : (
          <Sparkles className="size-5" aria-hidden="true" />
        )}
      </span>
      <span className="truncate text-lg font-semibold text-[#343f52]">{siteTitle || "Image Studio"}</span>
    </span>
  );
}

function ModelPanel({
  title,
  subtitle,
  icon: Icon,
  items,
  defaultModel,
  unit,
  accent,
  accentBackground,
}: {
  title: string;
  subtitle: string;
  icon: LucideIcon;
  items: PublicModelItem[];
  defaultModel: string;
  unit: string;
  accent: string;
  accentBackground: string;
}) {
  return (
    <div className="rounded-md border border-[#e1e6ef] bg-white p-6 shadow-[0_10px_36px_rgba(52,63,82,0.06)] sm:p-8">
      <div className="flex items-center gap-4">
        <span className={`grid size-11 shrink-0 place-items-center rounded-md ${accentBackground} ${accent}`}>
          <Icon className="size-5" aria-hidden="true" />
        </span>
        <div>
          <h3 className="text-xl font-semibold text-[#343f52]">{title}</h3>
          <p className="mt-1 text-sm text-[#9499a3]">{subtitle}</p>
        </div>
      </div>
      <div className="mt-7 divide-y divide-[#e8ebf1] border-y border-[#e8ebf1]">
        {items.length > 0 ? (
          items.map((item) => (
            <div key={item.model} className="flex min-h-16 items-center justify-between gap-4 py-3">
              <div className="min-w-0">
                <div className="font-medium text-[#343f52] [overflow-wrap:anywhere]">{item.model}</div>
                {item.model.toLowerCase() === defaultModel.toLowerCase() ? (
                  <span className={`mt-1 inline-block text-xs font-medium ${accent}`}>默认模型</span>
                ) : null}
              </div>
              <span className="shrink-0 rounded-md bg-[#fffaf2] px-3 py-1.5 text-sm font-semibold text-[#d89222]">
                {item.quota_cost} 点 / {unit}
              </span>
            </div>
          ))
        ) : (
          <p className="py-8 text-sm text-[#9499a3]">暂未配置可用模型</p>
        )}
      </div>
    </div>
  );
}

export function LandingPage() {
  const siteTitle = useSiteSettingsStore((state) => state.settings.site_title) || "Image Studio";
  const subscriptionPlans = useSiteSettingsStore((state) => state.settings.subscription_plans);
  const defaultImageModel = useSiteSettingsStore((state) => state.settings.default_image_model);
  const defaultTextModel = useSiteSettingsStore((state) => state.settings.default_text_model);
  const [publicModels, setPublicModels] = useState<PublicModelItem[]>([]);
  const loginHref = getRouteHref("/login");
  const registerHref = getRouteHref("/register");
  const imageModels = publicModels.filter((item) => isImageGenerationModel(item.model));
  const textModels = publicModels.filter((item) => !isImageGenerationModel(item.model));

  useEffect(() => {
    let active = true;
    const loadModels = async () => {
      try {
        const data = await fetchPublicModels();
        if (active) {
          setPublicModels(data.items);
        }
      } catch {
        if (active) {
          setPublicModels([]);
        }
      }
    };
    void loadModels();
    return () => {
      active = false;
    };
  }, []);

  return (
    <div className="overflow-hidden bg-white text-[#60697b]">
      <section className="relative h-[calc(100svh-2rem)] overflow-hidden bg-[#f1f5fd]">
        <Image
          src="/banana-prompt-quicker/images/home_office_isometric_3d.jpg"
          alt="AI 生成的 3D 创作空间"
          fill
          priority
          sizes="100vw"
          className="object-cover object-center"
        />
        <div className="absolute inset-0 bg-[#f1f5fd]/82" />

        <div className="relative z-10 mx-auto flex h-full w-full max-w-[1280px] flex-col px-5 sm:px-8 lg:px-12">
          <header className="flex h-20 shrink-0 items-center justify-between gap-6 sm:h-24">
            <Link href="/" aria-label={`${siteTitle} 首页`} className="min-w-0">
              <Brand />
            </Link>

            <nav className="hidden items-center gap-7 text-sm font-semibold text-[#343f52] md:flex" aria-label="首页导航">
              <a href="#capabilities" className="transition-colors hover:text-[#3f78e0]">核心能力</a>
              <a href="#models" className="transition-colors hover:text-[#3f78e0]">模型点数</a>
              <a href="#plans" className="transition-colors hover:text-[#3f78e0]">订阅套餐</a>
            </nav>

            <div className="flex shrink-0 items-center gap-2">
              <a
                href={registerHref}
                className="inline-flex h-10 items-center gap-2 rounded-md border border-[#3f78e0]/30 bg-white/80 px-3 text-sm font-semibold text-[#3f78e0] transition-colors hover:bg-white sm:px-4"
              >
                <UserPlus className="size-4" aria-hidden="true" />
                注册
              </a>
              <a
                href={loginHref}
                className="inline-flex h-10 items-center gap-2 rounded-md bg-[#3f78e0] px-3 text-sm font-semibold text-white shadow-[0_8px_24px_rgba(63,120,224,0.24)] transition-colors hover:bg-[#2f65c6] sm:px-4"
              >
                登录
                <ArrowRight className="size-4" aria-hidden="true" />
              </a>
            </div>
          </header>

          <div className="flex min-h-0 flex-1 items-center pb-8 sm:pb-12">
            <div className="max-w-2xl">
              <div className="text-sm font-semibold text-[#3f78e0]">一站式 AI 创作工作台</div>
              <h1 className="mt-4 max-w-full text-5xl leading-[1.04] font-semibold text-[#343f52] [overflow-wrap:anywhere] sm:text-6xl">
                {siteTitle}
              </h1>
              <p className="mt-5 max-w-xl text-2xl leading-tight font-semibold text-[#343f52] sm:text-3xl">
                顶级模型驱动的 <span className="border-b-[5px] border-[#fab758]">AI 图片与对话平台</span>
              </p>
              <p className="mt-6 max-w-xl text-base leading-7 text-[#60697b] sm:text-lg">
                从一句话到高质量作品，生成图片、编辑素材、讨论创意与优化提示词，一处完成。
              </p>
              <div className="mt-8 flex flex-wrap gap-3">
                <a
                  href={loginHref}
                  className="inline-flex h-12 items-center gap-2 rounded-md bg-[#3f78e0] px-6 font-semibold text-white shadow-[0_10px_28px_rgba(63,120,224,0.25)] transition-colors hover:bg-[#2f65c6]"
                >
                  立即开始
                  <ArrowRight className="size-5" aria-hidden="true" />
                </a>
                <a
                  href="#plans"
                  className="inline-flex h-12 items-center rounded-md bg-[#e0e9fa] px-6 font-semibold text-[#3f78e0] transition-colors hover:bg-white"
                >
                  了解套餐
                </a>
              </div>
              <div className="mt-7 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm font-medium text-[#60697b]">
                <span>GPT-Image 2</span>
                <span className="size-1 rounded-full bg-[#fab758]" />
                <span>Nano Banana</span>
                <span className="size-1 rounded-full bg-[#45c4a0]" />
                <span>GPT-5.5</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section id="capabilities" className="bg-white px-5 py-20 sm:px-8 sm:py-28">
        <div className="mx-auto max-w-6xl">
          <div className="mx-auto max-w-3xl text-center">
            <p className="text-sm font-semibold text-[#9499a3]">核心能力</p>
            <h2 className="mt-3 text-3xl leading-tight font-semibold text-[#343f52] sm:text-5xl">
              简洁易用，覆盖完整 AI 创作流程
            </h2>
          </div>

          <div className="mt-14 grid gap-x-10 gap-y-11 md:grid-cols-2 lg:grid-cols-3">
            {features.map((feature) => {
              const Icon = feature.icon;
              return (
                <article key={feature.title} className="flex items-start gap-5">
                  <span className={`grid size-12 shrink-0 place-items-center rounded-md ${feature.iconBackground} ${feature.iconClass}`}>
                    <Icon className="size-6" aria-hidden="true" />
                  </span>
                  <div>
                    <h3 className="text-xl font-semibold text-[#343f52]">{feature.title}</h3>
                    <p className="mt-2 text-sm leading-6 text-[#60697b]">{feature.description}</p>
                  </div>
                </article>
              );
            })}
          </div>
        </div>
      </section>

      <section className="bg-[#f6f7f9] px-5 py-20 sm:px-8 sm:py-28">
        <div className="mx-auto grid max-w-6xl items-center gap-12 lg:grid-cols-2 lg:gap-16">
          <div className="grid min-h-[480px] grid-cols-2 gap-3">
            <figure className="relative row-span-2 overflow-hidden rounded-md bg-[#e9edf4]">
              <Image
                src="/banana-prompt-quicker/images/brand_miniature_store.jpg"
                alt="AI 生成的品牌微缩场景"
                fill
                sizes="(max-width: 1023px) 50vw, 28vw"
                className="object-cover"
              />
            </figure>
            <figure className="relative overflow-hidden rounded-md bg-[#e9edf4]">
              <Image
                src="/banana-prompt-quicker/images/product-ad.svg"
                alt="AI 生成的产品广告"
                fill
                sizes="(max-width: 1023px) 50vw, 28vw"
                className="object-cover"
              />
            </figure>
            <figure className="relative overflow-hidden rounded-md bg-[#e9edf4]">
              <Image
                src="/banana-prompt-quicker/images/city_weather_cake.jpg"
                alt="AI 生成的城市天气创意图"
                fill
                sizes="(max-width: 1023px) 50vw, 28vw"
                className="object-cover"
              />
            </figure>
          </div>

          <div>
            <p className="text-sm font-semibold text-[#9499a3]">创作步骤</p>
            <h2 className="mt-3 text-3xl leading-tight font-semibold text-[#343f52] sm:text-5xl">
              无需复杂设置，三步完成作品
            </h2>
            <p className="mt-5 text-base leading-7 text-[#60697b] sm:text-lg">
              把精力留给创意本身，模型选择、图片编辑和作品管理都已为你准备好。
            </p>

            <div className="mt-9 space-y-7">
              {[
                ["01", "描述你的想法", "输入提示词，也可以上传参考图片，让模型理解你想要的内容。"],
                ["02", "选择模型与工具", "根据质量、风格和点数选择合适模型，按需使用内置编辑工具。"],
                ["03", "生成并继续完善", "保存满意作品，或通过对话与编辑功能继续打磨画面细节。"],
              ].map(([number, title, description]) => (
                <div key={number} className="flex items-start gap-5">
                  <span className="grid size-11 shrink-0 place-items-center rounded-full bg-[#e0e9fa] text-sm font-semibold text-[#3f78e0]">
                    {number}
                  </span>
                  <div>
                    <h3 className="text-xl font-semibold text-[#343f52]">{title}</h3>
                    <p className="mt-2 text-sm leading-6 text-[#60697b]">{description}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="bg-white px-5 py-20 sm:px-8 sm:py-28">
        <div className="mx-auto max-w-6xl">
          <div className="mx-auto max-w-3xl text-center">
            <p className="text-sm font-semibold text-[#9499a3]">作品展示</p>
            <h2 className="mt-3 text-3xl leading-tight font-semibold text-[#343f52] sm:text-5xl">
              唱，跳，Rap，打篮球 <span className="whitespace-nowrap">样样精通</span>
            </h2>
          </div>

          <div className="mt-12 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
            {showcaseImages.map((item) => (
              <figure key={item.src} className="overflow-hidden rounded-md border border-[#e1e6ef] bg-white shadow-[0_12px_36px_rgba(52,63,82,0.07)]">
                <div className="relative aspect-[3/4] overflow-hidden bg-[#f6f7f9]">
                  <Image
                    src={item.src}
                    alt={item.alt}
                    fill
                    sizes="(max-width: 639px) 100vw, (max-width: 1023px) 50vw, 25vw"
                    className="object-cover transition-transform duration-500 hover:scale-[1.025]"
                  />
                </div>
                <figcaption className="p-5 text-center">
                  <h3 className="font-semibold text-[#343f52]">{item.title}</h3>
                </figcaption>
              </figure>
            ))}
          </div>
        </div>
      </section>

      <section id="models" className="scroll-mt-4 bg-[#f6f7f9] px-5 py-20 sm:px-8 sm:py-28">
        <div className="mx-auto max-w-6xl">
          <div className="mx-auto max-w-3xl text-center">
            <p className="text-sm font-semibold text-[#9499a3]">模型与点数</p>
            <h2 className="mt-3 text-3xl leading-tight font-semibold text-[#343f52] sm:text-5xl">
              每一次创作，点数清晰可见
            </h2>
            <p className="mt-5 text-base leading-7 text-[#60697b] sm:text-lg">
              模型列表与所需点数直接读取后台当前配置，选择前即可了解消耗。
            </p>
          </div>

          <div className="mt-12 grid gap-6 lg:grid-cols-2">
            <ModelPanel
              title="画图模型"
              subtitle="每生成一张图片的点数"
              icon={ImageIcon}
              items={imageModels}
              defaultModel={defaultImageModel}
              unit="张"
              accent="text-[#3f78e0]"
              accentBackground="bg-[#f1f5fd]"
            />
            <ModelPanel
              title="对话模型"
              subtitle="每次发送消息的点数"
              icon={Bot}
              items={textModels}
              defaultModel={defaultTextModel}
              unit="次"
              accent="text-[#45c4a0]"
              accentBackground="bg-[#f1fbf8]"
            />
          </div>
        </div>
      </section>

      <section id="plans" className="scroll-mt-4 bg-white px-5 py-20 sm:px-8 sm:py-28">
        <div className="mx-auto max-w-6xl">
          <div className="mx-auto max-w-3xl text-center">
            <p className="text-sm font-semibold text-[#9499a3]">订阅套餐</p>
            <h2 className="mt-3 text-3xl leading-tight font-semibold text-[#343f52] sm:text-5xl">
              按创作需要，选择合适额度
            </h2>
            <p className="mt-5 text-base leading-7 text-[#60697b] sm:text-lg">
              套餐价格、额度和有效期均与站内订阅配置自动同步。
            </p>
          </div>

          {subscriptionPlans.length > 0 ? (
            <div className="mt-12 grid gap-5 md:grid-cols-2 lg:grid-cols-3">
              {subscriptionPlans.map((plan, index) => {
                const highlighted = subscriptionPlans.length >= 3 && index === 1;
                return (
                  <article
                    key={plan.id}
                    className={`flex min-h-[380px] flex-col rounded-md border p-7 sm:p-8 ${
                      highlighted ? "border-[#c9d8f3] bg-[#f1f5fd]" : "border-[#e1e6ef] bg-white"
                    }`}
                  >
                    <h3 className="text-xl font-semibold text-[#343f52] [overflow-wrap:anywhere]">{plan.name || "创作套餐"}</h3>
                    <div className="mt-7 flex items-end gap-2 border-b border-[#dfe4ec] pb-7">
                      <span className="pb-1 text-xl font-semibold text-[#60697b]">¥</span>
                      <span className="text-5xl leading-none font-semibold text-[#343f52] [overflow-wrap:anywhere]">{plan.price}</span>
                      <span className="pb-1 text-sm text-[#9499a3]">套餐总价</span>
                    </div>
                    <div className="mt-7 space-y-4 text-sm text-[#60697b]">
                      <div className="flex items-center gap-3">
                        <Check className="size-4 shrink-0 text-[#45c4a0]" aria-hidden="true" />
                        <span><strong className="font-semibold text-[#343f52]">{plan.quota.toLocaleString("zh-CN")}</strong> 点创作额度</span>
                      </div>
                      <div className="flex items-center gap-3">
                        <Check className="size-4 shrink-0 text-[#45c4a0]" aria-hidden="true" />
                        <span>购买后 <strong className="font-semibold text-[#343f52]">{plan.valid_months}</strong> 个月内有效</span>
                      </div>
                      <div className="flex items-center gap-3">
                        <Check className="size-4 shrink-0 text-[#45c4a0]" aria-hidden="true" />
                        <span>用于站内 AI 创作服务</span>
                      </div>
                    </div>
                    <a
                      href={loginHref}
                      className={`mt-auto inline-flex h-11 items-center justify-center gap-2 rounded-md px-5 text-sm font-semibold transition-colors ${
                        highlighted
                          ? "bg-[#3f78e0] text-white hover:bg-[#2f65c6]"
                          : "bg-[#e0e9fa] text-[#3f78e0] hover:bg-[#d3e0f7]"
                      }`}
                    >
                      登录后订阅
                      <ArrowRight className="size-4" aria-hidden="true" />
                    </a>
                  </article>
                );
              })}
            </div>
          ) : (
            <div className="mt-12 border-y border-[#e1e6ef] py-12 text-center">
              <p className="font-medium text-[#343f52]">套餐正在配置中</p>
              <p className="mt-2 text-sm text-[#9499a3]">登录后可查看最新购买方式。</p>
            </div>
          )}
        </div>
      </section>

      <section className="bg-[#f6f7f9] px-5 py-20 sm:px-8 sm:py-24">
        <div className="mx-auto flex max-w-6xl flex-col items-start justify-between gap-8 md:flex-row md:items-center">
          <div className="max-w-3xl">
            <p className="text-sm font-semibold text-[#3f78e0]">开始创作</p>
            <h2 className="mt-3 text-3xl leading-tight font-semibold text-[#343f52] sm:text-5xl">
              把脑海里的画面，变成看得见的作品
            </h2>
          </div>
          <a
            href={loginHref}
            className="inline-flex h-12 shrink-0 items-center gap-2 rounded-md bg-[#3f78e0] px-6 font-semibold text-white shadow-[0_10px_28px_rgba(63,120,224,0.22)] transition-colors hover:bg-[#2f65c6]"
          >
            立即开始
            <ArrowRight className="size-5" aria-hidden="true" />
          </a>
        </div>
      </section>

      <footer className="border-t border-[#e1e6ef] bg-[#f6f7f9] px-5 py-8 sm:px-8">
        <div className="mx-auto flex max-w-6xl flex-col gap-4 text-sm text-[#9499a3] sm:flex-row sm:items-center sm:justify-between">
          <span className="font-semibold text-[#343f52]">{siteTitle}</span>
          <span>AI 图片生成、编辑与智能对话</span>
        </div>
      </footer>
    </div>
  );
}
