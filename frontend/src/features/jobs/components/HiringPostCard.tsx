import type { HiringPost } from "../types";
import { relativeTime } from "../utils";

const VERDICT_META: Record<string, { label: string; className: string }> = {
  legit: { label: "✓ Legit", className: "legit" },
  suspicious: { label: "⚠ Suspicious", className: "suspicious" },
  likely_scam: { label: "✗ Likely scam", className: "scam" },
};

const PLATFORM_META: Record<string, { label: string; className: string }> = {
  linkedin: { label: "LinkedIn", className: "linkedin" },
  x: { label: "X", className: "x" },
};

function tone(score: number): string {
  if (score >= 7) return "high";
  if (score >= 4.5) return "mid";
  return "low";
}

export function HiringPostCard({ post, index }: { post: HiringPost; index: number }) {
  const score = typeof post.score === "number" ? post.score : null;
  const verdict = post.verdict ? VERDICT_META[post.verdict] : null;
  const platform = PLATFORM_META[post.platform] ?? { label: post.platform, className: post.platform };
  const rel = relativeTime(post.posted_at || post.scraped_at || "");
  const reasons = post.reasons?.filter(Boolean) ?? [];

  return (
    <article className="jd-hp-card" style={{ animationDelay: `${Math.min(index, 20) * 30}ms` }}>
      <div className="jd-hp-top">
        <span className={`jd-platform ${platform.className}`}>{platform.label}</span>
        <span className="jd-hp-author">
          {post.author_url ? (
            <a href={post.author_url} target="_blank" rel="noreferrer">
              {post.author || "Unknown author"}
            </a>
          ) : (
            post.author || "Unknown author"
          )}
        </span>
        <span className="spacer" />
        {score !== null && (
          <span className={`jd-score-badge ${tone(score)}`} title={reasons.join(" · ")}>
            {score.toFixed(1)} / 10
          </span>
        )}
        {verdict && (
          <span className={`jd-verdict ${verdict.className}`} title={reasons.join(" · ")}>
            {verdict.label}
          </span>
        )}
      </div>

      <p className="jd-hp-text">{post.text}</p>

      {post.keywords_matched?.length > 0 && (
        <div className="jd-hp-tags">
          {post.keywords_matched.slice(0, 6).map((kw) => (
            <span key={kw} className="jd-mini muted">
              {kw}
            </span>
          ))}
        </div>
      )}

      <div className="jd-hp-foot">
        <span className="mono">{rel || "recently"}</span>
        <a className="jd-btn primary" href={post.post_url} target="_blank" rel="noreferrer">
          Open post ↗
        </a>
      </div>
    </article>
  );
}
