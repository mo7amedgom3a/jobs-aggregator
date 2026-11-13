"""Manual social hiring-post scraping (LinkedIn / X / Reddit).

These collectors are triggered from the frontend a few times per day and are
intentionally excluded from the hourly spider scheduler.
"""

from services.social.collector import (
    collect_social_posts,
    platform_status,
    run_state,
)

__all__ = ["collect_social_posts", "platform_status", "run_state"]
