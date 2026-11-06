"use client";
import { useState } from "react";
import { api, apiPage, VideoEvent } from "@/lib/api";
import { Button, Card, Empty, ErrorBox, Input } from "@/components/ui";

const PAGE_SIZE = 20;

export default function Events() {
  const [videoId, setVideoId] = useState("");
  const [name, setName] = useState("long-scene");
  const [ruleType, setRuleType] = useState("scene_duration_gt");
  const [value, setValue] = useState("5");
  const [severity, setSeverity] = useState("warning");
  const [events, setEvents] = useState<VideoEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");

  async function list(off = 0) {
    try {
      const p = await apiPage<VideoEvent>(`/api/v1/videos/${videoId}/events?limit=${PAGE_SIZE}&offset=${off}`);
      setEvents(p.items);
      setTotal(p.total);
      setOffset(off);
    } catch (e: any) { setError(String(e.message)); }
  }

  async function evaluate() {
    try {
      await api(`/api/v1/videos/${videoId}/events/evaluate`, {
        method: "POST", body: JSON.stringify([{ name, rule_type: ruleType, value, severity }]),
      });
      list(0);
    } catch (e: any) { setError(String(e.message)); }
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Event timeline</h1>
      <p className="text-sm text-gray-500">Events are only marked verified when backed by a high-confidence detection. Template captions alone never verify an event.</p>
      <Card className="flex flex-wrap gap-2">
        <Input placeholder="Video ID" value={videoId} onChange={(e) => setVideoId(e.target.value)} />
        <Input placeholder="Rule name" value={name} onChange={(e) => setName(e.target.value)} />
        <select value={ruleType} onChange={(e) => setRuleType(e.target.value)} className="rounded-lg border px-2 py-2 text-sm dark:bg-gray-800">
          <option value="scene_duration_gt">Scene longer than (seconds)</option>
          <option value="caption_keyword">Caption keyword</option>
          <option value="detection_label">Detection label</option>
        </select>
        <Input placeholder="Value" value={value} onChange={(e) => setValue(e.target.value)} />
        <select value={severity} onChange={(e) => setSeverity(e.target.value)} className="rounded-lg border px-2 py-2 text-sm dark:bg-gray-800">
          <option value="info">info</option><option value="warning">warning</option><option value="critical">critical</option>
        </select>
        <Button onClick={evaluate}>Evaluate rules</Button>
        <Button onClick={() => list(0)}>List events</Button>
      </Card>
      {error && <ErrorBox error={error} />}
      {events.length === 0 ? <Empty text="No events yet — run Evaluate rules, or list events for a video." /> : events.map((e) => (
        <Card key={e.id}><p className="text-sm"><b>{e.timestamp_seconds.toFixed(1)}s</b> — {e.title} [{e.severity}] verified={String(e.verified)}</p><p className="text-xs text-gray-500">{e.description}</p></Card>
      ))}
      {total > PAGE_SIZE && (
        <div className="flex items-center justify-between text-sm">
          <Button disabled={offset === 0} onClick={() => list(Math.max(0, offset - PAGE_SIZE))}>← Previous</Button>
          <span>Showing {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}</span>
          <Button disabled={offset + PAGE_SIZE >= total} onClick={() => list(offset + PAGE_SIZE)}>Next →</Button>
        </div>
      )}
    </div>
  );
}
