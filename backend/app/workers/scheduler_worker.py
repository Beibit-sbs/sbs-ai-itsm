from __future__ import annotations

import logging
import os
import signal
import threading
import uuid
from datetime import UTC, datetime
from types import FrameType
from urllib.parse import urlsplit

from redis import Redis
from redis.exceptions import RedisError

from app.core.config import get_settings
from app.core.observability import configure_logging
from app.workers.jobs_worker import run_periodic_cycles


logger = logging.getLogger("app.jobs.scheduler")
_LEASE_KEY = "sbs:jobs:scheduler:lease"
_HEARTBEAT_KEY = "sbs:jobs:scheduler:heartbeat"
_METADATA_KEY = "sbs:jobs:scheduler:metadata"
_RENEW_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('expire', KEYS[1], ARGV[2])
end
return 0
"""
_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""


def _publish_heartbeat(
    redis_client: Redis,
    *,
    instance_id: str,
    ttl_seconds: int,
) -> None:
    now = datetime.now(UTC)
    redis_client.set(_HEARTBEAT_KEY, f"{now.timestamp():.6f}", ex=ttl_seconds)
    redis_client.hset(
        _METADATA_KEY,
        mapping={
            "instance": instance_id,
            "updated_at": now.isoformat(),
            "role": "leader",
        },
    )
    redis_client.expire(_METADATA_KEY, ttl_seconds)


def _renew_lease(
    redis_client: Redis,
    *,
    instance_id: str,
    lease_seconds: int,
) -> bool:
    return bool(
        redis_client.eval(
            _RENEW_SCRIPT,
            1,
            _LEASE_KEY,
            instance_id,
            lease_seconds,
        )
    )


def _keep_lease_alive(
    redis_client: Redis,
    *,
    instance_id: str,
    lease_seconds: int,
    heartbeat_ttl_seconds: int,
    refresh_seconds: int,
    stop_event: threading.Event,
    lease_lost: threading.Event,
) -> None:
    while not stop_event.wait(refresh_seconds):
        try:
            if not _renew_lease(
                redis_client,
                instance_id=instance_id,
                lease_seconds=lease_seconds,
            ):
                lease_lost.set()
                logger.error("scheduler_lease_lost", extra={"instance": instance_id})
                return
            _publish_heartbeat(
                redis_client,
                instance_id=instance_id,
                ttl_seconds=heartbeat_ttl_seconds,
            )
        except RedisError:
            lease_lost.set()
            logger.exception("scheduler_lease_renewal_failed")
            return


def run_scheduler_forever() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    redis_client = Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_timeout=5,
        socket_connect_timeout=5,
        health_check_interval=30,
    )
    shutdown_event = threading.Event()
    instance_id = f"{os.getenv('HOSTNAME', 'local')}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
    heartbeat_ttl = max(
        settings.scheduler_lease_seconds,
        settings.scheduler_heartbeat_max_age_seconds * 2,
    )
    refresh_seconds = max(
        1,
        min(
            settings.scheduler_poll_interval_seconds,
            settings.scheduler_lease_seconds // 3,
        ),
    )

    def request_shutdown(signum: int, _frame: FrameType | None) -> None:
        if shutdown_event.is_set():
            return
        logger.info(
            "scheduler_draining",
            extra={"signal": signal.Signals(signum).name},
        )
        shutdown_event.set()

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)
    logger.info(
        "scheduler_started",
        extra={
            "instance": instance_id,
            "redis_host": urlsplit(settings.redis_url).hostname,
            "poll_interval_seconds": settings.scheduler_poll_interval_seconds,
            "lease_seconds": settings.scheduler_lease_seconds,
        },
    )

    try:
        while not shutdown_event.is_set():
            try:
                is_leader = bool(
                    redis_client.set(
                        _LEASE_KEY,
                        instance_id,
                        nx=True,
                        ex=settings.scheduler_lease_seconds,
                    )
                )
                if not is_leader:
                    is_leader = _renew_lease(
                        redis_client,
                        instance_id=instance_id,
                        lease_seconds=settings.scheduler_lease_seconds,
                    )
            except RedisError:
                logger.exception("scheduler_lease_acquisition_failed")
                shutdown_event.wait(settings.scheduler_poll_interval_seconds)
                continue

            if not is_leader:
                shutdown_event.wait(settings.scheduler_poll_interval_seconds)
                continue

            lease_lost = threading.Event()
            renewal_stop = threading.Event()
            _publish_heartbeat(
                redis_client,
                instance_id=instance_id,
                ttl_seconds=heartbeat_ttl,
            )
            renewal_thread = threading.Thread(
                target=_keep_lease_alive,
                kwargs={
                    "redis_client": redis_client,
                    "instance_id": instance_id,
                    "lease_seconds": settings.scheduler_lease_seconds,
                    "heartbeat_ttl_seconds": heartbeat_ttl,
                    "refresh_seconds": refresh_seconds,
                    "stop_event": renewal_stop,
                    "lease_lost": lease_lost,
                },
                name="scheduler-lease-renewal",
                daemon=True,
            )
            renewal_thread.start()
            try:
                run_periodic_cycles()
                if not lease_lost.is_set():
                    _publish_heartbeat(
                        redis_client,
                        instance_id=instance_id,
                        ttl_seconds=heartbeat_ttl,
                    )
            except Exception:
                logger.exception("scheduler_cycle_failed")
            finally:
                renewal_stop.set()
                renewal_thread.join(timeout=max(2, refresh_seconds + 1))

            shutdown_event.wait(settings.scheduler_poll_interval_seconds)
    except KeyboardInterrupt:
        shutdown_event.set()
    finally:
        try:
            redis_client.eval(_RELEASE_SCRIPT, 1, _LEASE_KEY, instance_id)
        except RedisError:
            logger.exception("scheduler_lease_release_failed")
        redis_client.close()
        logger.info("scheduler_stopped", extra={"instance": instance_id})


if __name__ == "__main__":
    run_scheduler_forever()
