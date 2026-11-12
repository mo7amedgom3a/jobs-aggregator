import { useCallback, useEffect, useRef, useState } from "react";
import { TopNav } from "@/features/jobs/components/TopNav";
import {
  approveOutreach,
  draftOutreach,
  exportFoundersUrl,
  getOutreach,
  getYCCompanies,
  getYCFounders,
  getYCJobs,
  getYCStatus,
  sendOutreach,
  skipOutreach,
  startYCCrawl,
  stopYCCrawl,
  updateOutreach,
} from "./api";
import type {
  OutreachMessage,
  YCCompany,
  YCFounder,
  YCJobRow,
  YCStatusResponse,
} from "./types";
import "@/features/jobs/jobdork.css";

const BATCH_OPTIONS = [
  "Fall 2026",
  "Summer 2026",
  "Spring 2026",
  "Winter 2026",
  "Fall 2025",
  "Summer 2025",
  "Spring 2025",
  "Winter 2025",
];

const CHANNELS = ["email", "x", "linkedin"] as const;

type Tab = "founders" | "companies" | "jobs" | "outreach";

const PAGE_SIZE = 200;

function channelLabel(channel: string): string {
  if (channel === "x") return "X";
  if (channel === "linkedin") return "LinkedIn";
  return "Email";
}

function statusTone(status: string): string {
  if (status === "approved") return "green";
  if (status === "sent") return "cyan";
  if (status === "failed") return "amber";
  return "muted";
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

const SOCIAL_PATHS = {
  x: "M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z",
  linkedin:
    "M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433c-1.144 0-2.063-.926-2.063-2.065 0-1.138.92-2.063 2.063-2.063 1.14 0 2.064.925 2.064 2.063 0 1.139-.925 2.065-2.064 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z",
};

function SocialIcon({
  network,
  size = 14,
}: {
  network: "x" | "linkedin";
  size?: number;
}) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="currentColor"
      aria-hidden="true"
      style={{ display: "block" }}
    >
      <path d={SOCIAL_PATHS[network]} />
    </svg>
  );
}

function SocialLink({
  href,
  network,
  label,
  variant = "chip",
}: {
  href: string;
  network: "x" | "linkedin";
  label: string;
  variant?: "chip" | "button";
}) {
  return (
    <a
      className={variant === "button" ? "jd-btn ghost" : "jd-mini muted"}
      href={href}
      target="_blank"
      rel="noreferrer"
      title={label}
      aria-label={label}
      style={{
        display: "inline-flex",
        alignItems: "center",
        justifyContent: "center",
        padding: variant === "button" ? 8 : "6px 9px",
      }}
    >
      <SocialIcon network={network} />
    </a>
  );
}

function Avatar({
  src,
  name,
  size = 56,
  radius = 14,
}: {
  src?: string | null;
  name?: string | null;
  size?: number;
  radius?: number;
}) {
  const [failed, setFailed] = useState(false);
  const label = name || "?";
  const style = {
    width: size,
    height: size,
    borderRadius: radius,
    flex: `0 0 ${size}px`,
    objectFit: "cover" as const,
    background: "rgba(255,255,255,.06)",
    border: "1px solid var(--jd-border)",
  };
  if (!src || failed) {
    return (
      <div
        aria-label={label}
        style={{
          ...style,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: "Sora",
          fontWeight: 600,
          fontSize: Math.max(10, Math.round(size * 0.34)),
          color: "var(--jd-muted)",
        }}
      >
        {initials(label) || "?"}
      </div>
    );
  }
  return (
    <img
      src={src}
      alt={label}
      loading="lazy"
      style={style}
      onError={() => setFailed(true)}
    />
  );
}

