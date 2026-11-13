import { createFileRoute } from "@tanstack/react-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { TopNav } from "@/features/jobs/components/TopNav";
import { HiringPostCard } from "@/features/jobs/components/HiringPostCard";
import { getHiringPosts, getSocialStatus, openSocialSession, runSocialScan } from "@/features/jobs/api";
import type { HiringPost, SocialStatusResponse } from "@/features/jobs/types";
import "@/features/jobs/jobdork.css";

export const Route = createFileRoute("/hiring-posts")({
  head: () => ({
    meta: [
      { title: "Hiring Posts — LinkedIn, X & Reddit" },
      { name: "description", content: "Scan LinkedIn, X and Reddit for fresh remote hiring posts from the last 24 hours." },
    ],
  }),
  component: HiringPostsPage,
});

const DEFAULT_PLATFORMS = ["linkedin", "x", "reddit"];

const MENA_COUNTRIES: Array<{ id: string; label: string; flag: string }> = [
  { id: "egypt", label: "Egypt", flag: "🇪🇬" },
  { id: "saudi arabia", label: "Saudi Arabia", flag: "🇸🇦" },
  { id: "united arab emirates", label: "UAE", flag: "🇦🇪" },
  { id: "qatar", label: "Qatar", flag: "🇶🇦" },
  { id: "kuwait", label: "Kuwait", flag: "🇰🇼" },
  { id: "bahrain", label: "Bahrain", flag: "🇧🇭" },
  { id: "oman", label: "Oman", flag: "🇴🇲" },
  { id: "jordan", label: "Jordan", flag: "🇯🇴" },
  { id: "middle east", label: "Middle East / MENA", flag: "🌍" },
];

const DEFAULT_COUNTRIES = MENA_COUNTRIES.filter((c) => c.id !== "middle east").map((c) => c.id);

