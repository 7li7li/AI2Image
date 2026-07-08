"use client";

import {
  type ClipboardEvent,
  type KeyboardEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  FileText,
  ImageIcon,
  Bot,
  LoaderCircle,
  Menu,
  MessageSquare,
  MessageSquarePlus,
  Plus,
  Search,
  Send,
  Sparkles,
  Trash2,
  UserRound,
  X,
} from "lucide-react";
import { toast } from "sonner";

import { ImageLightbox } from "@/components/image-lightbox";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import {
  streamChatCompletion,
  type ChatCompletionContent,
  type ChatCompletionMessage,
} from "@/lib/api";
import { useSiteSettingsStore } from "@/lib/site-settings";
import { useAuthGuard } from "@/lib/use-auth-guard";
import { cn } from "@/lib/utils";
import type { StoredAuthSession } from "@/store/auth";
import {
  CHAT_CONVERSATIONS_CHANGED_EVENT,
  clearChatConversations,
  deleteChatConversation,
  getChatConversationOwnerKey,
  listChatConversations,
  saveChatConversation,
  saveChatConversations,
  type ChatConversation,
  type ChatConversationsChangedDetail,
  type StoredChatAttachment,
  type StoredChatMessage,
} from "@/store/chat-conversations";

const ACTIVE_CHAT_CONVERSATION_STORAGE_KEY = "chatgpt2api:chat_active_conversation_id";
const QUOTA_REFRESH_EVENT = "yanai:quota-refresh";
const CHAT_CONTEXT_TURN_LIMIT = 4;
const MAX_CHAT_ATTACHMENTS = 4;
const MAX_CHAT_ATTACHMENT_BYTES = 8 * 1024 * 1024;
const READABLE_ATTACHMENT_TYPES = new Set([
  "application/json",
  "application/xml",
  "application/javascript",
  "text/csv",
  "text/html",
  "text/markdown",
  "text/plain",
  "text/xml",
]);

type ChatAttachmentLightboxImage = {
  id: string;
  src: string;
  sizeLabel?: string;
  dimensions?: string;
};

function getScopedStorageKey(baseKey: string, ownerKey: string) {
  return ownerKey ? `${baseKey}:${ownerKey}` : baseKey;
}

function createId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function isReadableAttachment(file: File) {
  return file.type.startsWith("text/") || READABLE_ATTACHMENT_TYPES.has(file.type);
}

function readFileAsDataUrl(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(reader.error || new Error("读取附件失败"));
    reader.readAsDataURL(file);
  });
}

function readFileAsText(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(reader.error || new Error("读取附件失败"));
    reader.readAsText(file);
  });
}