export function YCFoundersPage() {
  const [tab, setTab] = useState<Tab>("founders");
  const [status, setStatus] = useState<YCStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [founders, setFounders] = useState<YCFounder[]>([]);
  const [foundersTotal, setFoundersTotal] = useState(0);
  const [companies, setCompanies] = useState<YCCompany[]>([]);
  const [companiesTotal, setCompaniesTotal] = useState(0);
  const [jobs, setJobs] = useState<YCJobRow[]>([]);
  const [jobsTotal, setJobsTotal] = useState(0);
  const [foundersLimit, setFoundersLimit] = useState(PAGE_SIZE);
  const [companiesLimit, setCompaniesLimit] = useState(PAGE_SIZE);
  const [jobsLimit, setJobsLimit] = useState(PAGE_SIZE);

  const [batch, setBatch] = useState("");
  const [queryInput, setQueryInput] = useState("");
  const [query, setQuery] = useState("");
  const [hasEmail, setHasEmail] = useState(false);
  const [hasX, setHasX] = useState(false);
  const [hasLinkedin, setHasLinkedin] = useState(false);
  const [onlyHiring, setOnlyHiring] = useState(false);

  const [selectedBatches, setSelectedBatches] =
    useState<string[]>(BATCH_OPTIONS);
  const [skipExisting, setSkipExisting] = useState(true);
  const [discoverEmails, setDiscoverEmails] = useState(true);
  const [starting, setStarting] = useState(false);

  const [draftChannels, setDraftChannels] = useState<string[]>([...CHANNELS]);
  const [draftLimit, setDraftLimit] = useState(500);
  const [drafting, setDrafting] = useState(false);

  const [queueStatus, setQueueStatus] = useState("draft");
  const [queueChannel, setQueueChannel] = useState("all");
  const [messages, setMessages] = useState<OutreachMessage[]>([]);
  const [messageEdits, setMessageEdits] = useState<
    Record<number, { subject: string; body: string }>
  >({});
  const [sending, setSending] = useState(false);
  const [sendChannel, setSendChannel] = useState("email");
  const [dryRun, setDryRun] = useState(true);

  const wasRunning = useRef(false);
  const running = Boolean(status?.state.running);

  const loadStatus = useCallback(async () => {
    try {
      const data = await getYCStatus();
      setStatus(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load YC status");
    }
  }, []);

  const loadFounders = useCallback(async () => {
    try {
      const data = await getYCFounders({
        batch: batch || undefined,
        q: query || undefined,
        hasEmail,
        hasX,
        hasLinkedin,
        limit: foundersLimit,
      });
      setFounders(data.founders);
      setFoundersTotal(data.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load founders");
    }
  }, [batch, query, hasEmail, hasX, hasLinkedin, foundersLimit]);

  const loadCompanies = useCallback(async () => {
    try {
      const data = await getYCCompanies({
        batch: batch || undefined,
        q: query || undefined,
        isHiring: onlyHiring,
        limit: companiesLimit,
      });
      setCompanies(data.companies);
      setCompaniesTotal(data.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load companies");
    }
  }, [batch, query, onlyHiring, companiesLimit]);

  const loadJobs = useCallback(async () => {
    try {
      const data = await getYCJobs({
        batch: batch || undefined,
        q: query || undefined,
        limit: jobsLimit,
      });
      setJobs(data.jobs);
      setJobsTotal(data.total);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load open roles",
      );
    }
  }, [batch, query, jobsLimit]);

  const loadQueue = useCallback(async () => {
    try {
      const data = await getOutreach({
        status: queueStatus,
        channel: queueChannel,
      });
      setMessages(data.messages);
      setMessageEdits(
        Object.fromEntries(
          data.messages.map((message) => [
            message.id,
            { subject: message.subject ?? "", body: message.body },
          ]),
        ),
      );
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load outreach queue",
      );
    }
  }, [queueStatus, queueChannel]);

  useEffect(() => {
    void loadStatus();
    const id = window.setInterval(() => {
      void loadStatus();
    }, 6000);
    return () => window.clearInterval(id);
  }, [loadStatus]);

  useEffect(() => {
    const isRunning = Boolean(status?.state.running);
    if (wasRunning.current && !isRunning) {
      void loadFounders();
      void loadCompanies();
      void loadJobs();
      void loadQueue();
    }
    wasRunning.current = isRunning;
  }, [status?.state.running, loadFounders, loadCompanies, loadJobs, loadQueue]);

  useEffect(() => {
    setFoundersLimit(PAGE_SIZE);
    setCompaniesLimit(PAGE_SIZE);
    setJobsLimit(PAGE_SIZE);
  }, [batch, query, hasEmail, hasX, hasLinkedin, onlyHiring]);

  useEffect(() => {
    if (tab === "founders") void loadFounders();
    if (tab === "companies") void loadCompanies();
    if (tab === "jobs") void loadJobs();
    if (tab === "outreach") void loadQueue();
  }, [tab, loadFounders, loadCompanies, loadJobs, loadQueue]);

  const toggleBatch = (value: string) => {
    setSelectedBatches((prev) =>
      prev.includes(value) ? prev.filter((b) => b !== value) : [...prev, value],
    );
  };

  const toggleDraftChannel = (value: string) => {
    setDraftChannels((prev) =>
      prev.includes(value) ? prev.filter((c) => c !== value) : [...prev, value],
    );
  };

  const handleCollect = async () => {
    if (running) return;
    const ok = confirm(
      `Crawl ${selectedBatches.length} YC batch(es)? This fetches every company and founder page ` +
        `and can take a while for 2025+2026 coverage. You can leave this page open and watch progress.`,
    );
    if (!ok) return;
    setStarting(true);
    setError(null);
    setNotice(null);
    try {
      const res = await startYCCrawl({
        batches: selectedBatches,
        skip_existing: skipExisting,
        discover_emails: discoverEmails,
      });
      setNotice(res.message);
      if (res.status === "error" || res.status === "already_running") {
        setNotice(null);
        setError(res.message);
      }
      void loadStatus();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to start the YC crawl",
      );
    } finally {
      setStarting(false);
    }
  };

  const handleStop = async () => {
    setError(null);
    try {
      const res = await stopYCCrawl();
      setNotice(res.message);
      void loadStatus();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to stop the YC crawl",
      );
    }
  };

  const handleDraft = async () => {
    if (draftChannels.length === 0) return;
    setDrafting(true);
    setError(null);
    setNotice(null);
    try {
      const res = await draftOutreach({
        channels: draftChannels,
        batch: batch || undefined,
        limit: draftLimit,
      });
      setNotice(
        `Drafted ${res.drafts_created} message(s) across ${Object.entries(
          res.by_channel,
        )
          .map(([channel, count]) => `${channelLabel(channel)}: ${count}`)
          .join(", ")} (${res.skipped} skipped without a usable contact).`,
      );
      setTab("outreach");
      void loadQueue();
      void loadStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to draft outreach");
    } finally {
      setDrafting(false);
    }
  };

  const saveMessage = async (message: OutreachMessage, silent = false) => {
    const edit = messageEdits[message.id];
    if (!edit) return;
    try {
      await updateOutreach(message.id, {
        subject: message.channel === "email" ? edit.subject : null,
        body: edit.body,
      });
      if (!silent) setNotice("Draft saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save draft");
    }
  };

  const handleApprove = async (message: OutreachMessage) => {
    await saveMessage(message, true);
    try {
      await approveOutreach(message.id);
      setMessages((prev) => prev.filter((item) => item.id !== message.id));
      setNotice("Approved. It will be sent when you run the channel send.");
      void loadStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to approve draft");
    }
  };

  const handleSkip = async (message: OutreachMessage) => {
    try {
      await skipOutreach(message.id);
      setMessages((prev) => prev.filter((item) => item.id !== message.id));
      void loadStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to skip draft");
    }
  };

  const handleSend = async () => {
    const ok = confirm(
      dryRun
        ? "Run a dry-run preview? Nothing will be sent."
        : `Send all APPROVED ${channelLabel(sendChannel)} messages now? This contacts real people.`,
    );
    if (!ok) return;
    setSending(true);
    setError(null);
    setNotice(null);
    try {
      const res = await sendOutreach({
        channel: sendChannel,
        dry_run: dryRun,
      });
      if (!dryRun) {
        setNotice(
          "Send started in the background. Approved messages will move to sent/failed — refresh the queue in a moment.",
        );
      } else {
        setNotice(
          `Dry run finished — attempted ${res.attempted}, sent ${res.sent}, failed ${res.failed}.` +
            (res.errors.length ? ` ${res.errors.slice(0, 2).join(" | ")}` : ""),
        );
      }
      void loadQueue();
      void loadStatus();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to send outreach");
    } finally {
      setSending(false);
    }
  };

  const stats = status?.stats;
  const state = status?.state;

  return (
    <div className="jobdork">
      <TopNav />
      {running && <div className="jd-progress" />}

      <div className="jd-aggregation-page">
        <div className="jd-page-header">
          <h1>YC founders — sourcing &amp; outreach</h1>
          <p>
            Crawls YC companies for 2025–2026, collects active founders with
            their X, LinkedIn and email contacts, then drafts outreach for open
            roles. Nothing is sent until you approve it. DM sending uses your
            saved LinkedIn/X browser sessions and is strictly rate-limited.
          </p>
        </div>

        {error && (
          <div
            className="jd-card"
            style={{ marginBottom: 20, border: "1px solid var(--jd-red)" }}
          >
            <p style={{ color: "var(--jd-red)", margin: 0 }}>{error}</p>
          </div>
        )}
        {notice && (
          <div className="jd-card" style={{ marginBottom: 20 }}>
            <p style={{ margin: 0, color: "var(--jd-muted)" }}>{notice}</p>
          </div>
        )}

        <div className="jd-grid-2 three-cols" style={{ marginBottom: 24 }}>
          <div className="jd-stat-card">
            <span className="label">Companies</span>
            <span className="value gradient">{stats?.companies ?? 0}</span>
            <span className="desc">Stored across the selected batches.</span>
          </div>
          <div className="jd-stat-card">
            <span className="label">Founders</span>
            <span className="value gradient">{stats?.founders ?? 0}</span>
            <span className="desc">
              {stats?.founders_with_email ?? 0} email ·{" "}
              {stats?.founders_with_x ?? 0} X ·{" "}
              {stats?.founders_with_linkedin ?? 0} LinkedIn
            </span>
          </div>
          <div className="jd-stat-card">
            <span className="label">Open roles</span>
            <span className="value gradient">{stats?.company_jobs ?? 0}</span>
            <span className="desc">
              Outreach:{" "}
              {Object.entries(stats?.outreach ?? {})
                .map(([key, count]) => `${key} ${count}`)
                .join(" · ") || "no drafts yet"}
            </span>
          </div>
        </div>

        <div className="jd-tabs" style={{ marginBottom: 20 }}>
          <button
            className={tab === "founders" ? "active" : ""}
            onClick={() => setTab("founders")}
          >
            Founders ({stats?.founders ?? foundersTotal})
          </button>
          <button
            className={tab === "companies" ? "active" : ""}
            onClick={() => setTab("companies")}
          >
            Companies ({stats?.companies ?? companiesTotal})
          </button>
          <button
            className={tab === "jobs" ? "active" : ""}
            onClick={() => setTab("jobs")}
          >
            Open roles ({stats?.company_jobs ?? jobsTotal})
          </button>
          <button
            className={tab === "outreach" ? "active" : ""}
            onClick={() => setTab("outreach")}
          >
            Outreach queue
          </button>
        </div>

        {tab === "outreach" ? (
          <div style={{ display: "grid", gap: 18 }}>
            <div className="jd-grid-2">
              <div className="jd-card">
                <h3
                  style={{
                    margin: "0 0 14px",
                    fontFamily: "Sora",
                    fontWeight: 600,
                  }}
                >
                  Generate drafts
                </h3>
                <div className="jd-form-group">
                  <label>Channels</label>
                  <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
                    {CHANNELS.map((channel) => (
                      <label
                        key={channel}
                        style={{
                          display: "flex",
                          gap: 6,
                          alignItems: "center",
                        }}
                      >
                        <input
                          type="checkbox"
                          checked={draftChannels.includes(channel)}
                          onChange={() => toggleDraftChannel(channel)}
                        />
                        {channelLabel(channel)}
                      </label>
                    ))}
                  </div>
                </div>
                <div className="jd-form-group">
                  <label>Limit (founders scanned)</label>
                  <input
                    className="jd-input"
                    type="number"
                    min={1}
                    max={5000}
                    value={draftLimit}
                    onChange={(e) =>
                      setDraftLimit(parseInt(e.target.value, 10) || 500)
                    }
                  />
                </div>
                <p
                  className="mono"
                  style={{ color: "var(--jd-muted-2)", fontSize: 11 }}
                >
                  Use the Batch filter to draft for one batch at a time.
                  Existing drafts are never duplicated.
                </p>
                <button
                  className="jd-btn primary"
                  style={{
                    width: "100%",
                    justifyContent: "center",
                    padding: 12,
                  }}
                  onClick={handleDraft}
                  disabled={drafting || draftChannels.length === 0}
                >
                  {drafting ? "Drafting…" : "Generate outreach drafts"}
                </button>
              </div>

              <div className="jd-card">
                <h3
                  style={{
                    margin: "0 0 14px",
                    fontFamily: "Sora",
                    fontWeight: 600,
                  }}
                >
                  Review queue
                </h3>
                <div className="jd-form-group">
                  <label>Status</label>
                  <select
                    className="jd-select"
                    value={queueStatus}
                    onChange={(e) => setQueueStatus(e.target.value)}
                  >
                    <option value="draft">Drafts</option>
                    <option value="approved">Approved</option>
                    <option value="sent">Sent</option>
                    <option value="failed">Failed</option>
                    <option value="skipped">Skipped</option>
                    <option value="all">All</option>
                  </select>
                </div>
                <div className="jd-form-group">
                  <label>Channel</label>
                  <select
                    className="jd-select"
                    value={queueChannel}
                    onChange={(e) => setQueueChannel(e.target.value)}
                  >
                    <option value="all">All channels</option>
                    {CHANNELS.map((channel) => (
                      <option key={channel} value={channel}>
                        {channelLabel(channel)}
                      </option>
                    ))}
                  </select>
                </div>
                <button
                  className="jd-btn ghost"
                  style={{ width: "100%" }}
                  onClick={() => void loadQueue()}
                >
                  Refresh queue
                </button>
              </div>
            </div>

            <div className="jd-card">
              <h3
                style={{
                  margin: "0 0 14px",
                  fontFamily: "Sora",
                  fontWeight: 600,
                }}
              >
                Send approved
              </h3>
              <div
                style={{
                  display: "flex",
                  gap: 12,
                  alignItems: "flex-end",
                  flexWrap: "wrap",
                }}
              >
                <div
                  className="jd-form-group"
                  style={{ minWidth: 180, marginBottom: 0 }}
                >
                  <label>Channel</label>
                  <select
                    className="jd-select"
                    value={sendChannel}
                    onChange={(e) => setSendChannel(e.target.value)}
                  >
                    {CHANNELS.map((channel) => (
                      <option key={channel} value={channel}>
                        {channelLabel(channel)}
                      </option>
                    ))}
                  </select>
                </div>
                <label
                  style={{
                    display: "flex",
                    gap: 8,
                    alignItems: "center",
                    paddingBottom: 10,
                  }}
                >
                  <input
                    type="checkbox"
                    checked={dryRun}
                    onChange={(e) => setDryRun(e.target.checked)}
                  />
                  Dry run (preview only)
                </label>
                <button
                  className="jd-btn primary"
                  onClick={handleSend}
                  disabled={sending}
                >
                  {sending
                    ? "Sending…"
                    : dryRun
                      ? "Preview send"
                      : "Send approved now"}
                </button>
              </div>
              <p
                className="mono"
                style={{
                  color: "var(--jd-muted-2)",
                  fontSize: 11,
                  marginTop: 10,
                }}
              >
                X: up to {20} DMs/run · LinkedIn: up to {10}/run with randomized
                delays. Email requires SMTP settings in backend/.env. Stop
                immediately if a platform shows a challenge.
              </p>
            </div>

            {messages.length === 0 ? (
              <div
                className="jd-card"
                style={{ textAlign: "center", padding: 40 }}
              >
                <p style={{ color: "var(--jd-muted)", margin: 0 }}>
                  No messages for this filter. Generate drafts above, then
                  approve the ones you want to send.
                </p>
              </div>
            ) : (
              <div style={{ display: "grid", gap: 14 }}>
                {messages.map((message) => {
                  const edit = messageEdits[message.id] ?? {
                    subject: message.subject ?? "",
                    body: message.body,
                  };
                  const editable = message.status === "draft";
                  return (
                    <article key={message.id} className="jd-card">
                      <div
                        style={{
                          display: "flex",
                          gap: 10,
                          alignItems: "center",
                          flexWrap: "wrap",
                          marginBottom: 10,
                        }}
                      >
                        <span className="jd-mini cyan">
                          {channelLabel(message.channel)}
                        </span>
                        <strong>{message.founder_name}</strong>
                        <span style={{ color: "var(--jd-muted)" }}>
                          {message.founder_title
                            ? `${message.founder_title} · `
                            : ""}
                          {message.company_name}{" "}
                          {message.company_batch
                            ? `(${message.company_batch})`
                            : ""}
                        </span>
                        <span className="spacer" style={{ flex: 1 }} />
                        <span
                          className={`jd-mini ${statusTone(message.status)}`}
                        >
                          {message.status}
                        </span>
                      </div>
                      <p
                        className="mono"
                        style={{
                          color: "var(--jd-muted-2)",
                          fontSize: 11,
                          margin: "0 0 10px",
                        }}
                      >
                        to {message.recipient}
                      </p>
                      {message.channel === "email" && (
                        <div className="jd-form-group">
                          <label>Subject</label>
                          <input
                            className="jd-input"
                            value={edit.subject}
                            disabled={!editable}
                            onChange={(e) =>
                              setMessageEdits((prev) => ({
                                ...prev,
                                [message.id]: {
                                  ...edit,
                                  subject: e.target.value,
                                },
                              }))
                            }
                          />
                        </div>
                      )}
                      <div className="jd-form-group">
                        <label>Message</label>
                        <textarea
                          className="jd-textarea"
                          rows={5}
                          value={edit.body}
                          disabled={!editable}
                          onChange={(e) =>
                            setMessageEdits((prev) => ({
                              ...prev,
                              [message.id]: { ...edit, body: e.target.value },
                            }))
                          }
                        />
                      </div>
                      {message.error && (
                        <p
                          style={{
                            color: "var(--jd-amber)",
                            margin: "0 0 10px",
                            fontSize: 12,
                          }}
                        >
                          {message.error}
                        </p>
                      )}
                      <div
                        style={{ display: "flex", gap: 8, flexWrap: "wrap" }}
                      >
                        {editable && (
                          <>
                            <button
                              className="jd-btn primary"
                              onClick={() => void handleApprove(message)}
                            >
                              Approve
                            </button>
                            <button
                              className="jd-btn ghost"
                              onClick={() => void saveMessage(message)}
                            >
                              Save edits
                            </button>
                            <button
                              className="jd-btn"
                              onClick={() => void handleSkip(message)}
                            >
                              Skip
                            </button>
                          </>
                        )}
                        {message.x_handle && (
                          <SocialLink
                            href={`https://x.com/${message.x_handle.replace(/^@/, "")}`}
                            network="x"
                            label="Open X profile"
                            variant="button"
                          />
                        )}
                        {message.linkedin_url && (
                          <SocialLink
                            href={message.linkedin_url}
                            network="linkedin"
                            label="Open LinkedIn profile"
                            variant="button"
                          />
                        )}
                      </div>
                    </article>
                  );
                })}
              </div>
            )}
          </div>
        ) : (
          <>
            <div className="jd-grid-2" style={{ marginBottom: 24 }}>
              <div className="jd-card">
                <h3
                  style={{
                    margin: "0 0 14px",
                    fontFamily: "Sora",
                    fontWeight: 600,
                  }}
                >
                  Collection
                </h3>
                <div className="jd-form-group">
                  <label>Batches</label>
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "1fr 1fr",
                      gap: 8,
                    }}
                  >
                    {BATCH_OPTIONS.map((value) => (
                      <label
                        key={value}
                        style={{
                          display: "flex",
                          gap: 8,
                          alignItems: "center",
                        }}
                      >
                        <input
                          type="checkbox"
                          checked={selectedBatches.includes(value)}
                          onChange={() => toggleBatch(value)}
                        />
                        {value}
                      </label>
                    ))}
                  </div>
                </div>
                <label
                  style={{
                    display: "flex",
                    gap: 8,
                    alignItems: "center",
                    marginBottom: 8,
                  }}
                >
                  <input
                    type="checkbox"
                    checked={skipExisting}
                    onChange={(e) => setSkipExisting(e.target.checked)}
                  />
                  Skip companies already stored (resume a big crawl)
                </label>
                <label
                  style={{
                    display: "flex",
                    gap: 8,
                    alignItems: "center",
                    marginBottom: 12,
                  }}
                >
                  <input
                    type="checkbox"
                    checked={discoverEmails}
                    onChange={(e) => setDiscoverEmails(e.target.checked)}
                  />
                  Discover emails on company websites
                </label>
                <button
                  className="jd-btn primary"
                  style={{
                    width: "100%",
                    justifyContent: "center",
                    padding: 12,
                  }}
                  onClick={handleCollect}
                  disabled={running || starting || selectedBatches.length === 0}
                >
                  {running
                    ? state?.stopping
                      ? "Stopping…"
                      : "Collection running…"
                    : starting
                      ? "Starting…"
                      : "Start YC collection"}
                </button>
                {running && (
                  <button
                    className="jd-btn"
                    style={{
                      width: "100%",
                      justifyContent: "center",
                      padding: 10,
                      marginTop: 8,
                      borderColor: "var(--jd-amber)",
                      color: "var(--jd-amber)",
                    }}
                    onClick={handleStop}
                    disabled={Boolean(state?.stopping)}
                  >
                    {state?.stopping
                      ? "Stopping after current request…"
                      : "Stop collection"}
                  </button>
                )}
                <div style={{ marginTop: 12 }}>
                  <a
                    className="jd-btn ghost"
                    href={exportFoundersUrl(batch || undefined)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Export contacts CSV
                  </a>
                </div>
              </div>

              <div className="jd-card">
                <h3
                  style={{
                    margin: "0 0 14px",
                    fontFamily: "Sora",
                    fontWeight: 600,
                  }}
                >
                  Progress
                </h3>
                {state ? (
                  <div style={{ display: "grid", gap: 8, fontSize: 13 }}>
                    <div>
                      <span style={{ color: "var(--jd-muted)" }}>Stage: </span>
                      {state.stage}
                      {state.batch ? ` · ${state.batch}` : ""}
                    </div>
                    <div>
                      <span style={{ color: "var(--jd-muted)" }}>
                        Companies:{" "}
                      </span>
                      {state.companies_done}/{state.companies_total || "?"}
                      {state.companies_skipped
                        ? ` (${state.companies_skipped} skipped)`
                        : ""}
                    </div>
                    <div>
                      <span style={{ color: "var(--jd-muted)" }}>
                        Founders / jobs / emails:{" "}
                      </span>
                      {state.founders_found} / {state.jobs_found} /{" "}
                      {state.emails_found}
                    </div>
                    {state.current_company && (
                      <div
                        className="mono"
                        style={{ fontSize: 11, color: "var(--jd-cyan)" }}
                      >
                        {state.current_company}
                      </div>
                    )}
                    {state.finished_at && (
                      <div
                        className="mono"
                        style={{ fontSize: 11, color: "var(--jd-muted-2)" }}
                      >
                        last finished {state.finished_at}
                      </div>
                    )}
                    {state.errors.length > 0 && (
                      <details>
                        <summary
                          style={{
                            cursor: "pointer",
                            color: "var(--jd-amber)",
                          }}
                        >
                          {state.errors.length} recent error(s)
                        </summary>
                        <ul
                          style={{
                            margin: "8px 0 0 16px",
                            color: "var(--jd-muted)",
                            fontSize: 11,
                          }}
                        >
                          {state.errors.slice(-8).map((err, index) => (
                            <li key={index}>{err}</li>
                          ))}
                        </ul>
                      </details>
                    )}
                  </div>
                ) : (
                  <p style={{ color: "var(--jd-muted)" }}>Loading status…</p>
                )}
              </div>
            </div>

            <div className="jd-card" style={{ marginBottom: 18 }}>
              <div
                style={{
                  display: "flex",
                  gap: 12,
                  flexWrap: "wrap",
                  alignItems: "flex-end",
                }}
              >
                <div
                  className="jd-form-group"
                  style={{ minWidth: 180, marginBottom: 0 }}
                >
                  <label>Batch</label>
                  <select
                    className="jd-select"
                    value={batch}
                    onChange={(e) => setBatch(e.target.value)}
                  >
                    <option value="">All batches</option>
                    {BATCH_OPTIONS.map((value) => (
                      <option key={value} value={value}>
                        {value}
                      </option>
                    ))}
                  </select>
                </div>
                <div
                  className="jd-form-group"
                  style={{ flex: 1, minWidth: 220, marginBottom: 0 }}
                >
                  <label>Search</label>
                  <input
                    className="jd-input"
                    value={queryInput}
                    placeholder="founder, company, role…"
                    onChange={(e) => setQueryInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") setQuery(queryInput);
                    }}
                  />
                </div>
                {tab === "founders" ? (
                  <>
                    <label
                      style={{
                        display: "flex",
                        gap: 6,
                        alignItems: "center",
                        paddingBottom: 10,
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={hasEmail}
                        onChange={(e) => setHasEmail(e.target.checked)}
                      />
                      Email
                    </label>
                    <label
                      style={{
                        display: "flex",
                        gap: 6,
                        alignItems: "center",
                        paddingBottom: 10,
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={hasX}
                        onChange={(e) => setHasX(e.target.checked)}
                      />
                      X
                    </label>
                    <label
                      style={{
                        display: "flex",
                        gap: 6,
                        alignItems: "center",
                        paddingBottom: 10,
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={hasLinkedin}
                        onChange={(e) => setHasLinkedin(e.target.checked)}
                      />
                      LinkedIn
                    </label>
                  </>
                ) : tab === "companies" ? (
                  <label
                    style={{
                      display: "flex",
                      gap: 6,
                      alignItems: "center",
                      paddingBottom: 10,
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={onlyHiring}
                      onChange={(e) => setOnlyHiring(e.target.checked)}
                    />
                    Is hiring
                  </label>
                ) : null}
                <button
                  className="jd-btn"
                  style={{ marginBottom: 2 }}
                  onClick={() => setQuery(queryInput)}
                >
                  Apply
                </button>
              </div>
            </div>

            {tab === "founders" ? (
              founders.length === 0 ? (
                <div
                  className="jd-card"
                  style={{ textAlign: "center", padding: 40 }}
                >
                  <p style={{ color: "var(--jd-muted)", margin: 0 }}>
                    No founders stored yet. Start a collection above, or adjust
                    the filters.
                  </p>
                </div>
              ) : (
                <div className="jd-cards grid">
                  {founders.map((founder) => (
                    <article key={founder.id} className="jd-card">
                      <div
                        style={{
                          display: "flex",
                          gap: 8,
                          flexWrap: "wrap",
                          alignItems: "center",
                        }}
                      >
                        <Avatar
                          src={founder.avatar_url}
                          name={founder.name}
                          size={48}
                          radius={12}
                        />
                        <strong style={{ fontSize: 16 }}>{founder.name}</strong>
                        {founder.company_batch && (
                          <span className="jd-mini muted">
                            {founder.company_batch}
                          </span>
                        )}
                        {founder.company_is_hiring && (
                          <span className="jd-mini green">hiring</span>
                        )}
                      </div>
                      <div
                        style={{
                          display: "flex",
                          gap: 6,
                          alignItems: "center",
                          margin: "4px 0 8px",
                          color: "var(--jd-muted)",
                          flexWrap: "wrap",
                        }}
                      >
                        <Avatar
                          src={founder.company_logo_url}
                          name={founder.company_name}
                          size={18}
                          radius={4}
                        />
                        <span>
                          {founder.title ? `${founder.title} · ` : ""}
                          <a
                            href={founder.company_website || "#"}
                            target="_blank"
                            rel="noreferrer"
                          >
                            {founder.company_name}
                          </a>
                        </span>
                      </div>
                      {founder.company_one_liner && (
                        <p style={{ margin: "0 0 10px", fontSize: 13 }}>
                          {founder.company_one_liner}
                        </p>
                      )}
                      <div
                        style={{
                          display: "flex",
                          gap: 8,
                          flexWrap: "wrap",
                          marginBottom: 10,
                        }}
                      >
                        {founder.email && (
                          <a
                            className="jd-mini cyan"
                            href={`mailto:${founder.email}`}
                          >
                            ✉ {founder.email}
                            {founder.email_confidence === "guessed"
                              ? " (guessed)"
                              : ""}
                          </a>
                        )}
                        {founder.x_url && (
                          <SocialLink
                            href={founder.x_url}
                            network="x"
                            label={
                              founder.x_handle
                                ? `Open ${founder.x_handle} on X`
                                : "Open X profile"
                            }
                          />
                        )}
                        {founder.linkedin_url && (
                          <SocialLink
                            href={founder.linkedin_url}
                            network="linkedin"
                            label="Open LinkedIn profile"
                          />
                        )}
                        {founder.yc_has_email && !founder.email && (
                          <span className="jd-mini muted">
                            YC has email on file
                          </span>
                        )}
                      </div>
                      {founder.jobs.length > 0 && (
                        <div style={{ fontSize: 12, color: "var(--jd-muted)" }}>
                          Open roles:{" "}
                          {founder.jobs.slice(0, 3).map((job, index) => (
                            <span key={job.title}>
                              {index > 0 ? ", " : ""}
                              {job.url ? (
                                <a
                                  href={job.url}
                                  target="_blank"
                                  rel="noreferrer"
                                >
                                  {job.title}
                                </a>
                              ) : (
                                job.title
                              )}
                            </span>
                          ))}
                        </div>
                      )}
                    </article>
                  ))}
                </div>
              )
            ) : tab === "companies" ? (
              companies.length === 0 ? (
                <div
                  className="jd-card"
                  style={{ textAlign: "center", padding: 40 }}
                >
                  <p style={{ color: "var(--jd-muted)", margin: 0 }}>
                    No companies stored yet. Start a collection above.
                  </p>
                </div>
              ) : (
                <div className="jd-cards grid">
                  {companies.map((company) => (
                    <article key={company.id} className="jd-card">
                      <div
                        style={{
                          display: "flex",
                          gap: 8,
                          flexWrap: "wrap",
                          alignItems: "center",
                        }}
                      >
                        <Avatar
                          src={company.small_logo_url}
                          name={company.name}
                          size={48}
                          radius={12}
                        />
                        <strong style={{ fontSize: 16 }}>{company.name}</strong>
                        {company.batch && (
                          <span className="jd-mini muted">{company.batch}</span>
                        )}
                        {company.is_hiring && (
                          <span className="jd-mini green">hiring</span>
                        )}
                      </div>
                      {company.one_liner && (
                        <p
                          style={{
                            margin: "4px 0 8px",
                            color: "var(--jd-muted)",
                          }}
                        >
                          {company.one_liner}
                        </p>
                      )}
                      <p
                        className="mono"
                        style={{
                          fontSize: 11,
                          color: "var(--jd-muted-2)",
                          margin: "0 0 8px",
                        }}
                      >
                        {company.founders_count} founder(s) ·{" "}
                        {company.jobs_count} open role(s)
                        {company.team_size
                          ? ` · team ${company.team_size}`
                          : ""}
                      </p>
                      <div
                        style={{ display: "flex", gap: 8, flexWrap: "wrap" }}
                      >
                        {company.website && (
                          <a
                            className="jd-btn ghost"
                            href={company.website}
                            target="_blank"
                            rel="noreferrer"
                          >
                            Website ↗
                          </a>
                        )}
                        <a
                          className="jd-btn ghost"
                          href={`/yc-founders?company=${encodeURIComponent(company.slug)}`}
                          onClick={(event) => {
                            event.preventDefault();
                            setQuery(company.name);
                            setQueryInput(company.name);
                            setTab("founders");
                          }}
                        >
                          View founders
                        </a>
                        {company.email && (
                          <a
                            className="jd-mini cyan"
                            href={`mailto:${company.email}`}
                          >
                            ✉ {company.email}
                          </a>
                        )}
                      </div>
                    </article>
                  ))}
                </div>
              )
            ) : jobs.length === 0 ? (
              <div
                className="jd-card"
                style={{ textAlign: "center", padding: 40 }}
              >
                <p style={{ color: "var(--jd-muted)", margin: 0 }}>
                  No open roles stored yet. Start a collection above.
                </p>
              </div>
            ) : (
              <div className="jd-cards grid">
                {jobs.map((job) => (
                  <article key={job.id} className="jd-card">
                    <div
                      style={{
                        display: "flex",
                        gap: 8,
                        flexWrap: "wrap",
                        alignItems: "center",
                      }}
                    >
                      <strong style={{ fontSize: 15 }}>
                        {job.url ? (
                          <a href={job.url} target="_blank" rel="noreferrer">
                            {job.title}
                          </a>
                        ) : (
                          job.title
                        )}
                      </strong>
                      {job.company_batch && (
                        <span className="jd-mini muted">
                          {job.company_batch}
                        </span>
                      )}
                      {job.company_is_hiring && (
                        <span className="jd-mini green">hiring</span>
                      )}
                    </div>
                    <div
                      style={{
                        margin: "4px 0 6px",
                        color: "var(--jd-muted)",
                        display: "flex",
                        gap: 6,
                        alignItems: "center",
                        flexWrap: "wrap",
                      }}
                    >
                      <Avatar
                        src={job.company_logo_url}
                        name={job.company_name}
                        size={18}
                        radius={4}
                      />
                      <span>
                        {job.company_website ? (
                          <a
                            href={job.company_website}
                            target="_blank"
                            rel="noreferrer"
                          >
                            {job.company_name}
                          </a>
                        ) : (
                          job.company_name
                        )}
                        {job.location ? ` · ${job.location}` : ""}
                      </span>
                    </div>
                    {job.company_one_liner && (
                      <p
                        style={{
                          margin: "0 0 8px",
                          fontSize: 13,
                          color: "var(--jd-muted-2)",
                        }}
                      >
                        {job.company_one_liner}
                      </p>
                    )}
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                      {job.url && (
                        <a
                          className="jd-btn ghost"
                          href={job.url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          View role ↗
                        </a>
                      )}
                      {job.company_slug && (
                        <a
                          className="jd-btn ghost"
                          href={`/yc-founders?company=${encodeURIComponent(job.company_slug)}`}
                          onClick={(event) => {
                            event.preventDefault();
                            const name = job.company_name ?? "";
                            setQuery(name);
                            setQueryInput(name);
                            setTab("founders");
                          }}
                        >
                          View founders
                        </a>
                      )}
                    </div>
                  </article>
                ))}
              </div>
            )}
            <div style={{ marginTop: 16, textAlign: "center" }}>
              {tab === "founders" && founders.length < foundersTotal && (
                <button
                  className="jd-btn"
                  onClick={() => setFoundersLimit((value) => value + PAGE_SIZE)}
                >
                  Load more founders ({founders.length} / {foundersTotal})
                </button>
              )}
              {tab === "companies" && companies.length < companiesTotal && (
                <button
                  className="jd-btn"
                  onClick={() =>
                    setCompaniesLimit((value) => value + PAGE_SIZE)
                  }
                >
                  Load more companies ({companies.length} / {companiesTotal})
                </button>
              )}
              {tab === "jobs" && jobs.length < jobsTotal && (
                <button
                  className="jd-btn"
                  onClick={() => setJobsLimit((value) => value + PAGE_SIZE)}
                >
                  Load more roles ({jobs.length} / {jobsTotal})
                </button>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
