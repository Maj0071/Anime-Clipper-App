"""
Celery tasks for clip discovery, daily curation, scheduled posting, and cleanup.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.workers.celery_app import celery_app
from app.database import SessionLocal
from app.models import ClipSuggestion, ScheduledPost, SocialAccount

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Run an async coroutine from sync Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(name="clip_tasks.discover_clips", bind=True, max_retries=2)
def discover_clips(self, max_per_source=25):
    """
    Discover trending anime clips from YouTube and Reddit.

    Runs every 6 hours via Celery Beat.
    """
    from app.services.clip_discovery_service import ClipDiscoveryService

    logger.info("Starting clip discovery task")
    db = SessionLocal()

    async def _discover():
        service = ClipDiscoveryService()
        try:
            suggestions = await service.discover_trending_clips(
                max_per_source=max_per_source,
            )

            added = 0
            for suggestion in suggestions:
                existing = db.query(ClipSuggestion).filter(
                    ClipSuggestion.external_id == suggestion.external_id,
                ).first()

                if not existing:
                    db.add(suggestion)
                    added += 1

            db.commit()
            logger.info(f"Clip discovery complete: {added} new clips added")
            return added

        finally:
            await service.close()

    try:
        return _run_async(_discover())
    except Exception as e:
        logger.error(f"Clip discovery failed: {e}")
        db.rollback()
        raise self.retry(exc=e, countdown=300)
    finally:
        db.close()


@celery_app.task(name="clip_tasks.curate_daily", bind=True)
def curate_daily(self):
    """
    Curate daily suggestion picks.

    Runs once per day via Celery Beat.
    """
    from app.services.clip_discovery_service import ClipDiscoveryService

    logger.info("Starting daily curation task")
    db = SessionLocal()

    async def _curate():
        service = ClipDiscoveryService()
        try:
            daily = await service.curate_daily_suggestions(db_session=db)
            db.commit()
            logger.info(f"Daily curation complete: {len(daily)} picks")
            return len(daily)
        finally:
            await service.close()

    try:
        return _run_async(_curate())
    except Exception as e:
        logger.error(f"Daily curation failed: {e}")
        db.rollback()
    finally:
        db.close()


@celery_app.task(name="clip_tasks.publish_scheduled_posts", bind=True)
def publish_scheduled_posts(self):
    """
    Publish any scheduled posts whose time has arrived.

    Runs every minute via Celery Beat.
    """
    from app.services.social_posting_service import SocialPostingService

    db = SessionLocal()
    now = datetime.now(timezone.utc)

    try:
        pending_posts = db.query(ScheduledPost).filter(
            ScheduledPost.status == "pending",
            ScheduledPost.scheduled_time <= now,
        ).all()

        if not pending_posts:
            return 0

        logger.info(f"Publishing {len(pending_posts)} scheduled posts")

        async def _publish_all():
            service = SocialPostingService()
            published = 0

            try:
                for post in pending_posts:
                    account = db.query(SocialAccount).filter(
                        SocialAccount.id == post.social_account_id,
                        SocialAccount.is_active == 1,
                    ).first()

                    if not account:
                        post.status = "failed"
                        post.error_message = "Account not found or disconnected"
                        db.commit()
                        continue

                    caption = post.caption or ""
                    if post.hashtags:
                        caption += "\n\n" + " ".join(f"#{tag}" for tag in post.hashtags)

                    try:
                        if account.platform == "tiktok":
                            result = await service.post_to_tiktok(
                                account=account,
                                video_path=post.video_path,
                                caption=caption,
                                db_session=db,
                            )
                        elif account.platform == "instagram":
                            result = await service.post_to_instagram(
                                account=account,
                                video_url=post.video_path,
                                caption=caption,
                                db_session=db,
                            )
                        else:
                            post.status = "failed"
                            post.error_message = f"Unsupported platform: {account.platform}"
                            db.commit()
                            continue

                        if result.success:
                            post.status = "posted"
                            post.posted_at = datetime.now(timezone.utc)
                            post.post_id = result.post_id
                            post.post_url = result.post_url
                            published += 1
                        else:
                            post.status = "failed"
                            post.error_message = result.error

                        db.commit()

                    except Exception as e:
                        logger.error(f"Failed to publish post {post.id}: {e}")
                        post.status = "failed"
                        post.error_message = str(e)
                        db.commit()

            finally:
                await service.close()

            return published

        return _run_async(_publish_all())

    except Exception as e:
        logger.error(f"Scheduled post publishing failed: {e}")
        db.rollback()
    finally:
        db.close()


@celery_app.task(name="clip_tasks.cleanup_expired")
def cleanup_expired():
    """
    Clean up expired suggestions and old downloads.

    Runs daily via Celery Beat.
    """
    from app.services.video_download_service import VideoDownloadService

    db = SessionLocal()

    try:
        now = datetime.now(timezone.utc)

        # Mark expired suggestions
        expired = db.query(ClipSuggestion).filter(
            ClipSuggestion.expires_at <= now,
            ClipSuggestion.status == "active",
        ).update({"status": "expired"})

        db.commit()
        logger.info(f"Marked {expired} suggestions as expired")

        # Clean up old download files
        async def _cleanup():
            service = VideoDownloadService()
            removed = await service.cleanup_old_downloads(max_age_hours=24)
            return removed

        removed = _run_async(_cleanup())
        logger.info(f"Cleaned up {removed} old download files")

        return {"expired_suggestions": expired, "removed_files": removed}

    except Exception as e:
        logger.error(f"Cleanup failed: {e}")
        db.rollback()
    finally:
        db.close()
