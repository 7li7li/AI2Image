"use client";

import { ArrowUpRight, Check, Eraser, Paintbrush, PencilLine, Type, Undo2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type PointerEvent, type ReactNode } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

export type AnnotationEditorImage = {
  name: string;
  type?: string;
  dataUrl: string;
};

export type AnnotationEditResult = {
  file: File;
  dataUrl: string;
  instruction: string;
  insertInstruction: boolean;
};

type Point = {
  x: number;
  y: number;
};

type ArrowMark = {
  id: string;
  type: "arrow";
  start: Point;
  end: Point;
  text: string;
};

type PenMark = {
  id: string;
  type: "pen";
  points: Point[];
};

type MaskMark = {
  id: string;
  type: "mask";
  points: Point[];
  brushSize: number;
};

type TextMark = {
  id: string;
  type: "text";
  position: Point;
  text: string;
};

type AnnotationMark = ArrowMark | PenMark | MaskMark | TextMark;
type AnnotationDraft = Omit<ArrowMark, "id"> | Omit<PenMark, "id"> | Omit<MaskMark, "id">;
type AnnotationTool = "arrow" | "pen" | "mask" | "text";
type PendingArrowMark = Omit<ArrowMark, "id"> & { id: string };
type PendingTextMark = Omit<TextMark, "id"> & { id: string };
type DraggingTextMark = {
  id: string;
  offset: Point;
};

const ANNOTATION_CANVAS_MAX_EDGE = 1400;
const ANNOTATION_STROKE_COLOR = "#ef4444";
const PEN_STROKE_COLOR = "rgba(249, 115, 22, 0.9)";
const TEXT_STROKE_COLOR = "#7c3aed";
const MASK_BRUSH_MIN = 24;
const MASK_BRUSH_MAX = 180;
const MASK_BRUSH_DEFAULT = 72;

function createAnnotationId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function annotationScreenshotFileName() {
  const timestamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
  return `annotation-edit-${timestamp}.png`;
}

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

