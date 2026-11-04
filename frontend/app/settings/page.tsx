"use client";
import { useEffect, useState } from "react";
import { API, api } from "@/lib/api";
import { Card, ErrorBox } from "@/components/ui";

export default function Settings() {
  const [me, setMe] = useState<any>(null);
  const [error, setError] = useState("");
  useEffect(() => { api("/api/v1/auth/me").then(setMe).catch((e) => setError(String(e.message))); }, []);
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Settings</h1>
      {error && <ErrorBox error={error} />}
      <Card>
        <p className="text-sm">API URL: <b>{API}</b></p>
        {me && <p className="text-sm">Signed in as: <b>{me.email}</b> (role: {me.role})</p>}
        <p className="text-sm text-gray-500">Theme: dark by default in this release (layout uses the dark class). Server-side settings — model provider, frame rate, upload limits — are environment variables on the backend; see .env.example. No secrets are shown here.</p>
        <p className="text-sm text-gray-500">Sign out: clear the VisionIQ token from your browser storage (localStorage key: visioniq_token).</p>
      </Card>
    </div>
  );
}
