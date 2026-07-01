"use client";

import localforage from "localforage";

import type { ChatCompletionMessage, ChatRole } from "@/lib/api";
import type { ImageConversationOwner } from "@/store/image-conversations";

export type ChatMessageStatus = "sending" | "success" | "error";

export type StoredChatAttachment = {
  id: string;
  name: string;
  type: string;
  size: number;
  dataUrl?: string;
  text?: string;
};

export type StoredChatMessage = Omit<ChatCompletionMessage, "content"> & {
  id: string;
  createdAt: string;
  content: string;
  status?: ChatMessageStatus;
  error?: string;
  attachments?: StoredChatAttachment[];
};

export type ChatConversation = {
  id: string;
  ownerKey?: string;
  title: string;
  model: string;
  createdAt: string;
  updatedAt: string;
  messages: StoredChatMessage[];
};

export type ChatConversationsChangedDetail = {
  ownerKey: string;
};

const chatConversationStorage = localforage.createInstance({
  name: "chatgpt2api",
  storeName: "chat_conversations",
});

const CHAT_CONVERSATIONS_KEY = "items";
export const CHAT_CONVERSATIONS_CHANGED_EVENT = "chatgpt2api:chat-conversations-changed";
let chatConversationWriteQueue: Promise<void> = Promise.resolve();

function encodeStorageSegment(value: string) {
  return encodeURIComponent(value.trim());
}

function normalizeOwnerKey(ownerKey?: string | null) {
  return String(ownerKey || "").trim();
}

function getChatConversationsStorageKey(ownerKey?: string | null) {
  const normalizedOwnerKey = normalizeOwnerKey(ownerKey);
  return normalizedOwnerKey ? `${CHAT_CONVERSATIONS_KEY}:${normalizedOwnerKey}` : CHAT_CONVERSATIONS_KEY;
}

function emitChatConversationsChanged(ownerKey: string) {
  if (typeof window === "undefined") {
    return;
  }

  window.dispatchEvent(
    new CustomEvent<ChatConversationsChangedDetail>(CHAT_CONVERSATIONS_CHANGED_EVENT, {
      detail: { ownerKey },
    }),
  );
}

export function getChatConversationOwnerKey(owner: ImageConversationOwner | null | undefined) {
  const subject = String(owner?.subjectId || owner?.email || owner?.name || "").trim();
  if (!subject) {
    return "";
  }

  const role = String(owner?.role || "unknown").trim() || "unknown";
  return `${encodeStorageSegment(role)}:${encodeStorageSegment(subject)}`;
}

function normalizeRole(value: unknown): ChatRole {
  return value === "system" || value === "assistant" ? value : "user";
}

function normalizeMessage(message: StoredChatMessage & Record<string, unknown>): StoredChatMessage {
  const attachments: StoredChatAttachment[] | undefined = Array.isArray(message.attachments)
    ? message.attachments
        .map<StoredChatAttachment | null>((item) => {
          if (!item || typeof item !== "object") {
            return null;
          }
          const attachment = item as StoredChatAttachment & Record<string, unknown>;
          const normalized: StoredChatAttachment = {
            id: String(attachment.id || `${Date.now()}`),
            name: String(attachment.name || "attachment"),
            type: String(attachment.type || "application/octet-stream"),
            size: Number(attachment.size || 0),
            dataUrl: typeof attachment.dataUrl === "string" ? attachment.dataUrl : undefined,
            text: typeof attachment.text === "string" ? attachment.text : undefined,
          };
          return normalized;
        })
        .filter((item): item is StoredChatAttachment => item !== null)
    : undefined;
  return {
    id: String(message.id || `${Date.now()}`),
    role: normalizeRole(message.role),
    content: String(message.content || ""),
    createdAt: String(message.createdAt || new Date().toISOString()),
    status:
      message.status === "sending" || message.status === "success" || message.status === "error"
        ? message.status
        : "success",
    error: typeof message.error === "string" ? message.error : undefined,
    attachments,
  };
}

function normalizeConversation(
  conversation: ChatConversation & Record<string, unknown>,
  ownerKey = "",
): ChatConversation {
  const messages = Array.isArray(conversation.messages)
    ? conversation.messages.map((message) => normalizeMessage(message as StoredChatMessage & Record<string, unknown>))
    : [];
  const lastMessage = messages.length > 0 ? messages[messages.length - 1] : null;

  return {
    id: String(conversation.id || `${Date.now()}`),
    ownerKey: String(conversation.ownerKey || ownerKey || "").trim() || undefined,
    title: String(conversation.title || ""),
    model: String(conversation.model || "gpt-5.5"),
    createdAt: String(conversation.createdAt || lastMessage?.createdAt || new Date().toISOString()),
    updatedAt: String(conversation.updatedAt || lastMessage?.createdAt || new Date().toISOString()),
    messages,
  };
}