function distance(a: Point, b: Point) {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

function getCanvasSize(width: number, height: number) {
  const scale = Math.min(1, ANNOTATION_CANVAS_MAX_EDGE / Math.max(width, height));
  return {
    width: Math.max(1, Math.round(width * scale)),
    height: Math.max(1, Math.round(height * scale)),
  };
}

function getCanvasPoint(canvas: HTMLCanvasElement, event: PointerEvent<HTMLCanvasElement>): Point {
  const rect = canvas.getBoundingClientRect();
  return {
    x: clamp(((event.clientX - rect.left) / rect.width) * canvas.width, 0, canvas.width),
    y: clamp(((event.clientY - rect.top) / rect.height) * canvas.height, 0, canvas.height),
  };
}

function wrapCanvasText(ctx: CanvasRenderingContext2D, text: string, maxWidth: number) {
  const normalized = text.replace(/\s+/g, " ").trim();
  if (!normalized) {
    return [];
  }

  const lines: string[] = [];
  let current = "";
  for (const char of normalized) {
    const next = `${current}${char}`;
    if (current && ctx.measureText(next).width > maxWidth) {
      lines.push(current);
      current = char.trimStart();
    } else {
      current = next;
    }
  }
  if (current) {
    lines.push(current);
  }
  return lines;
}

function drawArrow(ctx: CanvasRenderingContext2D, mark: Pick<ArrowMark, "start" | "end">, lineWidth: number) {
  const angle = Math.atan2(mark.end.y - mark.start.y, mark.end.x - mark.start.x);
  const headLength = Math.max(16, lineWidth * 4.5);
  const headAngle = Math.PI / 6;
  const left = {
    x: mark.end.x - headLength * Math.cos(angle - headAngle),
    y: mark.end.y - headLength * Math.sin(angle - headAngle),
  };
  const right = {
    x: mark.end.x - headLength * Math.cos(angle + headAngle),
    y: mark.end.y - headLength * Math.sin(angle + headAngle),
  };

  ctx.save();
  ctx.strokeStyle = ANNOTATION_STROKE_COLOR;
  ctx.lineWidth = lineWidth;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";

  ctx.beginPath();
  ctx.moveTo(mark.start.x, mark.start.y);
  ctx.lineTo(mark.end.x, mark.end.y);
  ctx.stroke();

  ctx.beginPath();
  ctx.moveTo(left.x, left.y);
  ctx.lineTo(mark.end.x, mark.end.y);
  ctx.lineTo(right.x, right.y);
  ctx.stroke();
  ctx.restore();
}

function drawPen(ctx: CanvasRenderingContext2D, points: Point[], lineWidth: number) {
  if (points.length < 2) {
    return;
  }

  ctx.save();
  ctx.strokeStyle = PEN_STROKE_COLOR;
  ctx.lineWidth = lineWidth;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  ctx.beginPath();
  ctx.moveTo(points[0].x, points[0].y);
  for (const point of points.slice(1)) {
    ctx.lineTo(point.x, point.y);
  }
  ctx.stroke();
  ctx.restore();
}

type TextBoxLayout = {
  x: number;
  y: number;
  width: number;
  height: number;
  lineHeight: number;
  lines: string[];
};

function drawMask(ctx: CanvasRenderingContext2D, points: Point[], brushSize: number) {
  if (points.length < 2) {
    return;
  }

  ctx.save();
  ctx.strokeStyle = "rgba(96, 165, 250, 0.34)";
  ctx.lineWidth = brushSize;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  ctx.beginPath();
  ctx.moveTo(points[0].x, points[0].y);
  for (const point of points.slice(1)) {
    ctx.lineTo(point.x, point.y);
  }
  ctx.stroke();
  ctx.restore();
}

function drawLabel(ctx: CanvasRenderingContext2D, text: string, anchor: Point, canvasWidth: number, canvasHeight: number) {
  const fontSize = Math.max(18, Math.round(canvasWidth * 0.018));
  const lineHeight = Math.round(fontSize * 1.32);
  const maxTextWidth = Math.min(360, Math.round(canvasWidth * 0.5));

  ctx.save();
  ctx.font = `600 ${fontSize}px sans-serif`;
  const lines = wrapCanvasText(ctx, text, maxTextWidth);
  if (lines.length === 0) {
    ctx.restore();
    return;
  }

  const textWidth = Math.max(...lines.map((line) => ctx.measureText(line).width));
  const textHeight = lines.length * lineHeight;
  const minTextCenterX = 8 + textWidth / 2;
  const maxTextCenterX = Math.max(minTextCenterX, canvasWidth - textWidth / 2 - 8);
  const textCenterX = clamp(anchor.x, minTextCenterX, maxTextCenterX);
  const preferredY = anchor.y >= textHeight + 12 ? anchor.y - textHeight - 4 : anchor.y + 4;
  const y = clamp(preferredY, 8, Math.max(8, canvasHeight - textHeight - 8));

  ctx.fillStyle = ANNOTATION_STROKE_COLOR;
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  lines.forEach((line, index) => {
    ctx.fillText(line, textCenterX, y + index * lineHeight);
  });
  ctx.restore();
}

function getTextBoxLayout(ctx: CanvasRenderingContext2D, text: string, position: Point, canvasWidth: number, canvasHeight: number): TextBoxLayout | null {
  const fontSize = Math.max(18, Math.round(canvasWidth * 0.018));
  const lineHeight = Math.round(fontSize * 1.32);
  const maxTextWidth = Math.min(360, Math.round(canvasWidth * 0.5));

  ctx.font = `600 ${fontSize}px sans-serif`;
  const lines = wrapCanvasText(ctx, text, maxTextWidth);
  if (lines.length === 0) {
    return null;
  }

  const textWidth = Math.max(...lines.map((line) => ctx.measureText(line).width));
  const textHeight = lines.length * lineHeight;
  const x = clamp(position.x, 8, Math.max(8, canvasWidth - textWidth - 8));
  const y = clamp(position.y, 8, Math.max(8, canvasHeight - textHeight - 8));

  return {
    x,
    y,
    width: textWidth,
    height: textHeight,
    lineHeight,
    lines,
  };
}

function drawTextBox(ctx: CanvasRenderingContext2D, text: string, position: Point, canvasWidth: number, canvasHeight: number) {
  ctx.save();
  const layout = getTextBoxLayout(ctx, text, position, canvasWidth, canvasHeight);
  if (!layout) {
    ctx.restore();
    return;
  }

  ctx.fillStyle = TEXT_STROKE_COLOR;
  ctx.textBaseline = "top";
  layout.lines.forEach((line, index) => {
    ctx.fillText(line, layout.x, layout.y + index * layout.lineHeight);
  });
  ctx.restore();
}

function hitTestTextMark(canvas: HTMLCanvasElement, point: Point, marks: AnnotationMark[]) {
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    return null;
  }

  for (let index = marks.length - 1; index >= 0; index -= 1) {
    const mark = marks[index];
    if (mark.type !== "text") {
      continue;
    }
    const layout = getTextBoxLayout(ctx, mark.text, mark.position, canvas.width, canvas.height);
    if (
      layout &&
      point.x >= layout.x &&
      point.x <= layout.x + layout.width &&
      point.y >= layout.y &&
      point.y <= layout.y + layout.height
    ) {
      return {
        mark,
        offset: {
          x: point.x - layout.x,
          y: point.y - layout.y,
        },
      };
    }
  }
  return null;
}

