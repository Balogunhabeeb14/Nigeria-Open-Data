"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { publisherRequest } from "@/lib/publisher";

export default function AccountPage() {
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [action, setAction] = useState({ purpose: "", token: "" });
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const fragment = new URLSearchParams(window.location.hash.slice(1));
    const purpose = fragment.get("action") || "";
    const token = fragment.get("token") || "";
    if (token && ["verify", "reset", "invite"].includes(purpose)) {
      window.history.replaceState(null, "", "/account");
      queueMicrotask(() => {
        setAction({ purpose, token });
        if (purpose === "reset") setMode("reset");
        if (purpose === "verify") {
          publisherRequest<{ message: string }>("/api/auth/verify", { method: "POST", body: JSON.stringify({ token }) })
            .then(result => setMessage(result.message)).catch(error => setMessage(error.message));
        }
      });
    }
  }, []);
  async function submit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setMessage("");
    try {
      const body = mode === "reset" ? { token: action.token, password }
        : ["recover", "resend-verification"].includes(mode) ? { email } : { email, password };
      const result = await publisherRequest<{ message?: string }>(`/api/auth/${mode}`, { method: "POST", body: JSON.stringify(body) });
      setPassword("");
      if (mode === "login") {
        if (action.purpose === "invite") {
          await publisherRequest("/api/portal/invitations/accept", { method: "POST", body: JSON.stringify({ token: action.token }) });
        }
        window.location.assign("/publisher");
      } else {
        setMessage(result.message || "Request completed.");
        if (mode === "reset") { setAction({ purpose: "", token: "" }); setMode("login"); }
      }
    } catch (error) { setMessage(error instanceof Error ? error.message : "Unable to complete this request."); }
    finally { setBusy(false); }
  }
  return <main className="max-w-lg mx-auto px-5 py-16">
    <h1 className="text-3xl font-bold mb-3">Publisher account</h1>
    <p className="text-slate-600 mb-6">Sign in to manage your organisation and submit datasets. Public datasets remain available to everyone.</p>
    {action.purpose === "invite" && <p className="mb-4">Sign in with the verified address that received this invitation. If you need to register or verify first, reopen the invitation afterwards.</p>}
    <div className="flex flex-wrap gap-3 mb-6">{[["login", "Sign in"], ["register", "Create account"], ["recover", "Forgot password"], ["resend-verification", "Resend verification"]].map(([value, label]) => <button key={value} onClick={() => { setMode(value); setMessage(""); }} className="text-blue-700 underline">{label}</button>)}</div>
    <form onSubmit={submit} className="grid gap-4">
      {mode !== "reset" && <label>Email<input className="block w-full border rounded-lg p-3" type="email" autoComplete="email" required value={email} onChange={e => setEmail(e.target.value)} /></label>}
      {!["recover", "resend-verification"].includes(mode) && <label>Password<input className="block w-full border rounded-lg p-3" type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} required minLength={mode === "login" ? 1 : 12} maxLength={128} value={password} onChange={e => setPassword(e.target.value)} /><span className="text-sm text-slate-500">New passwords must contain 12–128 characters.</span></label>}
      <button disabled={busy} className="bg-blue-700 text-white rounded-lg p-3 disabled:opacity-50">{busy ? "Please wait…" : mode === "login" ? "Sign in" : mode === "register" ? "Create account" : mode === "reset" ? "Set new password" : "Send email"}</button>
    </form>
    {message && <p role="status" className="my-5 border rounded-lg p-4">{message}</p>}
    <Link href="/publisher" className="block mt-6 text-blue-700 underline">Open publisher dashboard</Link>
  </main>;
}
