"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Account, Dataset, DatasetDetail, PublisherError, publisherRequest } from "@/lib/publisher";

const field = "block w-full border border-slate-300 rounded-lg p-3 bg-white text-slate-900";
const button = "rounded-lg bg-blue-700 text-white px-4 py-2 disabled:opacity-50";
const panel = "bg-white border rounded-xl p-6 mb-6";
const scopes = ["datasets:read", "datasets:submit", "datasets:publish", "ingest:trigger", "sources:write", "uploads:write"];
type Member = { id: string; email: string; role: string };
type Integration = { id: string; name: string; scopes: string[]; revoked_at: string | null; expires_at: string | null };
type Invitation = { id: string; email: string; role: string; accepted_at: string | null; revoked_at: string | null };

export default function PublisherPage() {
  const [account, setAccount] = useState<Account | null>(null);
  const [ready, setReady] = useState(false);
  const [organisation, setOrganisation] = useState("");
  const [tab, setTab] = useState("datasets");
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [detail, setDetail] = useState<DatasetDetail | null>(null);
  const [members, setMembers] = useState<Member[]>([]);
  const [tokens, setTokens] = useState<Integration[]>([]);
  const [invitations, setInvitations] = useState<Invitation[]>([]);
  const [newToken, setNewToken] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [method, setMethod] = useState("file");
  const [format, setFormat] = useState("json");
  const [credentialKind, setCredentialKind] = useState("none");
  const [preview, setPreview] = useState<Record<string, unknown>[] | null>(null);
  const [reviewed, setReviewed] = useState(false);
  const [reauthentication, setReauthentication] = useState(false);
  const retryAction = useRef<(() => Promise<void>) | null>(null);
  const key = useRef<string | null>(null);
  const selected = account?.organisations.find(o => o.id === organisation);
  const writable = selected?.role !== "viewer";

  const loadAccount = useCallback(async () => {
    const result = await publisherRequest<Account>("/api/auth/me");
    setAccount(result);
    setOrganisation(current => result.organisations.some(o => o.id === current) ? current : result.organisations[0]?.id || "");
  }, []);
  const loadDatasets = useCallback(async () => {
    if (organisation) setDatasets(await publisherRequest<Dataset[]>(`/api/portal/datasets?organisation_id=${organisation}`));
  }, [organisation]);
  const loadManagement = useCallback(async () => {
    if (!organisation || selected?.role !== "owner") return;
    const [m, t, i] = await Promise.all([
      publisherRequest<Member[]>(`/api/portal/organisations/${organisation}/members`),
      publisherRequest<Integration[]>(`/api/portal/organisations/${organisation}/tokens`),
      publisherRequest<Invitation[]>(`/api/portal/organisations/${organisation}/invitations`),
    ]);
    setMembers(m); setTokens(t); setInvitations(i);
  }, [organisation, selected?.role]);
  const showError = useCallback((error: unknown) => {
    if (error instanceof PublisherError && error.status === 401 && !error.reauthenticate) {
      setAccount(null); setMessage("Your session expired. Sign in again to continue.");
    } else setMessage(error instanceof Error ? error.message : "Request failed. Please try again.");
  }, []);
  useEffect(() => { queueMicrotask(() => { loadAccount().catch(showError).finally(() => setReady(true)); }); }, [loadAccount, showError]);
  useEffect(() => {
    if (account?.verified && organisation) queueMicrotask(() => { loadDatasets().catch(showError); loadManagement().catch(showError); });
  }, [account?.verified, organisation, loadDatasets, loadManagement, showError]);
  useEffect(() => {
    if (!organisation || !account?.verified) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState !== "visible") return;
      loadDatasets().catch(showError);
      if (detail) publisherRequest<DatasetDetail>(`/api/portal/datasets/${detail.dataset_id}`).then(setDetail).catch(showError);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [organisation, account?.verified, detail, loadDatasets, showError]);

  async function run(action: () => Promise<void>) {
    setBusy(true); setMessage("");
    try { await action(); }
    catch (error) {
      if (error instanceof PublisherError && error.reauthenticate) { retryAction.current = action; setReauthentication(true); }
      else showError(error);
    } finally { setBusy(false); }
  }
  function connection(data: FormData) {
    const value = (name: string) => String(data.get(name) || "");
    const parameters = JSON.parse(value("parameters") || "{}");
    const column_mapping = JSON.parse(value("mapping") || "{}");
    return {
      url: value("url"), name: value("name"), schedule: value("schedule"), format: method === "api" ? "json" : format,
      records_path: value("records_path"), parameters, column_mapping,
      pagination: { mode: value("pagination") || "none", page_parameter: value("page_parameter") || "page", first_page: Number(value("first_page") || 1), max_pages: Number(value("max_pages") || 5) },
      ...(method === "api" && credentialKind !== "none" ? { credentials: { kind: credentialKind, secret: value("external_secret"), header_name: value("header_name") || "X-API-Key" } } : {}),
    };
  }
  async function addDataset(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const metadata = Object.fromEntries(["title", "description", "topic", "licence", "original_provider", "provenance"].map(name => [name, String(data.get(name) || "")]));
    await run(async () => {
      key.current ||= crypto.randomUUID();
      let body: FormData | string;
      if (method === "file") {
        body = new FormData(); body.set("metadata", JSON.stringify({ ...metadata, organisation_id: organisation }));
        body.set("file", data.get("file") as File);
      } else body = JSON.stringify({ ...metadata, organisation_id: organisation, access_method: method, connection: connection(data) });
      const result = await publisherRequest<{ dataset_id: string }>(method === "file" ? "/api/portal/datasets/upload" : "/api/portal/datasets", { method: "POST", headers: { "Idempotency-Key": key.current }, body });
      key.current = null; form.reset(); setCredentialKind("none"); setPreview(null);
      setMessage("Submission saved. Processing is queued; you can safely leave this page.");
      await loadDatasets(); setDetail(await publisherRequest<DatasetDetail>(`/api/portal/datasets/${result.dataset_id}`));
    });
  }
  async function testConnection(form: HTMLFormElement) {
    const data = new FormData(form);
    await run(async () => {
      const result = await publisherRequest<{ preview: Record<string, unknown>[]; message: string }>("/api/portal/connections/test", { method: "POST", body: JSON.stringify({ organisation_id: organisation, connection: connection(data) }) });
      setPreview(result.preview); setMessage(result.message);
    });
  }
  async function mutate(path: string, method = "POST", body?: object) {
    await publisherRequest(path, { method, ...(body ? { body: JSON.stringify(body) } : {}) });
    await loadDatasets(); await loadManagement();
    if (detail) setDetail(await publisherRequest<DatasetDetail>(`/api/portal/datasets/${detail.dataset_id}`));
  }
  if (!ready) return <main className="max-w-6xl mx-auto p-8">Loading your account…</main>;
  if (!account) return <main className="max-w-3xl mx-auto p-8"><h1 className="text-3xl font-bold mb-4">Publisher dashboard</h1><p>{message || "Sign in to submit datasets and manage your organisation."}</p><Link className="text-blue-700 underline" href="/account">Sign in or create an account</Link></main>;
  return <main className="max-w-6xl mx-auto px-5 py-10">
    <div className="flex flex-wrap justify-between gap-4 mb-6"><div><h1 className="text-3xl font-bold">Publisher dashboard</h1><p className="text-slate-600">{account.email}</p></div><button onClick={() => run(async () => { await publisherRequest("/api/auth/logout", { method: "POST" }); setAccount(null); })} className="underline">Sign out</button></div>
    {message && <p role="status" className="border rounded-xl p-4 mb-6 bg-blue-50">{message}</p>}
    {!account.verified ? <div className={panel}><h2 className="text-xl font-bold">Verify your email</h2><p>Open the verification email before creating an organisation or submitting datasets.</p><Link href="/account" className="underline text-blue-700">Resend verification email</Link></div> : <>
      {account.organisations.length > 0 && <label className="block mb-6">Submitting organisation<select value={organisation} className={field} onChange={e => { setOrganisation(e.target.value); setDetail(null); setNewToken(""); key.current = null; }}>{account.organisations.map(o => <option key={o.id} value={o.id}>{o.name} ({o.role})</option>)}</select></label>}
      <div className="flex flex-wrap gap-4 mb-6">{["datasets", "organisation", ...(selected?.role === "owner" ? ["integrations"] : [])].map(value => <button key={value} className={tab === value ? button : "px-4 py-2 border rounded-lg"} onClick={() => { setTab(value); setNewToken(""); }}>{value === "datasets" ? "Datasets" : value === "organisation" ? "Organisation" : "Integrations"}</button>)}</div>
      {(!organisation || tab === "organisation") && <section className={panel}>
        <h2 className="text-xl font-bold mb-3">Create a new organisation</h2><p className="mb-4 text-slate-600">If your organisation already exists, ask an owner to invite your verified email or ask the platform operator to approve membership. Entering its name does not grant access.</p>
        <form className="grid gap-3" onSubmit={event => { event.preventDefault(); const data = new FormData(event.currentTarget); run(async () => { const result = await publisherRequest<{ id: string }>("/api/portal/organisations", { method: "POST", body: JSON.stringify(Object.fromEntries(data)) }); await loadAccount(); setOrganisation(result.id); setTab("datasets"); }); }}>
          <label>Organisation name<input name="name" required minLength={2} maxLength={200} className={field} /></label>
          <label>Description<textarea name="description" maxLength={2000} className={field} /></label>
          <label>Website<input name="website" type="url" maxLength={500} className={field} /></label>
          <button disabled={busy} className={button}>Create organisation</button>
        </form>
      </section>}
      {organisation && tab === "datasets" && <>
        {writable && <section className={panel}>
          <h2 className="text-2xl font-bold mb-4">Add dataset</h2>
          <div className="flex flex-wrap gap-3 mb-5">{[["file", "Upload a file"], ["api", "Connect an API"], ["url", "Import from a download URL"]].map(([value, label]) => <button key={value} className={method === value ? button : "border rounded-lg px-4 py-2"} onClick={() => { setMethod(value); setPreview(null); key.current = null; }}>{label}</button>)}</div>
          <form className="grid gap-4" onSubmit={addDataset} onChange={() => { key.current = null; }}>
            <div className="grid md:grid-cols-2 gap-4">
              <label>Dataset title<input name="title" className={field} required minLength={3} maxLength={200} /></label>
              <label>Topic<select name="topic" className={field}>{["general", "health", "economics", "agric", "education"].map(value => <option key={value} value={value}>{value}</option>)}</select></label>
              <label className="md:col-span-2">Description<textarea name="description" className={field} required minLength={10} maxLength={5000} /></label>
              <label>Licence or reuse conditions<input name="licence" className={field} placeholder="e.g. CC BY 4.0, with a licence link" required minLength={3} maxLength={2000} /></label>
              <label>Original data provider<input name="original_provider" className={field} required minLength={2} maxLength={200} /></label>
              <label className="md:col-span-2">Provenance<textarea name="provenance" className={field} placeholder="Where the data came from, dates and relevant source links" required minLength={3} maxLength={2000} /></label>
            </div>
            {method === "file" ? <label>File (CSV, XLSX, JSON or PDF; maximum 50 MB)<input name="file" className={field} type="file" required accept=".csv,.xlsx,.json,.pdf" /><span className="text-sm text-slate-600">PDF tables are extracted where possible and always require review. Scanned documents need OCR outside this workflow.</span></label> : <>
              <label>{method === "api" ? "API endpoint" : "Public download URL"}<input name="url" className={field} type="url" required placeholder="https://…" /></label>
              {method === "api" && <label>Connection name<input name="name" className={field} required maxLength={200} /></label>}
              {method === "url" && <label>Downloaded file format<select className={field} value={format} onChange={e => setFormat(e.target.value)}>{["csv", "xlsx", "json", "pdf"].map(v => <option key={v}>{v}</option>)}</select></label>}
              <label>Update schedule<select name="schedule" className={field}>{["manual", "daily", "weekly"].map(v => <option key={v}>{v}</option>)}</select></label>
              {method === "api" && <>
                <p className="text-sm text-slate-600">Supported: GET requests returning an array of flat JSON records, optionally inside a named property. Cursor pagination, POST APIs and nested table cells need an operator-installed connector.</p>
                <label>External API authentication<select className={field} value={credentialKind} onChange={e => setCredentialKind(e.target.value)}><option value="none">No credentials</option><option value="bearer">Bearer token</option><option value="header">API key in a header</option></select></label>
                {credentialKind !== "none" && <><p className="text-sm">These credentials belong to the external data provider. They are encrypted on the server; they are separate from platform integration tokens. HTTPS is required.</p><label>External credential<input name="external_secret" className={field} type="password" autoComplete="off" required minLength={8} maxLength={4096} /></label>{credentialKind === "header" && <label>Header name<input name="header_name" className={field} defaultValue="X-API-Key" /></label>}</>}
              </>}
              <details className="border rounded-lg p-4"><summary className="cursor-pointer">Advanced settings</summary><div className="grid gap-3 mt-4">
                <label>JSON records property path<input name="records_path" className={field} placeholder="e.g. data.records; leave empty for a root array" /></label>
                <label>Request parameters (JSON object, no credentials)<textarea name="parameters" className={field} defaultValue="{}" /></label>
                <label>Column mappings (JSON object: original name → new name)<textarea name="mapping" className={field} defaultValue="{}" /></label>
                {method === "api" && <><label>Pagination<select name="pagination" className={field}><option value="none">None</option><option value="page">Page number</option></select></label><label>Page parameter<input name="page_parameter" className={field} defaultValue="page" /></label><label>First page<input name="first_page" className={field} type="number" min={0} max={1000} defaultValue={1} /></label><label>Maximum pages per run<input name="max_pages" className={field} type="number" min={1} max={10} defaultValue={5} /></label><p className="text-sm">A non-empty final page is flagged for review because the result may be incomplete.</p></>}
              </div></details>
              {method === "api" && <button type="button" className="border rounded-lg p-3" disabled={busy} onClick={e => { const form = e.currentTarget.closest("form"); if (form) testConnection(form); }}>Test connection</button>}
            </>}
            {preview && <div className="overflow-auto"><p>Preview of up to five records; sensitive fields are redacted.</p><pre className="bg-slate-50 p-3 text-sm">{JSON.stringify(preview, null, 2)}</pre></div>}
            <button className={button} disabled={busy}>{busy ? "Please wait…" : "Submit for processing"}</button>
          </form>
        </section>}
        <section className={panel}><h2 className="text-xl font-bold mb-4">Your datasets</h2>{datasets.length === 0 && <p>No submissions yet.</p>}{datasets.map(d => <button key={d.dataset_id} className="block text-left w-full border-b py-4" onClick={() => run(async () => { setDetail(await publisherRequest<DatasetDetail>(`/api/portal/datasets/${d.dataset_id}`)); setReviewed(false); })}><strong>{d.display_name}</strong><span className="block text-sm text-slate-600">Processing: {d.processing_state} · Catalog: {d.publication_state} · {d.row_count || 0} rows</span></button>)}</section>
        {detail && <section className={panel}><h2 className="text-xl font-bold mb-3">{detail.display_name}</h2><p>{detail.description}</p><p className="my-3">Processing: {detail.processing_state} · Catalog: {detail.publication_state}</p><div className="flex flex-wrap gap-4">{detail.files.map(f => <a className="text-blue-700 underline" key={f.id} href={`/api/portal/datasets/${detail.dataset_id}/files/${f.id}`}>{f.kind} {f.format.toUpperCase()} ({Math.ceil(f.size_bytes / 1024)} KB)</a>)}</div><pre className="overflow-auto bg-slate-50 p-4 my-4 text-sm">{JSON.stringify(detail.preview, null, 2)}</pre>
          {detail.jobs.map(j => <div key={j.id} className="border rounded-lg p-3 my-3"><strong>{j.action}: {j.status}</strong><p>{j.phase} · attempt {j.attempts}</p><progress className="w-full" max={100} value={j.progress} aria-label="Job progress" />{j.error_code && <p>{j.error_code === "publication_failed" ? "Catalog publication failed. Retry publication without re-ingesting the data." : j.error_code === "authorisation_revoked" ? "The submitting account or integration no longer has permission." : "Processing failed. Check the file format and source availability before retrying."}</p>}{writable && j.status === "failed" && <button disabled={busy} className={button} onClick={() => run(() => mutate(`/api/portal/jobs/${j.id}/retry`))}>Retry {j.action}</button>}<button className="ml-3 underline" onClick={() => run(async () => { const result = await publisherRequest<{ history: object[] }>(`/api/portal/jobs/${j.id}`); setMessage(JSON.stringify(result.history)); })}>Attempt history</button></div>)}
          {writable && <div className="flex flex-wrap gap-3 mt-4"><button disabled={busy} className="border rounded-lg px-4 py-2" onClick={() => run(() => mutate(`/api/portal/datasets/${detail.dataset_id}/ingest`))}>Process again</button>{["completed", "needs_review"].includes(detail.processing_state) && <><label className="flex items-center gap-2"><input type="checkbox" checked={reviewed} onChange={e => setReviewed(e.target.checked)} />I reviewed the original and extracted results</label><button className={button} disabled={busy || (detail.processing_state === "needs_review" && !reviewed)} onClick={() => run(() => mutate(`/api/portal/datasets/${detail.dataset_id}/publish`, "POST", { reviewed }))}>{detail.publication_state === "published" ? "Update catalog" : "Publish to catalog"}</button></>}</div>}
          {writable && <details className="mt-5"><summary>Edit metadata</summary><form className="grid gap-3 mt-3" key={detail.dataset_id} onSubmit={event => { event.preventDefault(); const data = Object.fromEntries(new FormData(event.currentTarget)); run(() => mutate(`/api/portal/datasets/${detail.dataset_id}`, "PATCH", data)); }}>{[["title", "Title", detail.display_name], ["description", "Description", detail.description], ["licence", "Licence", detail.licence], ["original_provider", "Original provider", detail.original_provider], ["provenance", "Provenance", detail.provenance]].map(([name, label, value]) => <label key={name}>{label}<textarea name={name} className={field} required defaultValue={value} /></label>)}<button disabled={busy} className={button}>Save metadata</button></form></details>}
        </section>}
      </>}
      {organisation && tab === "organisation" && selected?.role === "owner" && <section className={panel}><h2 className="text-xl font-bold mb-4">Members and invitations</h2>{members.map(m => <div className="flex flex-wrap gap-3 items-center py-3 border-b" key={m.id}><span>{m.email}</span><select aria-label={`Role for ${m.email}`} value={m.role} onChange={e => run(() => mutate(`/api/portal/organisations/${organisation}/members/${m.id}`, "PATCH", { role: e.target.value }))}>{["viewer", "editor", "owner"].map(v => <option key={v}>{v}</option>)}</select><button className="underline" disabled={busy} onClick={() => run(() => mutate(`/api/portal/organisations/${organisation}/members/${m.id}`, "DELETE"))}>Remove</button></div>)}<form className="grid gap-3 mt-4" onSubmit={event => { event.preventDefault(); const body = Object.fromEntries(new FormData(event.currentTarget)); run(async () => { await mutate(`/api/portal/organisations/${organisation}/invitations`, "POST", body); setMessage("Invitation email queued."); }); }}><label>Invite email<input name="email" required type="email" className={field} /></label><label>Role<select name="role" className={field}><option>editor</option><option>viewer</option><option>owner</option></select></label><button className={button} disabled={busy}>Send invitation</button></form>{invitations.map(i => <div className="mt-3" key={i.id}>{i.email} · {i.role} · {i.accepted_at ? "accepted" : i.revoked_at ? "revoked" : "pending"}{!i.accepted_at && !i.revoked_at && <button className="ml-3 underline" disabled={busy} onClick={() => run(() => mutate(`/api/portal/organisations/${organisation}/invitations/${i.id}`, "DELETE"))}>Revoke</button>}</div>)}</section>}
      {organisation && tab === "integrations" && selected?.role === "owner" && <section className={panel}><h2 className="text-xl font-bold mb-3">Automated integrations</h2><p className="mb-4">Use scoped, expiring platform tokens for automated clients. Normal dashboard submissions use your signed-in session.</p><form className="grid gap-3" onSubmit={event => { event.preventDefault(); const data = new FormData(event.currentTarget); run(async () => { const result = await publisherRequest<{ token: string }>(`/api/portal/organisations/${organisation}/tokens`, { method: "POST", body: JSON.stringify({ name: data.get("name"), lifetime_days: Number(data.get("days")), scopes: data.getAll("scopes") }) }); setNewToken(result.token); await loadManagement(); }); }}><label>Integration name<input name="name" required minLength={2} maxLength={100} className={field} /></label><label>Expires in days<input name="days" type="number" required min={1} max={365} defaultValue={90} className={field} /></label><fieldset><legend>Permissions</legend>{scopes.map(scope => <label className="block" key={scope}><input type="checkbox" name="scopes" value={scope} /> {scope}</label>)}</fieldset><button className={button} disabled={busy}>Create integration token</button></form>{newToken && <div className="my-4 border p-4"><p>Copy this token now; it is shown once. Store it securely.</p><code className="break-all">{newToken}</code><button className="block underline" onClick={() => setNewToken("")}>Dismiss token</button></div>}{tokens.map(t => <div className="border-t py-3" key={t.id}><strong>{t.name}</strong><p>{t.scopes.join(", ")} · {t.revoked_at ? "revoked" : `expires ${t.expires_at || "when revoked (legacy)"}`}</p>{!t.revoked_at && <button disabled={busy} className="underline" onClick={() => run(() => mutate(`/api/portal/organisations/${organisation}/tokens/${t.id}`, "DELETE"))}>Revoke token</button>}</div>)}</section>}
    </>}
    {reauthentication && <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-5"><form className="bg-white rounded-xl p-6 max-w-md w-full grid gap-4" onSubmit={event => { event.preventDefault(); const password = new FormData(event.currentTarget).get("password"); run(async () => { await publisherRequest("/api/auth/reauthenticate", { method: "POST", body: JSON.stringify({ password }) }); setReauthentication(false); const action = retryAction.current; retryAction.current = null; if (action) await action(); }); }}><h2 className="text-xl font-bold">Confirm your password</h2><p>This action needs a recent sign-in.</p><label>Password<input name="password" type="password" required autoComplete="current-password" className={field} /></label><button disabled={busy} className={button}>Confirm and continue</button><button type="button" onClick={() => { setReauthentication(false); retryAction.current = null; }}>Cancel</button></form></div>}
  </main>;
}