function drawAnnotationCanvas(
  canvas: HTMLCanvasElement,
  sourceImage: HTMLImageElement,
  marks: AnnotationMark[],
  draft: AnnotationDraft | null,
) {
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    return;
  }

  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(sourceImage, 0, 0, canvas.width, canvas.height);

  const lineWidth = Math.max(3, Math.round(Math.max(canvas.width, canvas.height) * 0.003));

  for (const mark of marks) {
    if (mark.type === "arrow") {
      drawArrow(ctx, mark, lineWidth);
      drawLabel(ctx, mark.text, mark.start, canvas.width, canvas.height);
    } else if (mark.type === "pen") {
      drawPen(ctx, mark.points, lineWidth);
    } else if (mark.type === "mask") {
      drawMask(ctx, mark.points, mark.brushSize);
    } else {
      drawTextBox(ctx, mark.text, mark.position, canvas.width, canvas.height);
    }
  }

  if (draft) {
    if (draft.type === "arrow") {
      drawArrow(ctx, draft, lineWidth);
      drawLabel(ctx, draft.text, draft.start, canvas.width, canvas.height);
    } else if (draft.type === "pen") {
      drawPen(ctx, draft.points, lineWidth);
    } else {
      drawMask(ctx, draft.points, draft.brushSize);
    }
  }
}

function canvasToBlob(canvas: HTMLCanvasElement) {
  return new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (!blob) {
        reject(new Error("导出批注图失败"));
        return;
      }
      resolve(blob);
    }, "image/png");
  });
}

function buildAnnotationInstruction(imageName: string, marks: AnnotationMark[]) {
  const notes = marks
    .filter((mark): mark is ArrowMark => mark.type === "arrow" && Boolean(mark.text.trim()))
    .map((mark, index) => `${index + 1}. ${mark.text.trim()}`);
  const textNotes = marks
    .filter((mark): mark is TextMark => mark.type === "text" && Boolean(mark.text.trim()))
    .map((mark, index) => `${index + 1}. ${mark.text.trim()}`);
  const maskCount = marks.filter((mark) => mark.type === "mask").length;

  return [
    "请根据参考图中的红色批注对原图进行图片编辑。",
    `批注来源：${imageName || "参考图"}`,
    "参考图列表中包含干净原图和本次新增的批注截图；以干净原图作为视觉基础，以批注截图作为编辑说明。",
    "红色箭头批注、橙色画笔圈画、紫色文本标注和半透明浅蓝色蒙版只表示编辑说明，不属于最终画面。",
    maskCount > 0 ? `半透明浅蓝色蒙版区域共有 ${maskCount} 处，表示必须保持不变的保护区域；不要修改、重绘、替换、清理或遮挡这些区域。` : "",
    "保留原图主体、构图、比例、风格、身份特征与关键细节，除非批注明确要求改变。",
    "最终输出必须是干净修订图，移除所有红色箭头、橙色线条、紫色文字、蒙版、边框、编辑界面和其它批注痕迹，同时保持蒙版覆盖区域的原始内容不变。",
    notes.length > 0 ? `箭头批注文字：\n${notes.join("\n")}` : "",
    textNotes.length > 0 ? `插入文本批注：\n${textNotes.join("\n")}` : "",
  ]
    .filter(Boolean)
    .join("\n");
}

