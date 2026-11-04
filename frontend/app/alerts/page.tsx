"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import { Button, Card, ErrorBox, Input } from "@/components/ui";

export default function Alerts() {
  const [videoId, setVideoId] = useState("");
  const [alerts, setAlerts] = useState<any[]>([]);
  const [error, setError] = useState("");
  async function list() {
    try { setAlerts(await api(`/api/v1/videos/${videoId}/alerts`)); }
    catch (e: any) { setError(String(e.message)); }
  }
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Alerts dashboard</h1>
      <Card className="flex gap-2">
        <Input placeholder="Video ID" value={videoId} onChange={(e) => setVideoId(e.target.value)} />
        <Button onClick={list}>Load alerts</Button>
      </Card>
      {error && <ErrorBox error={error} />}
      {alerts.map((a) => (
        <Card key={a.id} className="flex items-center justify-between">
          <p className="text-sm">{a.message} [{a.severity}] {a.acknowledged ? "· acknowledged" : ""}</p>
          {!a.acknowledged && <Button onClick={async () => { await api(`/api/v1/videos/${videoId}/alerts/${a.id}/acknowledge`, { method: "POST" }); list(); }}>Acknowledge</Button>}
        </Card>
      ))}
    </div>
  );
}