function HiringPostsPage() {
  const [status, setStatus] = useState<SocialStatusResponse | null>(null);
  const [posts, setPosts] = useState<HiringPost[]>([]);
  const [total, setTotal] = useState(0);
  const [keywordsInput, setKeywordsInput] = useState("devops, backend, python, frontend");
  const [platforms, setPlatforms] = useState<string[]>(DEFAULT_PLATFORMS);
  const [countries, setCountries] = useState<string[]>(DEFAULT_COUNTRIES);
  const [strictRegion, setStrictRegion] = useState(false);
  const [maxPosts, setMaxPosts] = useState(40);
  const [filterPlatform, setFilterPlatform] = useState("all");
  const [minScore, setMinScore] = useState(0);
  const [loading, setLoading] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);
  const sessionPollRef = useRef<number | null>(null);

  const keywords = keywordsInput
    .split(",")
    .map((k) => k.trim())
    .filter(Boolean);

  const loadPosts = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getHiringPosts({
        platform: filterPlatform,
        keywords,
        minScore,
        limit: 100,
      });
      setPosts(data.posts);
      setTotal(data.total);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load hiring posts");
    } finally {
      setLoading(false);
    }
  }, [filterPlatform, minScore, keywordsInput]);

  const loadStatus = useCallback(async () => {
    try {
      const data = await getSocialStatus();
      setStatus(data);
      return data;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load social scan status");
      return null;
    }
  }, []);

  useEffect(() => {
    loadStatus();
    loadPosts();
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
      if (sessionPollRef.current) window.clearInterval(sessionPollRef.current);
    };
  }, []);

  useEffect(() => {
    loadPosts();
  }, [filterPlatform, minScore]);

  const stopPolling = () => {
    if (pollRef.current) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  const startPolling = () => {
    stopPolling();
    pollRef.current = window.setInterval(async () => {
      const data = await loadStatus();
      if (data && !data.state.running) {
        stopPolling();
        setScanning(false);
        setMessage("Scan finished. Refreshing results…");
        await loadPosts();
      }
    }, 5000);
  };

  const stopSessionPolling = () => {
    if (sessionPollRef.current) {
      window.clearInterval(sessionPollRef.current);
      sessionPollRef.current = null;
    }
  };

  const startSessionPolling = () => {
    stopSessionPolling();
    sessionPollRef.current = window.setInterval(async () => {
      const data = await loadStatus();
      const sessions = data?.sessions ? Object.values(data.sessions) : [];
      const stillOpen = sessions.some((session) => session.running);
      if (!stillOpen) {
        stopSessionPolling();
        const failed = sessions.find((session) => session.error);
        const timedOut = sessions.find((session) => session.timed_out);
        if (failed?.error) {
          setError(`The login browser failed: ${failed.error}`);
        } else if (timedOut) {
          setMessage(
            "Login window closed after the timeout. Re-open it if you still need to sign in."
          );
        } else {
          setMessage(
            "Browser closed. The session was saved — you can run a scan again."
          );
        }
      }
    }, 3000);
  };

  const handleOpenBrowser = async (platform: string) => {
    setError(null);
    setMessage(null);
    try {
      const res = await openSocialSession(platform);
      setMessage(res.message);
      if (res.status === "error") {
        setError(res.message);
        return;
      }
      startSessionPolling();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to open the login browser"
      );
    }
  };

  const handleScan = async () => {
    if (scanning) return;
    const ok = confirm(
      "This logs into LinkedIn/X with your saved session and reads public Reddit feeds, then scans hiring posts from the last 24 hours.\n\n" +
        "Run this only 2-3 times per day to avoid rate limits. Continue?"
    );
    if (!ok) return;

    setScanning(true);
    setError(null);
    setMessage(null);
    try {
      const res = await runSocialScan({
        keywords,
        platforms,
        countries,
        max_posts: maxPosts,
        strict_region: strictRegion,
      });
      setMessage(res.message);
      if (res.status === "error") {
        setScanning(false);
        setError(res.message);
        return;
      }
      if (res.status === "already_running") {
        setScanning(false);
        return;
      }
      startPolling();
    } catch (err) {
      setScanning(false);
      setError(err instanceof Error ? err.message : "Failed to start the scan");
    }
  };

  const togglePlatform = (platform: string) => {
    setPlatforms((prev) =>
      prev.includes(platform) ? prev.filter((p) => p !== platform) : [...prev, platform]
    );
  };

  const toggleCountry = (country: string) => {
    setCountries((prev) =>
      prev.includes(country) ? prev.filter((c) => c !== country) : [...prev, country]
    );
  };

  const platformState = (name: string) => status?.platforms?.[name];
  const sessionState = (name: string) => status?.sessions?.[name];
  const anyBrowserOpen = Boolean(
    status?.sessions && Object.values(status.sessions).some((session) => session.running)
  );
  const running = scanning || Boolean(status?.state?.running);
  const platformLabel = (platform: string) =>
    platform === "x" ? "X (Twitter)" : platform === "reddit" ? "Reddit" : "LinkedIn";

  return (
    <div className="jobdork">
      <TopNav />
      {running && <div className="jd-progress" />}

      <div className="jd-aggregation-page">
        <div className="jd-page-header">
          <h1>Hiring posts — LinkedIn, X &amp; Reddit</h1>
          <p>
            Scans public “we are hiring” posts from the last 24 hours, keeps only
            remote roles (hybrid/onsite are excluded), and ranks them by relevance and
            authenticity. Manual only — run it a few times per day.
          </p>
        </div>

        {error && (
          <div className="jd-card" style={{ marginBottom: 24, border: "1px solid var(--jd-red)" }}>
            <p style={{ color: "var(--jd-red)", margin: 0 }}>{error}</p>
          </div>
        )}
        {message && (
          <div className="jd-card" style={{ marginBottom: 24, border: "1px solid var(--jd-border)" }}>
            <p style={{ margin: 0, color: "var(--jd-muted)" }}>{message}</p>
          </div>
        )}

        <div className="jd-grid-2">
          <div className="jd-card">
            <h3 style={{ margin: "0 0 16px", fontFamily: "Sora", fontWeight: 600 }}>Scan controls</h3>

            <div className="jd-form-group">
              <label>Keywords</label>
              <input
                className="jd-input"
                value={keywordsInput}
                onChange={(e) => setKeywordsInput(e.target.value)}
                placeholder="devops, backend, python"
              />
            </div>

            <div className="jd-form-group">
              <label>Platforms</label>
              <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
                {DEFAULT_PLATFORMS.map((platform) => {
                  const info = platformState(platform);
                  const session = sessionState(platform);
                  const available = Boolean(
                    info?.credentials || info?.saved_session || info?.public_feed
                  );
                  return (
                    <label key={platform} className="jd-hp-platform-toggle">
                      <input
                        type="checkbox"
                        checked={platforms.includes(platform)}
                        onChange={() => togglePlatform(platform)}
                      />
                      <span>{platformLabel(platform)}</span>
                      <span className={`jd-hp-availability ${available ? "ok" : "missing"}`}>
                        {session?.running ? "browser open" : available ? "configured" : "no session"}
                      </span>
                    </label>
                  );
                })}
              </div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 10 }}>
                {DEFAULT_PLATFORMS.map((platform) => {
                  const session = sessionState(platform);
                  return (
                    <button
                      key={platform}
                      type="button"
                      className="jd-btn ghost"
                      style={{ fontSize: 12, padding: "8px 12px" }}
                      onClick={() => handleOpenBrowser(platform)}
                      disabled={running || Boolean(session?.running)}
                      title="Opens a visible browser with the saved profile so you can re-login or complete a security check."
                    >
                      {session?.running
                        ? `${platformLabel(platform)}: browser open`
                        : `Open ${platformLabel(platform)} login`}
                    </button>
                  );
                })}
              </div>
              <p className="mono" style={{ color: "var(--jd-muted-2)", fontSize: 11, marginTop: 8 }}>
                Use these if a platform signed you out or asked for a security check. Log in
                in the window, then close it — the saved session is reused by the next scan.
              </p>
              <p className="mono" style={{ color: "var(--jd-muted-2)", fontSize: 11, marginTop: 8 }}>
                LinkedIn/X use saved sessions; Reddit reads public feeds. Credentials come from{" "}
                <code>auth-access.txt</code> / <code>backend/.env</code>.
              </p>
            </div>

            <div className="jd-form-group">
              <label>Countries / region</label>
              <div className="jd-hp-country-grid">
                {MENA_COUNTRIES.map((country) => (
                  <label key={country.id} className="jd-hp-platform-toggle">
                    <input
                      type="checkbox"
                      checked={countries.includes(country.id)}
                      onChange={() => toggleCountry(country.id)}
                    />
                    <span>
                      {country.flag} {country.label}
                    </span>
                  </label>
                ))}
              </div>
              <p className="mono" style={{ color: "var(--jd-muted-2)", fontSize: 11, marginTop: 8 }}>
                Selected countries are added to every LinkedIn/X query (e.g. Egypt, Cairo,
                Saudi Arabia, Riyadh, UAE, Dubai, Qatar, Doha, MENA).
              </p>
              <label className="jd-hp-platform-toggle" style={{ marginTop: 8 }}>
                <input
                  type="checkbox"
                  checked={strictRegion}
                  onChange={(e) => setStrictRegion(e.target.checked)}
                />
                <span>Only posts mentioning the selected region</span>
              </label>
            </div>

            <div className="jd-form-group">
              <label>Max posts per platform: {maxPosts}</label>
              <input
                type="range"
                min={10}
                max={100}
                step={10}
                className="jd-slider"
                value={maxPosts}
                onChange={(e) => setMaxPosts(parseInt(e.target.value, 10))}
              />
            </div>

            <button
              className="jd-btn primary"
              style={{ width: "100%", justifyContent: "center", padding: 14, marginTop: 12 }}
              onClick={handleScan}
              disabled={running || anyBrowserOpen || platforms.length === 0 || countries.length === 0}
            >
              {running
                ? "Scanning posts…"
                : anyBrowserOpen
                  ? "Close the login window to scan"
                  : "Scan hiring posts now"}
            </button>

            {status?.state?.last_result && (
              <pre className="jd-hp-last-result">
                {JSON.stringify(status.state.last_result, null, 2)}
              </pre>
            )}
          </div>

          <div className="jd-card">
            <h3 style={{ margin: "0 0 16px", fontFamily: "Sora", fontWeight: 600 }}>Filters</h3>
            <div className="jd-form-group">
              <label>Platform</label>
              <select
                className="jd-select"
                value={filterPlatform}
                onChange={(e) => setFilterPlatform(e.target.value)}
              >
                <option value="all">All platforms</option>
                <option value="linkedin">LinkedIn</option>
                <option value="x">X (Twitter)</option>
                <option value="reddit">Reddit</option>
              </select>
            </div>

            <div className="jd-form-group">
              <label>Minimum score: {minScore > 0 ? minScore.toFixed(1) : "any"}</label>
              <input
                type="range"
                min={0}
                max={8}
                step={0.5}
                className="jd-slider"
                value={minScore}
                onChange={(e) => setMinScore(parseFloat(e.target.value))}
              />
            </div>

            <button className="jd-btn ghost" style={{ width: "100%" }} onClick={loadPosts} disabled={loading}>
              {loading ? "Refreshing…" : "Refresh results"}
            </button>

            <div className="jd-stat-card" style={{ marginTop: 18 }}>
              <span className="label">Ranked posts (24h)</span>
              <span className="value gradient">{total}</span>
              <span className="desc">
                Only posts published within the last 24 hours are kept and scored.
              </span>
            </div>
          </div>
        </div>

        <div style={{ marginTop: 28 }}>
          {loading && posts.length === 0 ? (
            <p className="mono" style={{ color: "var(--jd-muted)" }}>Loading hiring posts…</p>
          ) : posts.length === 0 ? (
            <div className="jd-card" style={{ textAlign: "center", padding: 40 }}>
              <p style={{ color: "var(--jd-muted)", margin: 0 }}>
                No hiring posts yet. Trigger a scan above — results appear here once it finishes.
              </p>
            </div>
          ) : (
            <div className="jd-cards grid">
              {posts.map((post, index) => (
                <HiringPostCard key={post.id} post={post} index={index} />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
