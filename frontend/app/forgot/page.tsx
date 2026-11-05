"use client";
import { useState } from "react";
import { API } from "@/lib/api";
import { Button, Card, ErrorBox, Input } from "@/components/ui";

export default function Forgot() {
  const [email, setEmail] = useState("");
  const [token, setToken] = useState("");
  const [password, setPassword] = useState("");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  async function requestToken() {
    setError(""); setMsg("");
    const r = await fetch(`${API}/api/v1/auth/password-reset-request`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    });
    const d = await r.json().catch(() => ({}));
    if (d.reset_token) { setToken(d.reset_token); setMsg("Reset token created (valid 1 hour). Paste it below with a new password."); }
    else setMsg(d.detail || "If that email is registered, a reset token was created.");
  }
  async function reset() {
    setError(""); setMsg("");
    if (password.length < 8) { setError("New password must be at least 8 characters."); return; }
    const r = await fetch(`${API}/api/v1/auth/password-reset`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token, new_password: password }),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) setError(String(d.detail || "Reset failed"));
    else setMsg(String(d.detail || "Password reset. Please sign in."));
  }
  return (
    <Card className="mx-auto max-w-md space-y-3">
      <h1 className="text-xl font-bold">Reset password</h1>
      {error && <ErrorBox error={error} />}
      {msg && <p className="text-sm text-green-700">{msg}</p>}
      <Input placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} />
      <Button onClick={requestToken}>Send reset token</Button>
      <Input placeholder="Reset token" value={token} onChange={(e) => setToken(e.target.value)} />
      <Input placeholder="New password (min 8 characters)" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
      <Button onClick={reset}>Reset password</Button>
      <p className="text-xs text-gray-500">VisionIQ has no email service, so the reset token is shown here for local testing. In production it would be emailed instead.</p>
    </Card>
  );
}
