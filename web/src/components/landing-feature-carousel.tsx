"use client";

import {
  BookOpenText,
  Check,
  ChevronLeft,
  ChevronRight,
  Images,
  Layers,
  PenTool,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import Image from "next/image";
import { useEffect, useRef, useState } from "react";

const AUTO_PLAY_DELAY_MS = 5200;
const SWIPE_THRESHOLD_PX = 50;

const productFeatures: Array<{
  title: string;
  description: string;
  image: string;
  imageAlt: string;
  icon: LucideIcon;
  iconClass: string;
  iconBackground: string;
  highlights: string[];
}> = [
  {
    title: "批注修改",
    description: "局部修改利器。把调整意图直接标在图片上，让模型准确理解需要修改的位置和内容。",
    image: "/landing-features/annotation-edit.png",
    imageAlt: "在图片上添加文字和箭头批注",
    icon: PenTool,
    iconClass: "text-[#3f78e0]",
    iconBackground: "bg-[#e9f0fd]",
    highlights: ["箭头批注", "蒙版", "画笔", "文本工具"],
  },
  {
    title: "透明 PNG 支持",
    description: "通过增强提示词配合内置抠图，直接导出透明背景 PNG，省去下载后再次手动抠图的繁琐步骤。",
    image: "/landing-features/transparent-background.png",
    imageAlt: "原图与透明背景抠图效果对比",
    icon: Layers,
    iconClass: "text-[#45a98b]",
    iconBackground: "bg-[#e8f7f2]",
    highlights: ["增强提示词", "自动抠图", "透明背景", "PNG 导出"],
  },
  {
    title: "内置快捷工具",
    description: "常用图片操作集中在一个工具栏中，无需切换多个软件，生成后即可继续完成精修。",
    image: "/landing-features/quick-tools.png",
    imageAlt: "使用图片工具移除照片中的路人",
    icon: Wrench,
    iconClass: "text-[#d89222]",
    iconBackground: "bg-[#fff4df]",
    highlights: ["抠图", "擦除", "标记改图", "扩图", "变清晰"],
  },
  {
    title: "提示词管理",
    description: "统一管理公共提示词和自己的提示词，常用创意可以随时查找、复用和继续调整。",
    image: "/landing-features/prompt-library.png",
    imageAlt: "提示词库的搜索、分类与使用界面",
    icon: BookOpenText,
    iconClass: "text-[#c45f7a]",
    iconBackground: "bg-[#fbeef2]",
    highlights: ["公共提示词", "我的提示词", "快速查找", "一键复用"],
  },
  {
    title: "图库功能",
    description: "生成的每张图片都会自动记录下来，方便回看历史作品、下载成品或继续编辑。",
    image: "/landing-features/image-gallery.png",
    imageAlt: "我的图片历史作品管理界面",
    icon: Images,
    iconClass: "text-[#747ed1]",
    iconBackground: "bg-[#eeeefa]",
    highlights: ["自动记录", "历史回看", "作品下载", "继续编辑"],
  },
];

export function LandingFeatureCarousel() {
  const [activeIndex, setActiveIndex] = useState(0);
  const [isHovered, setIsHovered] = useState(false);
  const [isFocusWithin, setIsFocusWithin] = useState(false);
  const [isTouching, setIsTouching] = useState(false);
  const touchStartX = useRef<number | null>(null);
  const slideCount = productFeatures.length;

  useEffect(() => {
    if (isHovered || isFocusWithin || isTouching) {
      return;
    }
    const timeout = window.setTimeout(() => {
      setActiveIndex((current) => (current + 1) % slideCount);
    }, AUTO_PLAY_DELAY_MS);
    return () => window.clearTimeout(timeout);
  }, [activeIndex, isFocusWithin, isHovered, isTouching, slideCount]);

  const goToSlide = (index: number) => {
    setActiveIndex((index + slideCount) % slideCount);
  };

  const handleTouchEnd = (clientX: number | undefined) => {
    if (touchStartX.current !== null && clientX !== undefined) {
      const distance = touchStartX.current - clientX;
      if (Math.abs(distance) >= SWIPE_THRESHOLD_PX) {
        goToSlide(activeIndex + (distance > 0 ? 1 : -1));
      }
    }
    touchStartX.current = null;
    setIsTouching(false);
  };

  return (
    <section id="tools" className="scroll-mt-4 bg-[#f6f7f9] px-5 py-20 sm:px-8 sm:py-28">
      <div className="mx-auto max-w-6xl">
        <div className="mx-auto max-w-3xl text-center">
          <p className="text-sm font-semibold text-[#9499a3]">创作工具</p>
          <h2 className="mt-3 text-3xl leading-tight font-semibold text-[#343f52] sm:text-5xl">
            从生成到精修，每一步都更顺手
          </h2>
          <p className="mt-5 text-base leading-7 text-[#60697b] sm:text-lg">
            围绕图片创作的常用能力集中在一个工作台中，减少重复操作，让创意更快落地。
          </p>
        </div>

        <div
          className="group relative mt-12 overflow-hidden rounded-md border border-[#dfe5ee] bg-white shadow-[0_18px_52px_rgba(52,63,82,0.08)]"
          role="region"
          aria-roledescription="carousel"
          aria-label="AI 图片创作功能"
          onMouseEnter={() => setIsHovered(true)}
          onMouseLeave={() => setIsHovered(false)}
          onFocusCapture={() => setIsFocusWithin(true)}
          onBlurCapture={(event) => {
            if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
              setIsFocusWithin(false);
            }
          }}
          onTouchStart={(event) => {
            touchStartX.current = event.touches.item(0)?.clientX ?? null;
            setIsTouching(true);
          }}
          onTouchEnd={(event) => handleTouchEnd(event.changedTouches.item(0)?.clientX)}
          onTouchCancel={() => handleTouchEnd(undefined)}
        >
          <div className="overflow-hidden">
            <div
              className="flex transition-transform duration-700 ease-out motion-reduce:transition-none"
              style={{ transform: `translateX(-${activeIndex * 100}%)` }}
            >
              {productFeatures.map((feature, index) => {
                const Icon = feature.icon;
                return (
                  <article
                    key={feature.title}
                    className="grid w-full shrink-0 lg:grid-cols-[0.9fr_1.1fr]"
                    role="group"
                    aria-roledescription="slide"
                    aria-label={`${index + 1} / ${slideCount}：${feature.title}`}
                    aria-hidden={index !== activeIndex}
                  >
                    <div className="order-2 flex min-h-[390px] flex-col justify-center px-7 pt-7 pb-20 sm:px-10 sm:pt-10 sm:pb-20 lg:order-1 lg:min-h-[460px] lg:p-12 lg:pb-16">
                      <div className="flex items-center justify-between gap-4">
                        <span className={`grid size-12 place-items-center rounded-md ${feature.iconBackground} ${feature.iconClass}`}>
                          <Icon className="size-6" aria-hidden="true" />
                        </span>
                        <span className="text-sm font-semibold tabular-nums text-[#9499a3]">
                          {String(index + 1).padStart(2, "0")} / {String(slideCount).padStart(2, "0")}
                        </span>
                      </div>
                      <h3 className="mt-7 text-3xl leading-tight font-semibold text-[#343f52] sm:text-4xl">{feature.title}</h3>
                      <p className="mt-5 text-base leading-7 text-[#60697b] sm:text-lg">{feature.description}</p>
                      <ul className="mt-7 grid gap-3 sm:grid-cols-2">
                        {feature.highlights.map((highlight) => (
                          <li key={highlight} className="flex items-center gap-2 text-sm font-medium text-[#4b5568]">
                            <span className="grid size-5 shrink-0 place-items-center rounded-full bg-[#e8f7f2] text-[#45a98b]">
                              <Check className="size-3" strokeWidth={2.5} aria-hidden="true" />
                            </span>
                            {highlight}
                          </li>
                        ))}
                      </ul>
                    </div>

                    <div className="relative order-1 aspect-[16/10] overflow-hidden border-b border-[#e5e9f0] bg-[#eef3f8] lg:order-2 lg:aspect-auto lg:min-h-[460px] lg:border-b-0 lg:border-l">
                      <Image
                        src={feature.image}
                        alt={feature.imageAlt}
                        fill
                        sizes="(max-width: 1023px) 100vw, 55vw"
                        className="object-cover"
                      />
                    </div>
                  </article>
                );
              })}
            </div>
          </div>

          <button
            type="button"
            className="absolute top-1/2 left-3 z-10 grid size-14 -translate-y-1/2 place-items-center rounded-md bg-transparent text-[#3f78e0] opacity-0 transition-[opacity,color] hover:text-[#2f65c8] focus-visible:opacity-100 group-focus-within:opacity-100 group-hover:opacity-100 sm:left-4"
            aria-label="上一个功能"
            title="上一个功能"
            onClick={() => goToSlide(activeIndex - 1)}
          >
            <ChevronLeft className="size-8" strokeWidth={2.25} aria-hidden="true" />
          </button>

          <button
            type="button"
            className="absolute top-1/2 right-3 z-10 grid size-14 -translate-y-1/2 place-items-center rounded-md bg-transparent text-[#3f78e0] opacity-0 transition-[opacity,color] hover:text-[#2f65c8] focus-visible:opacity-100 group-focus-within:opacity-100 group-hover:opacity-100 sm:right-4"
            aria-label="下一个功能"
            title="下一个功能"
            onClick={() => goToSlide(activeIndex + 1)}
          >
            <ChevronRight className="size-8" strokeWidth={2.25} aria-hidden="true" />
          </button>

          <div
            className="absolute bottom-0 left-1/2 z-10 flex -translate-x-1/2 items-center bg-transparent px-1"
            aria-label="选择功能页面"
          >
            {productFeatures.map((feature, index) => (
              <button
                key={feature.title}
                type="button"
                className="grid size-8 place-items-center"
                aria-label={`显示${feature.title}`}
                aria-current={index === activeIndex ? "true" : undefined}
                title={feature.title}
                onClick={() => goToSlide(index)}
              >
                <span
                  className={`h-2 rounded-full transition-all ${index === activeIndex ? "w-6 bg-[#3f78e0]" : "w-2 bg-[#cdd5e1]"}`}
                  aria-hidden="true"
                />
              </button>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
