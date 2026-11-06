"use client";
import { useEffect, useState } from "react";
import { api, ChatMessage, Conversation } from "@/lib/api";
import { Button, Card, Empty, ErrorBox, Input, SkeletonCard } from "@/components/ui";

export default function Chat() {
  const [question, setQuestion] = useState("");
  const [videoId, setVideoId] = useState("");
  const [conversations, setConversations] = useState<Conversation[] | null>(null);
  const [conversationId, setConversationId] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [tool, setTool] = useState("");
  const [error, setError] = useState("");
  const [asking, setAsking] = useState(false);

  async function loadConversations() {
    try {
      setConversations(await api<Conversation[]>("/api/v1/conversations"));
    } catch { /* sidebar is optional; the chat still works */ }
  }

  useEffect(() => { loadConversations(); }, []);

  async function openConversation(id: number) {
    setError("");
    try {
      const conv = await api<{ messages: ChatMessage[] }>(`/api/v1/conversations/${id}`);
      setConversationId(id);
      setMessages(conv.messages);
      setTool("");
    } catch (e: any) { setError(String(e.message)); }
  }

  function newChat() {
    setConversationId(null);
    setMessages([]);
    setTool("");
  }

  async function ask() {
    if (!question.trim() || asking) return;
    setError("");
    setAsking(true);
    const q = question;
    setQuestion("");
    setMessages((m) => [...m, { role: "user", content: q }]);
    try {
      const body: any = { question: q };
      if (videoId) body.video_id = parseInt(videoId);
      if (conversationId) body.conversation_id = conversationId;
      const r = await api<any>("/api/v1/chat", { method: "POST", body: JSON.stringify(body) });
      setConversationId(r.conversation_id);
      setTool(r.tool || "");
      setMessages((m) => [...m, { role: "assistant", content: r.answer }]);
      loadConversations();
    } catch (e: any) {
      setError(String(e.message));
      setMessages((m) => m.slice(0, -1));
      setQuestion(q);
    } finally {
      setAsking(false);
    }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">AI video chat</h1>
      <p className="text-sm text-gray-500">Answers are grounded in retrieved video evidence with timestamp citations. If no evidence is retrieved, the assistant says so instead of guessing. Follow-up questions use the conversation above them.</p>
      <div className="grid gap-4 md:grid-cols-[220px_1fr]">
        <Card>
          <div className="mb-2 flex items-center justify-between">
            <h2 className="font-semibold">Conversations</h2>
            <Button onClick={newChat} ariaLabel="Start a new chat">+ New</Button>
          </div>
          {conversations === null ? <SkeletonCard lines={3} /> : conversations.length === 0 ? (
            <Empty text="No conversations yet." />
          ) : conversations.map((c) => (
            <button key={c.id} onClick={() => openConversation(c.id)}
              className={`block w-full truncate rounded px-2 py-1 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-800 ${c.id === conversationId ? "bg-indigo-50 font-semibold dark:bg-indigo-950" : ""}`}>
              {c.title || `Conversation ${c.id}`}
            </button>
          ))}
        </Card>
        <div className="space-y-4">
          <Card className="flex flex-wrap gap-2">
            <Input placeholder="Ask about your videos… (try: summarise, events, or a clip question)" value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") ask(); }} />
            <Input placeholder="Video ID (optional)" value={videoId} onChange={(e) => setVideoId(e.target.value)} />
            <Button onClick={ask} disabled={asking}>{asking ? "Asking…" : "Ask"}</Button>
          </Card>
          {error && <ErrorBox error={error} />}
          {messages.length === 0 ? (
            <Empty text="Ask a question, or open a conversation on the left to continue it." />
          ) : (
            <Card>
              {tool && <p className="text-xs text-gray-500">Tool: {tool}</p>}
              <div className="space-y-3">
                {messages.map((m, i) => (
                  <div key={i} className={m.role === "user" ? "text-right" : ""}>
                    <p className={`inline-block max-w-full whitespace-pre-wrap rounded-lg px-3 py-2 text-left text-sm ${m.role === "user" ? "bg-indigo-600 text-white" : "bg-gray-100 dark:bg-gray-800"}`}>
                      {m.content}
                    </p>
                  </div>
                ))}
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