function sortChatConversations(conversations: ChatConversation[]) {
  return [...conversations].sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
}

function getTimestamp(value: string) {
  const time = new Date(value).getTime();
  return Number.isFinite(time) ? time : 0;
}

function pickLatestConversation(current: ChatConversation, next: ChatConversation) {
  return getTimestamp(next.updatedAt) >= getTimestamp(current.updatedAt) ? next : current;
}

function queueChatConversationWrite<T>(operation: () => Promise<T>): Promise<T> {
  const result = chatConversationWriteQueue.then(operation);
  chatConversationWriteQueue = result.then(
    () => undefined,
    () => undefined,
  );
  return result;
}

async function readStoredChatConversations(ownerKey = ""): Promise<ChatConversation[]> {
  const normalizedOwnerKey = normalizeOwnerKey(ownerKey);
  const items =
    (await chatConversationStorage.getItem<Array<ChatConversation & Record<string, unknown>>>(
      getChatConversationsStorageKey(normalizedOwnerKey),
    )) || [];
  return items
    .map((conversation) => normalizeConversation(conversation, normalizedOwnerKey))
    .filter((conversation) => !normalizedOwnerKey || conversation.ownerKey === normalizedOwnerKey);
}

export async function listChatConversations(ownerKey = ""): Promise<ChatConversation[]> {
  return sortChatConversations(await readStoredChatConversations(ownerKey));
}

export async function saveChatConversations(conversations: ChatConversation[], ownerKey = ""): Promise<void> {
  await queueChatConversationWrite(async () => {
    const normalizedOwnerKey = normalizeOwnerKey(ownerKey);
    const items = await readStoredChatConversations(normalizedOwnerKey);
    const conversationMap = new Map(items.map((item) => [item.id, item]));
    for (const conversation of conversations.map((item) => normalizeConversation(item, normalizedOwnerKey))) {
      const current = conversationMap.get(conversation.id);
      conversationMap.set(conversation.id, current ? pickLatestConversation(current, conversation) : conversation);
    }
    await chatConversationStorage.setItem(
      getChatConversationsStorageKey(normalizedOwnerKey),
      sortChatConversations([...conversationMap.values()]),
    );
    emitChatConversationsChanged(normalizedOwnerKey);
  });
}

export async function saveChatConversation(conversation: ChatConversation, ownerKey = ""): Promise<void> {
  await queueChatConversationWrite(async () => {
    const normalizedOwnerKey = normalizeOwnerKey(ownerKey);
    const items = await readStoredChatConversations(normalizedOwnerKey);
    const nextConversation = normalizeConversation(conversation, normalizedOwnerKey);
    const current = items.find((item) => item.id === nextConversation.id);
    const persistedConversation = current ? pickLatestConversation(current, nextConversation) : nextConversation;
    const nextItems = sortChatConversations([
      persistedConversation,
      ...items.filter((item) => item.id !== persistedConversation.id),
    ]);
    await chatConversationStorage.setItem(getChatConversationsStorageKey(normalizedOwnerKey), nextItems);
    emitChatConversationsChanged(normalizedOwnerKey);
  });
}

export async function deleteChatConversation(id: string, ownerKey = ""): Promise<void> {
  await queueChatConversationWrite(async () => {
    const normalizedOwnerKey = normalizeOwnerKey(ownerKey);
    const items = await readStoredChatConversations(normalizedOwnerKey);
    await chatConversationStorage.setItem(
      getChatConversationsStorageKey(normalizedOwnerKey),
      items.filter((item) => item.id !== id),
    );
    emitChatConversationsChanged(normalizedOwnerKey);
  });
}

export async function clearChatConversations(ownerKey = ""): Promise<void> {
  await queueChatConversationWrite(async () => {
    const normalizedOwnerKey = normalizeOwnerKey(ownerKey);
    await chatConversationStorage.removeItem(getChatConversationsStorageKey(normalizedOwnerKey));
    emitChatConversationsChanged(normalizedOwnerKey);
  });
}
