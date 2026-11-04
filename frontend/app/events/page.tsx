"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import { Button, Card, ErrorBox, Input } from "@/components/ui";

export default function Events() {
  const [videoId, setVideoId] = useState("");
  const [name, setName] = useState("long-scene");
  const [ruleType, setRuleType] = useState("scene_duration_gt");
  const [value, setValue] = useState("5");
  const [severity, setSeverity] = useState("warning");
  const [events, setEvents] = useState<any[]>([]);
  const [error, setError] = useState("");

  async function evaluate() {
    try {
      await api(`/api/v1/videos/${videoId}/events/evaluate`, {
        method: "POST", body: JSON.stringify([{ name, rule_type: ruleType, value, severity }]),
      });
      setEvents(await api(`/api/v1/videos/${videoId}/events`));
    } catch (e: any) { setError(String(e.message)); }
  }
  async function list() {
    try { setEvents(await api(`/api/v1/videos/${videoId}/events`)); }
    catch (e: any) { setError(String(e.message)); }
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
        <Button onClick={list}>List events</Button>
      </Card>
      {error && <ErrorBox error={error} />}
      {events.map((e) => (
        <Card key={e.id}><p className="text-sm"><b>{e.timestamp_seconds.toFixed(1)}s</b> — {e.title} [{e.severity}] verified={String(e.verified)}</p><p className="text-xs text-gray-500">{e.description}</p></Card>
      ))}
    </div>
  );
}
