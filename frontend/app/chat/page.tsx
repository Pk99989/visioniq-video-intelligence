"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import { Button, Card, ErrorBox, Input } from "@/components/ui";

export default function Chat() {
  const [question, setQuestion] = useState("");
  const [videoId, setVideoId] = useState("");
  const [answer, setAnswer] = useState("");
  const [citations, setCitations] = useState<any[]>([]);
  const [tool, setTool] = useState("");
  const [error, setError] = useState("");

  async function ask() {
    setError("");
    try {
      const body: any = { question };
      if (videoId) body.video_id = parseInt(videoId);
      const r = await api<any>("/api/v1/chat", { method: "POST", body: JSON.stringify(body) });
      setAnswer(r.answer); setCitations(r.citations || []); setTool(r.tool || "");
    } catch (e: any) { setError(String(e.message)); }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">AI video chat</h1>
      <p className="text-sm text-gray-500">Answers are grounded in retrieved video evidence with timestamp citations. If no evidence is retrieved, the assistant says so instead of guessing.</p>
      <Card className="flex flex-wrap gap-2">
        <Input placeholder="Ask about your videos… (try: summarise, events, or a clip question)" value={question} onChange={(e) => setQuestion(e.target.value)} />
        <Input placeholder="Video ID (optional)" value={videoId} onChange={(e) => setVideoId(e.target.value)} />
        <Button onClick={ask}>Ask</Button>
      </Card>
      {error && <ErrorBox error={error} />}
      {answer && (
        <Card>
          <p className="text-xs text-gray-500">Tool: {tool}</p>
          <p className="whitespace-pre-wrap text-sm">{answer}</p>
          {citations.length > 0 && (
            <div className="mt-3 border-t pt-2">
              <p className="text-xs font-semibold">Citations</p>
              {citations.map((c: any, i: number) => (
                <p key={i} className="text-xs text-gray-600 dark:text-gray-400">
                  {c.timestamp_seconds?.toFixed(1)}s — {c.caption || c.text}
                </p>
              ))}
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