export function AnnotationEditorDialog({
  image,
  open,
  onOpenChange,
  onApply,
}: {
  image: AnnotationEditorImage | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onApply: (result: AnnotationEditResult) => void | Promise<void>;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const sourceImageRef = useRef<HTMLImageElement | null>(null);
  const draftRef = useRef<AnnotationDraft | null>(null);
  const labelInputRef = useRef<HTMLInputElement | null>(null);
  const [tool, setTool] = useState<AnnotationTool>("arrow");
  const [marks, setMarks] = useState<AnnotationMark[]>([]);
  const [draft, setDraft] = useState<AnnotationDraft | null>(null);
  const [pendingArrow, setPendingArrow] = useState<PendingArrowMark | null>(null);
  const [pendingArrowText, setPendingArrowText] = useState("");
  const [pendingText, setPendingText] = useState<PendingTextMark | null>(null);
  const [pendingTextValue, setPendingTextValue] = useState("");
  const [draggingText, setDraggingText] = useState<DraggingTextMark | null>(null);
  const [isHoveringText, setIsHoveringText] = useState(false);
  const [maskBrushSize, setMaskBrushSize] = useState(MASK_BRUSH_DEFAULT);
  const [canvasSize, setCanvasSize] = useState({ width: 0, height: 0 });
  const [isApplying, setIsApplying] = useState(false);
  const [isInsertPromptDialogOpen, setIsInsertPromptDialogOpen] = useState(false);

  useEffect(() => {
    if (!open || !image) {
      return;
    }

    setTool("arrow");
    setMarks([]);
    setDraft(null);
    setPendingArrow(null);
    setPendingArrowText("");
    setPendingText(null);
    setPendingTextValue("");
    setDraggingText(null);
    setIsHoveringText(false);
    setIsInsertPromptDialogOpen(false);
    draftRef.current = null;
  }, [image, open]);

  useEffect(() => {
    if (!open || !image?.dataUrl) {
      sourceImageRef.current = null;
      setCanvasSize({ width: 0, height: 0 });
      return;
    }

    let cancelled = false;
    const nextImage = new Image();
    nextImage.onload = () => {
      if (cancelled) {
        return;
      }
      sourceImageRef.current = nextImage;
      setCanvasSize(getCanvasSize(nextImage.naturalWidth || nextImage.width, nextImage.naturalHeight || nextImage.height));
    };
    nextImage.onerror = () => {
      if (!cancelled) {
        toast.error("读取批注图片失败");
      }
    };
    nextImage.src = image.dataUrl;

    return () => {
      cancelled = true;
    };
  }, [image?.dataUrl, open]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const sourceImage = sourceImageRef.current;
    if (!canvas || !sourceImage || canvasSize.width <= 0 || canvasSize.height <= 0) {
      return;
    }
    drawAnnotationCanvas(canvas, sourceImage, marks, pendingArrow ?? draft);
  }, [canvasSize, draft, marks, pendingArrow, pendingText]);

  useEffect(() => {
    if (!pendingArrow && !pendingText) {
      return;
    }
    window.requestAnimationFrame(() => {
      labelInputRef.current?.focus();
      labelInputRef.current?.select();
    });
  }, [pendingArrow, pendingText]);

  const updateDraft = (nextDraft: AnnotationDraft | null) => {
    draftRef.current = nextDraft;
    setDraft(nextDraft);
  };

  const handlePointerDown = (event: PointerEvent<HTMLCanvasElement>) => {
    if (event.button !== 0 || !canvasRef.current || canvasSize.width <= 0) {
      return;
    }

    event.currentTarget.setPointerCapture(event.pointerId);
    const point = getCanvasPoint(event.currentTarget, event);
    const textHit = hitTestTextMark(event.currentTarget, point, marks);
    if (textHit) {
      if (pendingArrow) {
        commitPendingArrow();
      }
      if (pendingText) {
        commitPendingText();
      }
      setDraggingText({ id: textHit.mark.id, offset: textHit.offset });
      setIsHoveringText(true);
      return;
    }

    setIsHoveringText(false);

    if (tool === "arrow") {
      if (pendingArrow) {
        commitPendingArrow();
      }
      if (pendingText) {
        commitPendingText();
      }
      updateDraft({
        type: "arrow",
        start: point,
        end: point,
        text: "",
      });
    } else if (tool === "text") {
      if (pendingArrow) {
        commitPendingArrow();
      }
      if (pendingText) {
        commitPendingText();
      }
      setPendingText({
        id: createAnnotationId(),
        type: "text",
        position: point,
        text: "",
      });
      setPendingTextValue("");
    } else {
      updateDraft({
        type: tool,
        points: [point],
        ...(tool === "mask" ? { brushSize: maskBrushSize } : {}),
      });
    }
  };

  const handlePointerMove = (event: PointerEvent<HTMLCanvasElement>) => {
    const point = getCanvasPoint(event.currentTarget, event);
    if (draggingText) {
      setIsHoveringText(true);
      setMarks((prev) =>
        prev.map((mark) =>
          mark.type === "text" && mark.id === draggingText.id
            ? {
                ...mark,
                position: {
                  x: clamp(point.x - draggingText.offset.x, 0, event.currentTarget.width),
                  y: clamp(point.y - draggingText.offset.y, 0, event.currentTarget.height),
                },
              }
            : mark,
        ),
      );
      return;
    }

    const current = draftRef.current;
    if (!current) {
      setIsHoveringText(Boolean(hitTestTextMark(event.currentTarget, point, marks)));
      return;
    }

    setIsHoveringText(false);
    if (current.type === "arrow") {
      updateDraft({ ...current, end: point });
      return;
    }

    const previousPoint = current.points[current.points.length - 1];
    if (previousPoint && distance(previousPoint, point) < 3) {
      return;
    }
    updateDraft({ ...current, points: [...current.points, point] });
  };

  const completeDraft = (event: PointerEvent<HTMLCanvasElement>) => {
    if (draggingText) {
      setDraggingText(null);
      return;
    }

    const current = draftRef.current;
    if (!current) {
      return;
    }

    const point = getCanvasPoint(event.currentTarget, event);
    let nextMark: AnnotationMark | null = null;
    if (current.type === "arrow") {
      const completed = { ...current, end: point };
      if (distance(completed.start, completed.end) >= 8) {
        setPendingArrow({
          ...completed,
          id: createAnnotationId(),
        });
        setPendingArrowText("");
      }
    } else if (current.type === "pen" || current.type === "mask") {
      const completedPoints = [...current.points, point];
      if (completedPoints.length >= 2 && distance(completedPoints[0], completedPoints[completedPoints.length - 1]) >= 8) {
        nextMark =
          current.type === "mask"
            ? { type: "mask", id: createAnnotationId(), points: completedPoints, brushSize: current.brushSize }
            : { type: "pen", id: createAnnotationId(), points: completedPoints };
      }
    }

    if (nextMark) {
      setMarks((prev) => [...prev, nextMark]);
    }
    updateDraft(null);
  };

  const commitPendingArrow = () => {
    setPendingArrow((current) => {
      if (!current) {
        return null;
      }
      const text = pendingArrowText.trim();
      if (text) {
        setMarks((prev) => [...prev, { ...current, text }]);
      }
      setPendingArrowText("");
      return null;
    });
  };

  const cancelPendingArrow = () => {
    setPendingArrow(null);
    setPendingArrowText("");
  };

  const commitPendingText = () => {
    setPendingText((current) => {
      if (!current) {
        return null;
      }
      const text = pendingTextValue.trim();
      if (text) {
        setMarks((prev) => [...prev, { ...current, text }]);
      }
      setPendingTextValue("");
      return null;
    });
  };

  const cancelPendingText = () => {
    setPendingText(null);
    setPendingTextValue("");
  };

  const undoLastAnnotation = () => {
    if (pendingArrow) {
      cancelPendingArrow();
      return;
    }
    if (pendingText) {
      cancelPendingText();
      return;
    }
    setMarks((prev) => prev.slice(0, -1));
  };

  useEffect(() => {
    if (!open || isApplying) {
      return;
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      const key = event.key.toLowerCase();
      const isUndoShortcut = (event.ctrlKey || event.metaKey) && !event.shiftKey && key === "z";
      if (!isUndoShortcut || event.defaultPrevented) {
        return;
      }

      const target = event.target;
      const isEditableTarget =
        target instanceof HTMLInputElement ||
        target instanceof HTMLTextAreaElement ||
        (target instanceof HTMLElement && target.isContentEditable);
      if (isEditableTarget) {
        return;
      }

      event.preventDefault();
      undoLastAnnotation();
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isApplying, open, pendingArrow, pendingText]);

  const getEffectiveMarks = (): AnnotationMark[] =>
    pendingArrow && pendingArrowText.trim()
      ? [
          ...marks,
          { ...pendingArrow, text: pendingArrowText.trim() },
          ...(pendingText && pendingTextValue.trim() ? [{ ...pendingText, text: pendingTextValue.trim() }] : []),
        ]
      : pendingText && pendingTextValue.trim()
        ? [...marks, { ...pendingText, text: pendingTextValue.trim() }]
        : marks;

  const handleCompleteClick = () => {
    const effectiveMarks = getEffectiveMarks();
    if (effectiveMarks.length === 0) {
      toast.error("请先添加批注");
      return;
    }
    setIsInsertPromptDialogOpen(true);
  };

  const handleApply = async (insertInstruction: boolean) => {
    if (!image || !canvasRef.current || !sourceImageRef.current) {
      return;
    }
    const effectiveMarks: AnnotationMark[] = getEffectiveMarks();
    if (effectiveMarks.length === 0) {
      toast.error("请先添加批注");
      return;
    }

    setIsApplying(true);
    try {
      setMarks(effectiveMarks);
      setPendingArrow(null);
      setPendingArrowText("");
      setPendingText(null);
      setPendingTextValue("");
      drawAnnotationCanvas(canvasRef.current, sourceImageRef.current, effectiveMarks, null);
      const blob = await canvasToBlob(canvasRef.current);
      const dataUrl = canvasRef.current.toDataURL("image/png");
      const file = new File([blob], annotationScreenshotFileName(), { type: "image/png" });
      await onApply({
        file,
        dataUrl,
        instruction: buildAnnotationInstruction(image.name, effectiveMarks),
        insertInstruction,
      });
      setIsInsertPromptDialogOpen(false);
      onOpenChange(false);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "生成批注图失败");
    } finally {
      setIsApplying(false);
    }
  };

  const canUndo = marks.length > 0;
  const labelInputPosition = useMemo(() => {
    if (!pendingArrow || canvasSize.width <= 0 || canvasSize.height <= 0) {
      return null;
    }
    const inputWidth = 220;
    const inputHeight = 40;
    const inputCenterX = clamp(
      pendingArrow.start.x,
      inputWidth / 2 + 8,
      Math.max(inputWidth / 2 + 8, canvasSize.width - inputWidth / 2 - 8),
    );
    const canPlaceAbove = pendingArrow.start.y >= inputHeight + 12;
    return {
      left: `${clamp((inputCenterX / canvasSize.width) * 100, 0, 100)}%`,
      top: `${clamp((pendingArrow.start.y / canvasSize.height) * 100, 0, 100)}%`,
      transform: canPlaceAbove ? "translate(-50%, calc(-100% - 6px))" : "translate(-50%, 6px)",
    };
  }, [canvasSize.height, canvasSize.width, pendingArrow]);
  const textInputPosition = useMemo(() => {
    if (!pendingText || canvasSize.width <= 0 || canvasSize.height <= 0) {
      return null;
    }
    const inputWidth = 220;
    const inputHeight = 40;
    return {
      left: `${clamp((pendingText.position.x / canvasSize.width) * 100, 0, 100)}%`,
      top: `${clamp((pendingText.position.y / canvasSize.height) * 100, 0, 100)}%`,
      transform:
        pendingText.position.x > canvasSize.width - inputWidth
          ? "translate(calc(-100% - 10px), 0)"
          : pendingText.position.y > canvasSize.height - inputHeight
            ? "translate(10px, calc(-100% - 10px))"
            : "translate(10px, 0)",
    };
  }, [canvasSize.height, canvasSize.width, pendingText]);
  const activeInputPosition = pendingArrow ? labelInputPosition : textInputPosition;
  const activeInputValue = pendingArrow ? pendingArrowText : pendingTextValue;
  const hasPendingInput = Boolean(pendingArrow || pendingText);
  const toolHint = {
    arrow: "画出批注箭头后，在箭头尾部输入说明。",
    pen: "用橙色画笔圈出需要说明的区域。",
    mask: "用浅蓝色蒙版覆盖不要修改的保护区域。",
    text: "点击画布插入紫色文本，已生成文本可拖动。",
  }[tool];

  return (
    <>
      <Dialog
        open={open}
        onOpenChange={(nextOpen) => {
          if (!nextOpen) {
            setIsInsertPromptDialogOpen(false);
          }
          onOpenChange(nextOpen);
        }}
      >
      <DialogContent className="flex h-[88vh] w-[min(96vw,1040px)] max-w-none flex-col overflow-hidden rounded-lg p-0">
        <DialogHeader className="border-b border-stone-100 px-5 py-4">
          <DialogTitle className="text-base font-semibold text-stone-950">批注修改</DialogTitle>
        </DialogHeader>

        <div className="flex flex-wrap items-center gap-2 border-b border-stone-100 bg-white/75 px-4 py-3">
          <div className="flex h-9 items-center gap-1 rounded-lg border border-stone-100 bg-white/85 p-1">
            <AnnotationToolButton active={tool === "arrow"} onClick={() => setTool("arrow")} title="批注">
              <ArrowUpRight className="size-4" />
              <span>批注</span>
            </AnnotationToolButton>
            <AnnotationToolButton active={tool === "pen"} onClick={() => setTool("pen")} title="画笔圈选">
              <PencilLine className="size-4" />
              <span>画笔</span>
            </AnnotationToolButton>
            <AnnotationToolButton active={tool === "mask"} onClick={() => setTool("mask")} title="蒙版">
              <Paintbrush className="size-4" />
              <span>蒙版</span>
            </AnnotationToolButton>
            <AnnotationToolButton active={tool === "text"} onClick={() => setTool("text")} title="插入文本">
              <Type className="size-4" />
              <span>文本</span>
            </AnnotationToolButton>
          </div>

          <div className="min-w-[220px] flex-1 text-xs font-medium text-stone-500">
            {toolHint}
          </div>

          {tool === "mask" ? (
            <label className="flex h-9 items-center gap-2 rounded-lg border border-stone-100 bg-white/85 px-3 text-xs font-medium text-stone-600">
              <span className="shrink-0">大小</span>
              <input
                type="range"
                min={MASK_BRUSH_MIN}
                max={MASK_BRUSH_MAX}
                step="4"
                value={maskBrushSize}
                onChange={(event) => setMaskBrushSize(Number(event.target.value) || MASK_BRUSH_DEFAULT)}
                className="w-28 accent-sky-500"
                aria-label="蒙版笔刷大小"
              />
              <span className="w-8 text-right tabular-nums">{maskBrushSize}</span>
            </label>
          ) : null}

          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-9 rounded-lg border-stone-100 bg-white/85"
            onClick={undoLastAnnotation}
            disabled={!canUndo && !hasPendingInput}
          >
            <Undo2 className="size-4" />
            撤销
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-9 rounded-lg border-stone-100 bg-white/85"
            onClick={() => {
              setMarks([]);
              cancelPendingArrow();
              cancelPendingText();
            }}
            disabled={(!canUndo && !hasPendingInput) || isApplying}
          >
            <Eraser className="size-4" />
            清空
          </Button>
          <Button
            type="button"
            size="sm"
            className="h-9 rounded-lg text-white"
            onClick={handleCompleteClick}
            disabled={isApplying || (marks.length === 0 && !hasPendingInput)}
          >
            <Check className="size-4" />
            完成
          </Button>
        </div>

        <div className="min-h-0 flex-1 overflow-auto bg-stone-100/70 p-4">
          <div className="flex min-h-full items-center justify-center">
            {canvasSize.width > 0 ? (
              <div className="relative max-h-full max-w-full">
                <canvas
                  ref={canvasRef}
                  width={canvasSize.width}
                  height={canvasSize.height}
                  onPointerDown={handlePointerDown}
                  onPointerMove={handlePointerMove}
                  onPointerUp={completeDraft}
                  onPointerCancel={() => {
                    setDraggingText(null);
                    setIsHoveringText(false);
                    updateDraft(null);
                  }}
                  onPointerLeave={() => {
                    if (!draggingText) {
                      setIsHoveringText(false);
                    }
                  }}
                  className={cn(
                    "max-h-full max-w-full rounded-lg border border-white/80 bg-white shadow-sm",
                    draggingText || isHoveringText ? "cursor-move" : hasPendingInput || tool === "text" ? "cursor-text" : "cursor-crosshair",
                  )}
                  style={{ touchAction: "none" }}
                />
                {hasPendingInput && activeInputPosition ? (
                  <input
                    ref={labelInputRef}
                    value={activeInputValue}
                    onChange={(event) => {
                      if (pendingArrow) {
                        setPendingArrowText(event.target.value);
                      } else {
                        setPendingTextValue(event.target.value);
                      }
                    }}
                    onBlur={() => {
                      if (pendingArrow) {
                        commitPendingArrow();
                      } else {
                        commitPendingText();
                      }
                    }}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        event.preventDefault();
                        if (pendingArrow) {
                          commitPendingArrow();
                        } else {
                          commitPendingText();
                        }
                      } else if (event.key === "Escape") {
                        event.preventDefault();
                        if (pendingArrow) {
                          cancelPendingArrow();
                        } else {
                          cancelPendingText();
                        }
                      }
                    }}
                    placeholder={pendingArrow ? "输入批注" : "输入文本"}
                    className={cn(
                      "absolute z-10 h-10 w-[220px] rounded-lg border-2 bg-white/96 px-3 text-sm font-semibold shadow-lg outline-none",
                      pendingArrow
                        ? "border-red-400 text-red-600 placeholder:text-red-300"
                        : "border-violet-500 text-violet-700 placeholder:text-violet-300",
                    )}
                    style={activeInputPosition}
                  />
                ) : null}
              </div>
            ) : (
              <div className="text-sm text-stone-500">图片加载中</div>
            )}
          </div>
        </div>
      </DialogContent>
      </Dialog>

      <Dialog open={isInsertPromptDialogOpen} onOpenChange={setIsInsertPromptDialogOpen}>
        <DialogContent className="w-[min(92vw,420px)] rounded-lg border-stone-100 bg-white p-0">
          <DialogHeader className="border-b border-stone-100 px-5 pt-5 pb-4">
            <DialogTitle className="text-base font-semibold text-stone-950">是否自动插入提示词？</DialogTitle>
            <DialogDescription className="pt-2 text-sm leading-6 text-stone-500">
              批注图会加入图生图参考。你可以选择是否把批注说明同步追加到当前输入框。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2 px-5 py-4">
            <Button
              type="button"
              variant="outline"
              className="rounded-lg border-stone-100 bg-white"
              onClick={() => void handleApply(false)}
              disabled={isApplying}
            >
              不插入
            </Button>
            <Button
              type="button"
              className="rounded-lg text-white"
              onClick={() => void handleApply(true)}
              disabled={isApplying}
            >
              插入提示词
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function AnnotationToolButton({
  active,
  children,
  title,
  onClick,
}: {
  active: boolean;
  children: ReactNode;
  title: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      title={title}
      aria-label={title}
      onClick={onClick}
      className={cn(
        "inline-flex h-7 items-center gap-1 rounded-md px-2.5 text-xs font-medium transition",
        active ? "bg-[#171717] text-white" : "text-stone-600 hover:bg-stone-50",
      )}
    >
      {children}
    </button>
  );
}