function formatFileSize(size: number) {
  if (size < 1024) {
    return `${size} B`;
  }
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function getAttachmentLightboxImages(attachments: StoredChatAttachment[]): ChatAttachmentLightboxImage[] {
  return attachments.flatMap((attachment) =>
    attachment.dataUrl && attachment.type.startsWith("image/")
      ? [
          {
            id: attachment.id,
            src: attachment.dataUrl,
            sizeLabel: formatFileSize(attachment.size),
          },
        ]
      : [],
  );
}

function buildConversationTitle(content: string) {
  const trimmed = content.trim().replace(/\s+/g, " ");
  if (trimmed.length <= 14) {
    return trimmed || "新对话";
  }
  return `${trimmed.slice(0, 14)}...`;
}

function formatConversationTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function sortChatConversations(conversations: ChatConversation[]) {
  return [...conversations].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
}

function pickFallbackConversationId(conversations: ChatConversation[]) {
  const activeConversation = conversations.find((conversation) =>
    conversation.messages.some((message) => message.status === "sending"),
  );
  return activeConversation?.id ?? conversations[0]?.id ?? null;
}

function isSameLocalDay(value: string, date = new Date()) {
  const target = new Date(value);
  if (Number.isNaN(target.getTime())) {
    return false;
  }
  return (
    target.getFullYear() === date.getFullYear() &&
    target.getMonth() === date.getMonth() &&
    target.getDate() === date.getDate()
  );
}

function stringifyAssistantContent(value: unknown) {
  if (typeof value === "string") {
    return value;
  }
  if (Array.isArray(value)) {
    return value
      .map((item) => {
        if (typeof item === "string") {
          return item;
        }
        if (item && typeof item === "object") {
          const candidate = item as { text?: unknown; content?: unknown };
          if (typeof candidate.text === "string") {
            return candidate.text;
          }
          if (typeof candidate.content === "string") {
            return candidate.content;
          }
        }
        return "";
      })
      .filter(Boolean)
      .join("\n");
  }
  if (value === null || value === undefined) {
    return "";
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function conversationMatchesQuery(conversation: ChatConversation, query: string) {
  const normalizedQuery = query.trim().toLowerCase();
  if (!normalizedQuery) {
    return true;
  }

  return (
    conversation.title.toLowerCase().includes(normalizedQuery) ||
    conversation.messages.some((message) =>
      [message.role, message.content, message.status, message.error].some((value) =>
        String(value || "").toLowerCase().includes(normalizedQuery),
      ),
    )
  );
}

function getWorkspaceStats(conversations: ChatConversation[]) {
  let todaySent = 0;
  let assistantReplies = 0;
  let failedReplies = 0;
  let sending = 0;

  for (const conversation of conversations) {
    for (const message of conversation.messages) {
      if (message.status === "sending") {
        sending += 1;
      }
      if (message.role === "user" && isSameLocalDay(message.createdAt)) {
        todaySent += 1;
      }
      if (message.role === "assistant" && message.status === "success") {
        assistantReplies += 1;
      }
      if (message.role === "assistant" && message.status === "error") {
        failedReplies += 1;
      }
    }
  }

  return {
    todaySent,
    assistantReplies,
    failedReplies,
    sending,
    conversations: conversations.length,
  };
}

async function recoverChatHistory(items: ChatConversation[], ownerKey: string) {
  let changed = false;
  const normalized = items.map((conversation) => {
    const messages = conversation.messages.map((message) => {
      if (message.status !== "sending") {
        return message;
      }
      changed = true;
      return {
        ...message,
        status: "error" as const,
        error: "页面刷新或任务中断，未完成的回复已标记为失败",
      };
    });

    const conversationChanged =
      messages.length !== conversation.messages.length ||
      messages.some((message, index) => message !== conversation.messages[index]);
    if (!conversationChanged) {
      return conversation;
    }

    return {
      ...conversation,
      messages,
      updatedAt: new Date().toISOString(),
    };
  });

  if (changed) {
    await saveChatConversations(normalized, ownerKey);
  }
  return normalized;
}

function toApiMessages(messages: StoredChatMessage[]): ChatCompletionMessage[] {
  const eligibleMessages = messages.filter(
    (message) =>
      message.status !== "sending" &&
      message.status !== "error" &&
      (String(message.content || "").trim() || (message.attachments?.length ?? 0) > 0),
  );
  let userTurnCount = 0;
  let windowStartIndex = 0;

  for (let index = eligibleMessages.length - 1; index >= 0; index -= 1) {
    if (eligibleMessages[index].role !== "user") {
      continue;
    }
    userTurnCount += 1;
    if (userTurnCount >= CHAT_CONTEXT_TURN_LIMIT) {
      windowStartIndex = index;
      break;
    }
  }

  const contextMessages =
    userTurnCount >= CHAT_CONTEXT_TURN_LIMIT
      ? [
          ...eligibleMessages.slice(0, windowStartIndex).filter((message) => message.role === "system"),
          ...eligibleMessages.slice(windowStartIndex),
        ]
      : eligibleMessages;

  return contextMessages
    .map((message) => {
      let content: ChatCompletionContent = String(message.content || "");
      if (message.attachments && message.attachments.length > 0) {
        const parts: Exclude<ChatCompletionContent, string> = [
          { type: "text", text: String(message.content || "") || "请根据附件内容回答。" },
        ];
        for (const attachment of message.attachments) {
          if (attachment.dataUrl && attachment.type.startsWith("image/")) {
            parts.push({
              type: "image_url",
              image_url: { url: attachment.dataUrl, detail: "auto" },
            });
          } else if (attachment.text) {
            parts.push({
              type: "text",
              text: `\n\n附件：${attachment.name}\n${attachment.text}`,
            });
          } else {
            parts.push({
              type: "text",
              text: `\n\n附件：${attachment.name}（${attachment.type || "unknown"}，${formatFileSize(attachment.size)}）`,
            });
          }
        }
        content = parts;
      }
      return {
        role: message.role,
        content,
      };
    });
}

function ChatPageContent({ session }: { session: StoredAuthSession }) {
  const conversationsRef = useRef<ChatConversation[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const messagesViewportRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const [workspaceSearch, setWorkspaceSearch] = useState("");
  const [messageDraft, setMessageDraft] = useState("");
  const [pendingAttachments, setPendingAttachments] = useState<StoredChatAttachment[]>([]);
  const [conversations, setConversations] = useState<ChatConversation[]>([]);
  const [selectedConversationId, setSelectedConversationId] = useState<string | null>(null);
  const [isLoadingHistory, setIsLoadingHistory] = useState(true);
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState<{ type: "one"; id: string } | { type: "all" } | null>(null);

  const defaultTextModel = useSiteSettingsStore((state) => state.settings.default_text_model || "gpt-5.5");
  const chatConversationOwnerKey = useMemo(() => getChatConversationOwnerKey(session), [session]);
  const activeConversationStorageKey = useMemo(
    () => getScopedStorageKey(ACTIVE_CHAT_CONVERSATION_STORAGE_KEY, chatConversationOwnerKey),
    [chatConversationOwnerKey],
  );
  const selectedConversation = useMemo(
    () => conversations.find((item) => item.id === selectedConversationId) ?? null,
    [conversations, selectedConversationId],
  );
  const filteredConversations = useMemo(
    () => conversations.filter((conversation) => conversationMatchesQuery(conversation, workspaceSearch)),
    [conversations, workspaceSearch],
  );
  const workspaceStats = useMemo(() => getWorkspaceStats(conversations), [conversations]);
  const selectedConversationSending = Boolean(
    selectedConversation?.messages.some((message) => message.status === "sending"),
  );
  const deleteConfirmTitle = deleteConfirm?.type === "all" ? "清空对话记录" : deleteConfirm?.type === "one" ? "删除对话" : "";
  const deleteConfirmDescription =
    deleteConfirm?.type === "all"
      ? "确认删除全部文本对话记录吗？删除后无法恢复。"
      : deleteConfirm?.type === "one"
        ? "确认删除这条文本对话吗？删除后无法恢复。"
        : "";

  useEffect(() => {
    conversationsRef.current = conversations;
  }, [conversations]);

  useEffect(() => {
    let cancelled = false;

    const loadHistory = async (options: { recoverInterrupted?: boolean; resetBeforeLoad?: boolean } = {}) => {
      if (options.resetBeforeLoad) {
        setIsLoadingHistory(true);
      }
      try {
        const items = await listChatConversations(chatConversationOwnerKey);
        const normalizedItems = options.recoverInterrupted
          ? await recoverChatHistory(items, chatConversationOwnerKey)
          : items;
        if (cancelled) {
          return;
        }
        conversationsRef.current = normalizedItems;
        setConversations(normalizedItems);
        const storedConversationId =
          typeof window !== "undefined" ? window.localStorage.getItem(activeConversationStorageKey) : null;
        setSelectedConversationId((currentConversationId) => {
          if (
            currentConversationId &&
            normalizedItems.some((conversation) => conversation.id === currentConversationId)
          ) {
            return currentConversationId;
          }
          return (
            (storedConversationId && normalizedItems.some((conversation) => conversation.id === storedConversationId)
              ? storedConversationId
              : null) ?? pickFallbackConversationId(normalizedItems)
          );
        });
      } catch (error) {
        const message = error instanceof Error ? error.message : "读取对话记录失败";
        toast.error(message);
      } finally {
        if (!cancelled) {
          setIsLoadingHistory(false);
        }
      }
    };

    const handleConversationsChanged = (event: Event) => {
      const detail = (event as CustomEvent<ChatConversationsChangedDetail>).detail;
      if (detail?.ownerKey !== chatConversationOwnerKey) {
        return;
      }
      void loadHistory();
    };

    window.addEventListener(CHAT_CONVERSATIONS_CHANGED_EVENT, handleConversationsChanged);
    void loadHistory({ recoverInterrupted: true, resetBeforeLoad: true });
    return () => {
      cancelled = true;
      window.removeEventListener(CHAT_CONVERSATIONS_CHANGED_EVENT, handleConversationsChanged);
    };
  }, [activeConversationStorageKey, chatConversationOwnerKey]);

  useEffect(() => {
    if (!selectedConversation) {
      return;
    }
    messagesViewportRef.current?.scrollTo({
      top: messagesViewportRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [selectedConversation?.updatedAt, selectedConversation?.messages.length, selectedConversation]);

  useEffect(() => {
    if (typeof window === "undefined" || isLoadingHistory) {
      return;
    }
    if (selectedConversationId) {
      window.localStorage.setItem(activeConversationStorageKey, selectedConversationId);
    } else {
      window.localStorage.removeItem(activeConversationStorageKey);
    }
  }, [activeConversationStorageKey, isLoadingHistory, selectedConversationId]);

  useEffect(() => {
    if (selectedConversationId && !conversations.some((conversation) => conversation.id === selectedConversationId)) {
      const timeout = window.setTimeout(() => {
        setSelectedConversationId(pickFallbackConversationId(conversations));
      }, 0);
      return () => window.clearTimeout(timeout);
    }
  }, [conversations, selectedConversationId]);

  const persistConversation = async (conversation: ChatConversation) => {
    const nextConversations = sortChatConversations([
      conversation,
      ...conversationsRef.current.filter((item) => item.id !== conversation.id),
    ]);
    conversationsRef.current = nextConversations;
    setConversations(nextConversations);
    await saveChatConversation(conversation, chatConversationOwnerKey);
  };

  const updateConversation = useCallback(
    async (
      conversationId: string,
      updater: (current: ChatConversation | null) => ChatConversation,
      options: { persist?: boolean } = {},
    ) => {
      const current = conversationsRef.current.find((item) => item.id === conversationId) ?? null;
      const nextConversation = updater(current);
      const nextConversations = sortChatConversations([
        nextConversation,
        ...conversationsRef.current.filter((item) => item.id !== conversationId),
      ]);
      conversationsRef.current = nextConversations;
      setConversations(nextConversations);
      if (options.persist !== false) {
        await saveChatConversation(nextConversation, chatConversationOwnerKey);
      }
    },
    [chatConversationOwnerKey],
  );

  const resetComposer = useCallback(() => {
    setMessageDraft("");
    setPendingAttachments([]);
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  }, []);

  const handleAttachmentFiles = async (files: FileList | File[] | null) => {
    const selectedFiles = Array.from(files || []);
    if (selectedFiles.length === 0) {
      return;
    }
    const remainingSlots = MAX_CHAT_ATTACHMENTS - pendingAttachments.length;
    if (remainingSlots <= 0) {
      toast.error(`最多上传 ${MAX_CHAT_ATTACHMENTS} 个附件`);
      return;
    }
    const acceptedFiles = selectedFiles.slice(0, remainingSlots);
    if (selectedFiles.length > acceptedFiles.length) {
      toast.error(`最多上传 ${MAX_CHAT_ATTACHMENTS} 个附件`);
    }
    const nextAttachments: StoredChatAttachment[] = [];
    for (const file of acceptedFiles) {
      if (file.size > MAX_CHAT_ATTACHMENT_BYTES) {
        toast.error(`${file.name} 超过 8 MB`);
        continue;
      }
      try {
        if (file.type.startsWith("image/")) {
          nextAttachments.push({
            id: createId(),
            name: file.name,
            type: file.type || "image/*",
            size: file.size,
            dataUrl: await readFileAsDataUrl(file),
          });
          continue;
        }
        if (isReadableAttachment(file)) {
          nextAttachments.push({
            id: createId(),
            name: file.name,
            type: file.type || "text/plain",
            size: file.size,
            text: await readFileAsText(file),
          });
          continue;
        }
        nextAttachments.push({
          id: createId(),
          name: file.name,
          type: file.type || "application/octet-stream",
          size: file.size,
        });
      } catch (error) {
        toast.error(error instanceof Error ? error.message : `读取 ${file.name} 失败`);
      }
    }
    if (nextAttachments.length > 0) {
      setPendingAttachments((current) => [...current, ...nextAttachments]);
    }
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  };

  const handleDraftPaste = (event: ClipboardEvent<HTMLTextAreaElement>) => {
    const imageFiles = Array.from(event.clipboardData.files).filter((file) => file.type.startsWith("image/"));
    if (imageFiles.length === 0) {
      for (const item of Array.from(event.clipboardData.items)) {
        if (item.type.startsWith("image/")) {
          const file = item.getAsFile();
          if (file) {
            imageFiles.push(file);
          }
        }
      }
    }
    if (imageFiles.length === 0) {
      return;
    }

    event.preventDefault();
    void handleAttachmentFiles(
      imageFiles.map((file, index) => {
        if (file.name) {
          return file;
        }
        const extension = file.type.split("/")[1] || "png";
        return new File([file], `pasted-image-${Date.now()}-${index + 1}.${extension}`, {
          type: file.type || "image/png",
        });
      }),
    );
  };

  const removePendingAttachment = (id: string) => {
    setPendingAttachments((current) => current.filter((attachment) => attachment.id !== id));
  };

  const handleCreateDraft = () => {
    setSelectedConversationId(null);
    resetComposer();
    textareaRef.current?.focus();
    toast.success("已新建空白对话");
  };

  const handleDeleteConversation = async (id: string) => {
    const nextConversations = conversations.filter((item) => item.id !== id);
    conversationsRef.current = nextConversations;
    setConversations(nextConversations);
    if (selectedConversationId === id) {
      setSelectedConversationId(pickFallbackConversationId(nextConversations));
      resetComposer();
    }

    try {
      await deleteChatConversation(id, chatConversationOwnerKey);
    } catch (error) {
      const message = error instanceof Error ? error.message : "删除对话失败";
      toast.error(message);
      const items = await listChatConversations(chatConversationOwnerKey);
      conversationsRef.current = items;
      setConversations(items);
    }
  };

  const handleClearHistory = async () => {
    try {
      await clearChatConversations(chatConversationOwnerKey);
      conversationsRef.current = [];
      setConversations([]);
      setSelectedConversationId(null);
      resetComposer();
      toast.success("已清空对话记录");
    } catch (error) {
      const message = error instanceof Error ? error.message : "清空对话记录失败";
      toast.error(message);
    }
  };

  const openDeleteConversationConfirm = (id: string) => {
    setIsHistoryOpen(false);
    setDeleteConfirm({ type: "one", id });
  };

  const openClearHistoryConfirm = () => {
    setIsHistoryOpen(false);
    setDeleteConfirm({ type: "all" });
  };

  const handleConfirmDelete = async () => {
    const target = deleteConfirm;
    setDeleteConfirm(null);
    if (!target) {
      return;
    }
    if (target.type === "all") {
      await handleClearHistory();
      return;
    }
    await handleDeleteConversation(target.id);
  };

  const handleSubmit = async () => {
    const content = messageDraft.trim();
    const attachments = pendingAttachments;
    if (!content && attachments.length === 0) {
      toast.error("请输入消息或上传附件");
      return;
    }
    if (isSending || selectedConversationSending) {
      toast.error("当前对话仍在回复中");
      return;
    }

    const targetConversation = selectedConversationId
      ? conversationsRef.current.find((conversation) => conversation.id === selectedConversationId) ?? null
      : null;
    const now = new Date().toISOString();
    const conversationId = targetConversation?.id ?? createId();
    const userMessage: StoredChatMessage = {
      id: createId(),
      role: "user",
      content,
      createdAt: now,
      status: "success",
      attachments,
    };
    const assistantMessage: StoredChatMessage = {
      id: createId(),
      role: "assistant",
      content: "",
      createdAt: now,
      status: "sending",
    };
    const baseConversation: ChatConversation = targetConversation
      ? {
          ...targetConversation,
          ownerKey: chatConversationOwnerKey,
          updatedAt: now,
          messages: [...targetConversation.messages, userMessage, assistantMessage],
        }
      : {
          id: conversationId,
          ownerKey: chatConversationOwnerKey,
          title: buildConversationTitle(content),
          model: defaultTextModel,
          createdAt: now,
          updatedAt: now,
          messages: [userMessage, assistantMessage],
        };

    setSelectedConversationId(conversationId);
    resetComposer();
    await persistConversation(baseConversation);

    setIsSending(true);
    try {
      let assistantContent = "";
      await streamChatCompletion(toApiMessages(baseConversation.messages), baseConversation.model, async (event) => {
        if (event.type !== "delta" || !event.content) {
          return;
        }
        assistantContent += event.content;
        const updatedAt = new Date().toISOString();
        await updateConversation(conversationId, (current) => {
          const conversation = current ?? baseConversation;
          return {
            ...conversation,
            updatedAt,
            messages: conversation.messages.map((message) =>
              message.id === assistantMessage.id
                ? {
                    ...message,
                    content: assistantContent,
                    createdAt: updatedAt,
                    status: "sending" as const,
                    error: undefined,
                  }
                : message,
            ),
          };
        });
      });
      assistantContent = stringifyAssistantContent(assistantContent).trim();
      if (!assistantContent) {
        throw new Error("上游没有返回文本内容");
      }
      const completedAt = new Date().toISOString();
      await updateConversation(conversationId, (current) => {
        const conversation = current ?? baseConversation;
        return {
          ...conversation,
          updatedAt: completedAt,
          messages: conversation.messages.map((message) =>
            message.id === assistantMessage.id
              ? {
                  ...message,
                  content: assistantContent,
                  createdAt: completedAt,
                  status: "success" as const,
                  error: undefined,
                }
              : message,
          ),
        };
      });
      window.dispatchEvent(new Event(QUOTA_REFRESH_EVENT));
    } catch (error) {
      const message = error instanceof Error ? error.message : "发送消息失败";
      const failedAt = new Date().toISOString();
      await updateConversation(conversationId, (current) => {
        const conversation = current ?? baseConversation;
        return {
          ...conversation,
          updatedAt: failedAt,
          messages: conversation.messages.map((item) =>
            item.id === assistantMessage.id
              ? {
                  ...item,
                  content: item.content,
                  createdAt: failedAt,
                  status: "error" as const,
                  error: message,
                }
              : item,
          ),
        };
      });
      toast.error(message);
    } finally {
      setIsSending(false);
    }
  };

  const handleDraftKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) {
      return;
    }
    event.preventDefault();
    void handleSubmit();
  };

  return (
    <>
      <section className="grid h-full min-h-0 w-full grid-cols-1 gap-3 overflow-y-auto lg:grid-cols-[280px_minmax(0,1fr)] lg:overflow-hidden">
        <div className="hidden min-h-0 overflow-hidden rounded-xl border border-white/80 bg-white/88 shadow-[0_20px_70px_-45px_rgba(15,23,42,0.45)] backdrop-blur-xl lg:flex">
          <ChatStudioSidebar
            conversations={filteredConversations}
            isLoadingHistory={isLoadingHistory}
            selectedConversationId={selectedConversationId}
            searchValue={workspaceSearch}
            onSearchChange={setWorkspaceSearch}
            workspaceStats={workspaceStats}
            formatConversationTime={formatConversationTime}
            onCreateDraft={handleCreateDraft}
            onClearHistory={openClearHistoryConfirm}
            onSelectConversation={setSelectedConversationId}
            onDeleteConversation={openDeleteConversationConfirm}
          />
        </div>

        <Dialog open={isHistoryOpen} onOpenChange={setIsHistoryOpen}>
          <DialogContent className="flex h-[88vh] w-[92vw] max-w-[430px] flex-col overflow-hidden rounded-lg p-0">
            <DialogTitle className="sr-only">对话记录</DialogTitle>
            <ChatStudioSidebar
              conversations={filteredConversations}
              isLoadingHistory={isLoadingHistory}
              selectedConversationId={selectedConversationId}
              searchValue={workspaceSearch}
              onSearchChange={setWorkspaceSearch}
              workspaceStats={workspaceStats}
              formatConversationTime={formatConversationTime}
              onCreateDraft={() => {
                handleCreateDraft();
                setIsHistoryOpen(false);
              }}
              onClearHistory={openClearHistoryConfirm}
              onSelectConversation={(id) => {
                setSelectedConversationId(id);
                setIsHistoryOpen(false);
              }}
              onDeleteConversation={openDeleteConversationConfirm}
            />
          </DialogContent>
        </Dialog>

        <div className="flex min-h-0 flex-col gap-3 overflow-hidden">
          <div className="flex items-center justify-between gap-2 lg:hidden">
            <Button
              variant="outline"
              className="h-10 flex-1 rounded-lg border-rose-100 bg-white/75 text-stone-700 shadow-sm"
              onClick={() => setIsHistoryOpen(true)}
            >
              <Menu className="mr-2 size-4" />
              对话记录 ({conversations.length})
            </Button>
            <Button className="h-10 rounded-lg text-white shadow-sm" onClick={handleCreateDraft}>
              <Plus className="size-4" />
              新建
            </Button>
            <Button
              variant="outline"
              className="h-10 rounded-lg border-rose-100 bg-white/75 px-3 text-stone-600 shadow-sm"
              onClick={openClearHistoryConfirm}
              disabled={conversations.length === 0}
            >
              <Trash2 className="size-4" />
            </Button>
          </div>

          <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl">
            <div
              ref={messagesViewportRef}
              className="min-h-0 flex-1 overflow-y-auto px-3 py-4 pb-56 [scrollbar-color:rgba(148,163,184,.45)_transparent] [scrollbar-width:thin] sm:px-5 sm:pb-60 [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-stone-300/65 [&::-webkit-scrollbar-track]:bg-transparent"
            >
              <div className="mx-auto w-full max-w-6xl">
                <ChatMessages conversation={selectedConversation} />
              </div>
            </div>

            <div className="pointer-events-none absolute inset-x-0 bottom-4 z-10 px-3 sm:px-6 lg:px-10">
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept="image/*,.txt,.md,.json,.csv,.xml,.html,.js,.ts,.tsx,.css"
                className="hidden"
                onChange={(event) => void handleAttachmentFiles(event.target.files)}
              />
              {pendingAttachments.length > 0 ? (
                <div className="pointer-events-auto mx-auto mb-3 flex max-w-4xl flex-wrap gap-2">
                  {pendingAttachments.map((attachment) => (
                    <div
                      key={attachment.id}
                      className="inline-flex max-w-full items-center gap-2 rounded-lg border border-rose-100 bg-white/82 px-2.5 py-1.5 text-xs text-stone-600"
                    >
                      {attachment.type.startsWith("image/") ? (
                        <ImageIcon className="size-3.5 shrink-0 text-rose-500" />
                      ) : (
                        <FileText className="size-3.5 shrink-0 text-stone-400" />
                      )}
                      <span className="max-w-[180px] truncate">{attachment.name}</span>
                      <span className="shrink-0 text-stone-400">{formatFileSize(attachment.size)}</span>
                      <button
                        type="button"
                        className="grid size-5 shrink-0 place-items-center rounded-md text-stone-400 hover:bg-rose-50 hover:text-rose-500"
                        onClick={() => removePendingAttachment(attachment.id)}
                        aria-label="移除附件"
                      >
                        <X className="size-3.5" />
                      </button>
                    </div>
                  ))}
                </div>
              ) : null}
              <div className="pointer-events-auto mx-auto max-w-4xl rounded-[24px] border border-stone-200/80 bg-white/95 p-3 shadow-[0_24px_90px_-45px_rgba(15,23,42,0.55)] backdrop-blur-xl">
                <Textarea
                  ref={textareaRef}
                  value={messageDraft}
                  onChange={(event) => setMessageDraft(event.target.value)}
                  onKeyDown={handleDraftKeyDown}
                  onPaste={handleDraftPaste}
                  placeholder="输入消息..."
                  className="max-h-44 min-h-20 resize-none rounded-none border-0 bg-transparent px-0 py-0 text-sm leading-6 shadow-none focus-visible:border-transparent focus-visible:ring-0"
                />
                <div className="mt-3 flex min-h-9 items-center gap-2">
                  <Button
                    variant="ghost"
                    size="icon"
                    className="size-8 rounded-full text-stone-500 hover:bg-stone-100"
                    onClick={() => fileInputRef.current?.click()}
                    disabled={isSending || selectedConversationSending || pendingAttachments.length >= MAX_CHAT_ATTACHMENTS}
                    aria-label="上传附件"
                  >
                    <Plus className="size-4" />
                  </Button>
                  <div className="min-w-0 flex-1" />
                  {selectedConversationSending ? (
                    <span className="hidden items-center gap-1.5 rounded-full bg-rose-50 px-2.5 py-1.5 text-xs font-medium text-rose-600 sm:inline-flex">
                      <LoaderCircle className="size-3.5 animate-spin" />
                      回复中
                    </span>
                  ) : null}
                  <div className="inline-flex min-w-0 max-w-[48vw] items-center gap-1.5 text-xs font-medium text-stone-600 sm:max-w-[310px]">
                    <Bot className="size-3.5 shrink-0 text-stone-300" />
                    <span className="min-w-0 truncate">{selectedConversation?.model || defaultTextModel}</span>
                    <span
                      className="inline-flex shrink-0 items-center gap-1 border-l border-stone-200 pl-2 text-stone-500"
                      title="每次成功回复扣除 1 点额度"
                    >
                      <Sparkles className="size-3 shrink-0 text-stone-300" />
                      1/次
                    </span>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="size-8 rounded-full text-stone-500 hover:bg-stone-100"
                    onClick={resetComposer}
                    disabled={!messageDraft && pendingAttachments.length === 0}
                    aria-label="清空输入"
                  >
                    <X className="size-4" />
                  </Button>
                  <Button
                    size="icon"
                    className="size-9 rounded-full bg-stone-700 text-white shadow-none hover:bg-stone-800"
                    onClick={() => void handleSubmit()}
                    disabled={(!messageDraft.trim() && pendingAttachments.length === 0) || isSending || selectedConversationSending}
                    aria-label="发送消息"
                  >
                    {isSending || selectedConversationSending ? (
                      <LoaderCircle className="size-4 animate-spin" />
                    ) : (
                      <Send className="size-4" />
                    )}
                  </Button>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {deleteConfirm ? (
        <Dialog open onOpenChange={(open) => (!open ? setDeleteConfirm(null) : null)}>
          <DialogContent showCloseButton={false} className="rounded-lg p-6">
            <DialogHeader className="gap-2">
              <DialogTitle>{deleteConfirmTitle}</DialogTitle>
              <DialogDescription className="text-sm leading-6">
                {deleteConfirmDescription}
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button variant="outline" onClick={() => setDeleteConfirm(null)}>
                取消
              </Button>
              <Button className="bg-rose-600 text-white hover:bg-rose-700" onClick={() => void handleConfirmDelete()}>
                确认删除
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      ) : null}
    </>
  );
}

function ChatStudioSidebar({
  conversations,
  isLoadingHistory,
  selectedConversationId,
  searchValue,
  onSearchChange,
  workspaceStats,
  formatConversationTime,
  onCreateDraft,
  onClearHistory,
  onSelectConversation,
  onDeleteConversation,
}: {
  conversations: ChatConversation[];
  isLoadingHistory: boolean;
  selectedConversationId: string | null;
  searchValue: string;
  onSearchChange: (value: string) => void;
  workspaceStats: ReturnType<typeof getWorkspaceStats>;
  formatConversationTime: (value: string) => string;
  onCreateDraft: () => void;
  onClearHistory: () => void | Promise<void>;
  onSelectConversation: (id: string) => void;
  onDeleteConversation: (id: string) => void | Promise<void>;
}) {
  return (
    <aside className="flex h-full min-h-0 w-full flex-col bg-white/32">
      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3 [scrollbar-color:rgba(244,114,182,.45)_transparent] [scrollbar-width:thin] [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-rose-300/55 [&::-webkit-scrollbar-track]:bg-transparent">
        <div className="min-h-[320px]">
          <div className="mb-3 flex items-center justify-between gap-2">
            <div>
              <div className="text-xs font-bold text-stone-500">最近对话</div>
              <div className="mt-1 text-[11px] text-stone-400">{conversations.length} 条记录</div>
            </div>
          </div>

          <div className="flex h-full min-h-0 flex-col gap-3">
            <div className="flex items-center gap-2">
              <Button className="h-10 flex-1 rounded-lg text-white" onClick={onCreateDraft}>
                <MessageSquarePlus className="size-4" />
                新建对话
              </Button>
              <Button
                variant="outline"
                className="h-10 rounded-lg border-rose-100 bg-white/75 px-3 text-stone-600 hover:bg-white"
                onClick={() => void onClearHistory()}
                disabled={conversations.length === 0}
                aria-label="清空对话记录"
              >
                <Trash2 className="size-4" />
              </Button>
            </div>

            <label className="relative block">
              <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-stone-400" />
              <input
                value={searchValue}
                onChange={(event) => onSearchChange(event.target.value)}
                placeholder="搜索对话、消息"
                aria-label="搜索对话、消息"
                className="h-10 w-full rounded-lg border border-[var(--yan-border)] bg-white/72 pl-9 pr-3 text-sm text-stone-700 outline-none transition placeholder:text-stone-400 focus:border-rose-200 focus:bg-white focus:ring-4 focus:ring-rose-100/60"
              />
            </label>

            <div className="min-h-0 flex-1 space-y-2 overflow-y-auto">
              {isLoadingHistory ? (
                <div className="flex items-center gap-2 px-2 py-3 text-sm text-stone-500">
                  <LoaderCircle className="size-4 animate-spin" />
                  正在读取对话记录
                </div>
              ) : conversations.length === 0 ? (
                <div className="rounded-lg border border-dashed border-rose-100 bg-white/45 px-3 py-4 text-sm leading-6 text-stone-500">
                  暂无文本对话。
                </div>
              ) : (
                conversations.map((conversation) => {
                  const active = conversation.id === selectedConversationId;
                  const sendingCount = conversation.messages.filter((message) => message.status === "sending").length;
                  const userTurnCount = conversation.messages.filter((message) => message.role === "user").length;
                  return (
                    <div
                      key={conversation.id}
                      className={cn(
                        "group relative w-full rounded-lg border px-3 py-2 text-left transition sm:py-3",
                        active
                          ? "border-rose-100 bg-[#2d1d26] text-white shadow-sm"
                          : "border-stone-200/80 bg-white/28 text-stone-700 hover:border-rose-100 hover:bg-white/52",
                      )}
                    >
                      <button
                        type="button"
                        onClick={() => onSelectConversation(conversation.id)}
                        className="block w-full pr-8 text-left"
                      >
                        <div className="truncate text-sm font-semibold">
                          <span className="truncate">{conversation.title}</span>
                        </div>
                        <div className={cn("mt-1 text-xs", active ? "text-white/62" : "text-stone-400")}>
                          {userTurnCount} 轮 · {formatConversationTime(conversation.updatedAt)}
                        </div>
                        {sendingCount > 0 ? (
                          <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px]">
                            <span className="rounded-full bg-pink-50 px-2 py-1 text-pink-600">回复中 {sendingCount}</span>
                          </div>
                        ) : null}
                      </button>
                      <button
                        type="button"
                        onClick={() => void onDeleteConversation(conversation.id)}
                        className={cn(
                          "absolute top-3 right-2 inline-flex size-7 items-center justify-center rounded-md opacity-0 transition group-hover:opacity-100",
                          active
                            ? "text-white/55 hover:bg-white/10 hover:text-white"
                            : "text-stone-400 hover:bg-rose-50 hover:text-rose-500",
                        )}
                        aria-label="删除对话"
                      >
                        <Trash2 className="size-4" />
                      </button>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="border-t border-rose-100/70 p-3">
        <div className="grid grid-cols-2 gap-2">
          <SidebarMetric label="今日发送" value={workspaceStats.todaySent} />
          <SidebarMetric label="回复数" value={workspaceStats.assistantReplies} />
          <SidebarMetric label="处理中" value={workspaceStats.sending} />
          <SidebarMetric label="对话数" value={workspaceStats.conversations} />
        </div>
      </div>
    </aside>
  );
}

function ChatMessages({ conversation }: { conversation: ChatConversation | null }) {
  const [lightboxImages, setLightboxImages] = useState<ChatAttachmentLightboxImage[]>([]);
  const [lightboxOpen, setLightboxOpen] = useState(false);
  const [lightboxIndex, setLightboxIndex] = useState(0);

  const openAttachmentLightbox = useCallback((images: ChatAttachmentLightboxImage[], index: number) => {
    if (images.length === 0) {
      return;
    }
    setLightboxImages(images);
    setLightboxIndex(Math.max(0, Math.min(index, images.length - 1)));
    setLightboxOpen(true);
  }, []);

  if (!conversation || conversation.messages.length === 0) {
    return (
      <div className="flex min-h-[calc(100dvh-260px)] items-center justify-center pb-20">
        <div className="text-center">
          <h1 className="text-2xl font-semibold tracking-tight text-stone-950">你好，想聊些什么？</h1>
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="space-y-4">
        {conversation.messages.map((message) => {
          const isUser = message.role === "user";
          const isAssistant = message.role === "assistant";
          return (
            <div key={message.id} className={cn("flex gap-3", isUser ? "justify-end" : "justify-start")}>
              {!isUser ? (
                <div className="mt-1 grid size-8 shrink-0 place-items-center rounded-lg border border-rose-100 bg-white/75 text-rose-500">
                  {isAssistant ? <Bot className="size-4" /> : <MessageSquare className="size-4" />}
                </div>
              ) : null}
              <div
                className={cn(
                  "max-w-[min(780px,82%)] rounded-lg px-4 py-3 text-sm leading-6 shadow-sm",
                  isUser
                    ? "bg-[#2d1d26] text-white"
                    : message.status === "error"
                      ? "border border-red-100 bg-red-50 text-red-700"
                      : "border border-rose-100/80 bg-white/82 text-stone-800",
                )}
              >
                {message.status === "sending" ? (
                  message.content ? (
                    <div className="space-y-2">
                      <MarkdownContent content={message.content} />
                      <div className="flex items-center gap-2 text-xs text-stone-400">
                        <LoaderCircle className="size-3.5 animate-spin" />
                        正在回复
                      </div>
                    </div>
                  ) : (
                    <div className="flex items-center gap-2 text-stone-500">
                      <LoaderCircle className="size-4 animate-spin" />
                      正在回复
                    </div>
                  )
                ) : message.status === "error" ? (
                  <div className="space-y-2">
                    {message.content ? <MarkdownContent content={message.content} /> : null}
                    <div>{message.error || "回复失败"}</div>
                  </div>
                ) : isAssistant ? (
                  <MarkdownContent content={message.content} />
                ) : (
                  <div className="space-y-2">
                    {message.content ? <div className="whitespace-pre-wrap break-words">{message.content}</div> : null}
                    {message.attachments && message.attachments.length > 0 ? (
                      <ChatAttachmentList
                        attachments={message.attachments}
                        compact={isUser}
                        onOpenLightbox={openAttachmentLightbox}
                      />
                    ) : null}
                  </div>
                )}
              </div>
              {isUser ? (
                <div className="mt-1 grid size-8 shrink-0 place-items-center rounded-lg border border-stone-200 bg-white/75 text-stone-500">
                  <UserRound className="size-4" />
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
      <ImageLightbox
        images={lightboxImages}
        currentIndex={lightboxIndex}
        open={lightboxOpen}
        onOpenChange={setLightboxOpen}
        onIndexChange={setLightboxIndex}
      />
    </>
  );
}

function ChatAttachmentList({
  attachments,
  compact = false,
  onOpenLightbox,
}: {
  attachments: StoredChatAttachment[];
  compact?: boolean;
  onOpenLightbox: (images: ChatAttachmentLightboxImage[], index: number) => void;
}) {
  const imageAttachments = getAttachmentLightboxImages(attachments);

  return (
    <div className="flex flex-wrap gap-2">
      {attachments.map((attachment) => {
        const imageIndex = imageAttachments.findIndex((image) => image.id === attachment.id);

        return (
          <div
            key={attachment.id}
            className={cn(
              "overflow-hidden rounded-lg border text-xs",
              compact ? "border-white/15 bg-white/10 text-white/80" : "border-rose-100 bg-white/75 text-stone-600",
            )}
          >
            {attachment.dataUrl && attachment.type.startsWith("image/") ? (
              <button
                type="button"
                onClick={() => onOpenLightbox(imageAttachments, Math.max(0, imageIndex))}
                className="group block cursor-zoom-in bg-stone-100"
                aria-label={`放大查看 ${attachment.name || "图片附件"}`}
              >
                <img
                  src={attachment.dataUrl}
                  alt={attachment.name}
                  className="h-20 w-28 object-cover transition duration-200 group-hover:scale-[1.02] group-hover:brightness-90"
                  loading="lazy"
                  decoding="async"
                />
              </button>
            ) : null}
            <div className="flex max-w-[220px] items-center gap-2 px-2 py-1.5">
              {attachment.type.startsWith("image/") ? (
                <ImageIcon className="size-3.5 shrink-0" />
              ) : (
                <FileText className="size-3.5 shrink-0" />
              )}
              <span className="truncate">{attachment.name}</span>
              <span className={cn("shrink-0", compact ? "text-white/50" : "text-stone-400")}>
                {formatFileSize(attachment.size)}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function parseInlineMarkdown(text: string) {
  const nodes: React.ReactNode[] = [];
  const pattern = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*|\[[^\]]+\]\([^)]+\))/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(text.slice(lastIndex, match.index));
    }
    const token = match[0];
    const key = `${match.index}-${token}`;
    if (token.startsWith("`") && token.endsWith("`")) {
      nodes.push(
        <code key={key} className="rounded bg-stone-100 px-1.5 py-0.5 font-mono text-[0.92em] text-rose-700">
          {token.slice(1, -1)}
        </code>,
      );
    } else if (token.startsWith("**") && token.endsWith("**")) {
      nodes.push(<strong key={key}>{parseInlineMarkdown(token.slice(2, -2))}</strong>);
    } else if (token.startsWith("*") && token.endsWith("*")) {
      nodes.push(<em key={key}>{parseInlineMarkdown(token.slice(1, -1))}</em>);
    } else {
      const linkMatch = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(token);
      if (linkMatch) {
        const href = safeMarkdownHref(linkMatch[2]);
        nodes.push(
          <a
            key={key}
            href={href}
            target="_blank"
            rel="noreferrer"
            className="font-medium text-rose-700 underline decoration-rose-300 underline-offset-4"
          >
            {parseInlineMarkdown(linkMatch[1])}
          </a>,
        );
      } else {
        nodes.push(token);
      }
    }
    lastIndex = match.index + token.length;
  }
  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex));
  }
  return nodes;
}

function safeMarkdownHref(value: string) {
  const href = value.trim();
  if (/^(https?:|mailto:|\/)/i.test(href)) {
    return href;
  }
  return "#";
}

function InlineMarkdown({ text }: { text: string }) {
  return <>{parseInlineMarkdown(text)}</>;
}

function markdownHeadingClassName(level: number) {
  if (level <= 2) {
    return "text-base font-bold leading-7 text-stone-950";
  }
  if (level === 3) {
    return "text-[0.95rem] font-bold leading-7 text-stone-950";
  }
  return "text-sm font-bold leading-6 text-stone-950";
}

type MarkdownBlock =
  | { type: "blockquote"; text: string }
  | { type: "code"; language: string; text: string }
  | { type: "heading"; level: number; text: string }
  | { type: "list"; ordered: boolean; items: string[] }
  | { type: "paragraph"; text: string };

function getFenceMatch(line: string) {
  return /^ {0,3}(`{3,}|~{3,})[ \t]*([^`]*)?$/.exec(line.trimEnd());
}

function isFenceClose(line: string, fence: string) {
  const fenceMarker = fence.startsWith("`") ? "`{3,}" : "~{3,}";
  return new RegExp(`^ {0,3}${fenceMarker}[ \\t]*$`).test(line.trimEnd());
}

function getHeadingMatch(line: string) {
  return /^ {0,3}(#{1,6})[ \t]*(\S.*)$/.exec(line.trimEnd());
}

function getListMatch(line: string) {
  const ordered = /^ {0,3}\d+\.[ \t]+(.+)$/.exec(line);
  if (ordered) {
    return { ordered: true, text: ordered[1] };
  }
  const unordered = /^ {0,3}[-*+][ \t]+(.+)$/.exec(line);
  if (unordered) {
    return { ordered: false, text: unordered[1] };
  }
  return null;
}

function getBlockquoteMatch(line: string) {
  return /^ {0,3}>[ \t]?(.*)$/.exec(line);
}

function parseMarkdownBlocks(content: string): MarkdownBlock[] {
  const lines = content.replace(/\r\n?/g, "\n").split("\n");
  const blocks: MarkdownBlock[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }

    const fenceMatch = getFenceMatch(line);
    if (fenceMatch) {
      const codeLines: string[] = [];
      const fence = fenceMatch[1];
      const language = (fenceMatch[2] || "").trim().split(/\s+/)[0] || "";
      index += 1;
      while (index < lines.length && !isFenceClose(lines[index], fence)) {
        codeLines.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) {
        index += 1;
      }
      blocks.push({ type: "code", language, text: codeLines.join("\n") });
      continue;
    }

    const headingMatch = getHeadingMatch(line);
    if (headingMatch) {
      blocks.push({
        type: "heading",
        level: headingMatch[1].length,
        text: headingMatch[2].replace(/[ \t]+#+[ \t]*$/, ""),
      });
      index += 1;
      continue;
    }

    const quoteMatch = getBlockquoteMatch(line);
    if (quoteMatch) {
      const quoteLines: string[] = [];
      while (index < lines.length) {
        if (!lines[index].trim()) {
          quoteLines.push("");
          index += 1;
          continue;
        }
        const currentQuote = getBlockquoteMatch(lines[index]);
        if (!currentQuote) {
          break;
        }
        quoteLines.push(currentQuote[1]);
        index += 1;
      }
      blocks.push({ type: "blockquote", text: quoteLines.join("\n").trim() });
      continue;
    }

    const listMatch = getListMatch(line);
    if (listMatch) {
      const items: string[] = [];
      const ordered = listMatch.ordered;
      while (index < lines.length) {
        const currentList = getListMatch(lines[index]);
        if (!currentList || currentList.ordered !== ordered) {
          break;
        }
        items.push(currentList.text.trim());
        index += 1;
      }
      blocks.push({ type: "list", ordered, items });
      continue;
    }

    const paragraphLines: string[] = [];
    while (index < lines.length) {
      const currentLine = lines[index];
      if (!currentLine.trim()) {
        break;
      }
      if (
        paragraphLines.length > 0 &&
        (getFenceMatch(currentLine) || getHeadingMatch(currentLine) || getBlockquoteMatch(currentLine) || getListMatch(currentLine))
      ) {
        break;
      }
      paragraphLines.push(currentLine);
      index += 1;
    }
    blocks.push({ type: "paragraph", text: paragraphLines.join("\n").trim() });
  }

  return blocks;
}

function MarkdownContent({ content }: { content: string }) {
  const blocks = parseMarkdownBlocks(content);
  return (
    <div className="space-y-3 break-words text-stone-800">
      {blocks.map((block, index) => {
        if (block.type === "code") {
          return (
            <pre
              key={index}
              className="overflow-x-auto whitespace-pre rounded-lg bg-stone-950 px-3 py-2 text-xs leading-5 text-stone-50"
            >
              <code className={block.language ? `language-${block.language}` : undefined}>{block.text}</code>
            </pre>
          );
        }

        if (block.type === "heading") {
          const Heading = (`h${Math.min(block.level + 2, 6)}` as "h3" | "h4" | "h5" | "h6");
          return (
            <Heading key={index} className={markdownHeadingClassName(block.level)}>
              <InlineMarkdown text={block.text} />
            </Heading>
          );
        }

        if (block.type === "blockquote") {
          return (
            <blockquote key={index} className="whitespace-pre-wrap border-l-4 border-rose-200 pl-3 text-stone-600">
              <InlineMarkdown text={block.text} />
            </blockquote>
          );
        }

        if (block.type === "list") {
          const List = block.ordered ? "ol" : "ul";
          return (
            <List key={index} className={cn("space-y-1 pl-5", block.ordered ? "list-decimal" : "list-disc")}>
              {block.items.map((item, lineIndex) => (
                <li key={lineIndex}>
                  <InlineMarkdown text={item} />
                </li>
              ))}
            </List>
          );
        }

        return (
          <p key={index} className="whitespace-pre-wrap leading-6">
            <InlineMarkdown text={block.text} />
          </p>
        );
      })}
    </div>
  );
}

function SidebarMetric({
  label,
  value,
  details = [],
  prominent = false,
  className,
}: {
  label: string;
  value: string | number;
  details?: string[];
  prominent?: boolean;
  className?: string;
}) {
  const visibleDetails = details.filter(Boolean);

  return (
    <div className={cn("rounded-lg bg-gradient-to-br from-white/82 to-rose-50/82 p-2.5", className)}>
      {prominent && visibleDetails.length > 0 ? (
        <div className="grid grid-cols-[minmax(64px,auto)_minmax(0,1fr)] items-center gap-3">
          <div className="min-w-0">
            <div className="text-sm font-medium text-stone-500">{label}</div>
            <div className="mt-0.5 truncate text-3xl font-bold tracking-tight text-stone-950">{value}</div>
          </div>
          <div className="min-w-0 space-y-1 text-right">
            {visibleDetails.map((detail) => (
              <div key={detail} title={detail} className="truncate text-xs leading-4 text-stone-400">
                {detail}
              </div>
            ))}
          </div>
        </div>
      ) : (
        <>
          <div className={cn("font-medium text-stone-500", prominent ? "text-sm" : "text-[11px]")}>{label}</div>
          <div
            className={cn(
              "mt-1 truncate font-bold tracking-tight text-stone-950",
              prominent ? "text-3xl" : "text-lg",
            )}
          >
            {value}
          </div>
          {visibleDetails.map((detail) => (
            <div key={detail} className="mt-1 text-xs text-stone-400">
              {detail}
            </div>
          ))}
        </>
      )}
    </div>
  );
}

export default function ChatPage() {
  const { isCheckingAuth, session } = useAuthGuard();

  if (isCheckingAuth || !session) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <LoaderCircle className="size-5 animate-spin text-stone-400" />
      </div>
    );
  }

  return <ChatPageContent session={session} />;
}
