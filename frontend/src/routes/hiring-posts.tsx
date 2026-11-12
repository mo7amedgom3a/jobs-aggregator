import { createFileRoute } from "@tanstack/react-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { TopNav } from "@/features/jobs/components/TopNav";
import { HiringPostCard } from "@/features/jobs/components/HiringPostCard";
import { getHiringPosts, getSocialStatus, runSocialScan } from "@/features/jobs/api";
import type { HiringPost, SocialStatusResponse } from "@/features/jobs/types";
import "@/features/jobs/jobdork.css";

export const Route = createFileRoute("/hiring-posts")({
  head: () => ({
    meta: [
      { title: "Hiring Posts — LinkedIn & X" },
      { name: "description", content: "Scan LinkedIn and X for fresh hiring posts from the last 24 hours." },
    ],
  }),
  component: HiringPostsPage,
});

const DEFAULT_PLATFORMS = ["linkedin", "x"];

function HiringPostsPage() {
  const [status, setStatus] = useState<SocialStatusResponse | null>(null);
  const [posts, setPosts] = useState<HiringPost[]>([]);
  const [total, setTotal] = useState(0);
  const [keywordsInput, setKeywordsInput] = useState("devops, backend, python, frontend");
  const [platforms, setPlatforms] = useState<string[]>(DEFAULT_PLATFORMS);
  const [maxPosts, setMaxPosts] = useState(40);
  const [filterPlatform, setFilterPlatform] = useState("all");
  const [minScore, setMinScore] = useState(0);
  const [loading, setLoading] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);

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

  const handleScan = async () => {
    if (scanning) return;
    const ok = confirm(
      "This logs into LinkedIn/X with your saved session and scans public hiring posts from the last 24 hours.\n\n" +
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
        max_posts: maxPosts,
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

  const platformState = (name: string) => status?.platforms?.[name];
  const running = scanning || Boolean(status?.state?.running);

  return (
    <div className="jobdork">
      <TopNav />
      {running && <div className="jd-progress" />}

      <div className="jd-aggregation-page">
        <div className="jd-page-header">
          <h1>Hiring posts — LinkedIn &amp; X</h1>
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
                  const available = Boolean(info?.credentials || info?.saved_session);
                  return (
                    <label key={platform} className="jd-hp-platform-toggle">
                      <input
                        type="checkbox"
                        checked={platforms.includes(platform)}
                        onChange={() => togglePlatform(platform)}
                      />
                      <span>{platform === "x" ? "X (Twitter)" : "LinkedIn"}</span>
                      <span className={`jd-hp-availability ${available ? "ok" : "missing"}`}>
                        {available ? "configured" : "no session"}
                      </span>
                    </label>
                  );
                })}
              </div>
              <p className="mono" style={{ color: "var(--jd-muted-2)", fontSize: 11, marginTop: 8 }}>
                Credentials are read from <code>auth-access.txt</code> / <code>backend/.env</code>.
                The first run opens a browser window so you can complete any login challenge.
              </p>
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
              disabled={running || platforms.length === 0}
            >
              {running ? "Scanning posts…" : "Scan hiring posts now"}
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
