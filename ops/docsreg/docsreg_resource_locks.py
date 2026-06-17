"""
DOCSREG resource locks — Redis-backed distributed locks for pipeline stage isolation.

Usage:
    lock = RedisResourceLock(redis_client, LOCK_SLOT32, ttl_seconds=60)
    with lock:
        # slot32 is exclusively held here
        ...

    # Or manual acquire/release:
    if lock.acquire(wait=True, timeout=30.0):
        try:
            ...
        finally:
            lock.release()
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pre-defined lock name constants
# ---------------------------------------------------------------------------

LOCK_SLOT32 = "model_group_slot32_exclusive"
LOCK_SLOT120 = "model_group_slot32_exclusive"  # intentionally same key — cannot run concurrently
LOCK_OCR = "ocr"
LOCK_DB_WRITE = "db_write"
LOCK_REFERENCE_GOVERNANCE = "reference_governance"
LOCK_MASTER_REGISTRATION = "master_registration"
LOCK_CLAUDE_CODE_AUDITOR = "claude_code_auditor"


# ---------------------------------------------------------------------------
# RedisResourceLock
# ---------------------------------------------------------------------------

class RedisResourceLock:
    """
    Distributed lock backed by a Redis SET NX PX pattern.

    Parameters
    ----------
    redis_client:
        Any object exposing ``.set()``, ``.get()``, ``.delete()``,
        ``.expire()`` — e.g. a ``redis.Redis`` or ``fakeredis.FakeRedis``
        instance.  Not imported at module level to avoid a hard dependency.
    name:
        Logical lock name.  The Redis key will be ``docsreg:lock:{name}``.
    ttl_seconds:
        Lock auto-expiry in seconds (default 30).
    owner_id:
        Unique string identifying this holder.  If *None*, a UUID4 is
        generated automatically.
    wait_timeout:
        Maximum seconds to wait when the context manager tries to acquire
        the lock (``__enter__``).  Defaults to 30.0.  For locks that may
        be held for several minutes (e.g. ``LOCK_SLOT32`` during model
        generation), pass a larger value such as ``600.0``.
    """

    def __init__(
        self,
        redis_client: Any,
        name: str,
        ttl_seconds: int = 30,
        owner_id: str | None = None,
        wait_timeout: float = 30.0,
    ) -> None:
        self._redis = redis_client
        self._name = name
        self._ttl_seconds = ttl_seconds
        self._owner_id: str = owner_id if owner_id is not None else str(uuid.uuid4())
        self._acquired: bool = False
        self._wait_timeout = wait_timeout

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def key(self) -> str:
        """Redis key for this lock."""
        return f"docsreg:lock:{self._name}"

    @property
    def owner_id(self) -> str:
        return self._owner_id

    @property
    def acquired(self) -> bool:
        return self._acquired

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def acquire(
        self,
        wait: bool = False,
        poll_interval: float = 0.5,
        timeout: float = 30.0,
    ) -> bool:
        """
        Attempt to acquire the lock.

        Parameters
        ----------
        wait:
            When *False* (default) return immediately.  When *True* poll
            until acquired or *timeout* is exceeded.
        poll_interval:
            Seconds to sleep between polls when *wait=True*.
        timeout:
            Maximum wall-clock seconds to wait when *wait=True*.

        Returns
        -------
        bool
            ``True`` if the lock was acquired, ``False`` otherwise.
        """
        ttl_ms = self._ttl_seconds * 1000
        deadline = time.monotonic() + timeout

        while True:
            result = self._redis.set(self.key, self._owner_id, nx=True, px=ttl_ms)
            if result:
                self._acquired = True
                logger.debug("Lock acquired: %s (owner=%s)", self.key, self._owner_id)
                return True

            if not wait:
                logger.debug("Lock already held: %s", self.key)
                return False

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.debug(
                    "Lock acquire timed out after %.1fs: %s", timeout, self.key
                )
                return False

            time.sleep(min(poll_interval, remaining))

    def release(self) -> bool:
        """
        Release the lock only if this instance still owns it.

        Returns
        -------
        bool
            ``True`` if the lock was released, ``False`` if it was not held
            by this owner (already expired or taken by someone else).

        Note
        ----
        The owner check (GET) and deletion (DELETE) are not atomic. In a
        truly distributed multi-process scenario, the TTL could expire
        between the two calls, allowing another owner to acquire the lock
        before the DELETE fires. This implementation assumes single-process
        use; for multi-process use, replace with a Lua eval script.
        """
        current = self._redis.get(self.key)
        if current is None:
            self._acquired = False
            logger.debug("Lock release skipped (key gone): %s", self.key)
            return False

        # Decode bytes if necessary
        if isinstance(current, bytes):
            current = current.decode("utf-8")

        if current != self._owner_id:
            self._acquired = False
            logger.debug(
                "Lock release skipped (owner mismatch): %s (held by %s, we are %s)",
                self.key,
                current,
                self._owner_id,
            )
            return False

        self._redis.delete(self.key)
        self._acquired = False
        logger.debug("Lock released: %s (owner=%s)", self.key, self._owner_id)
        return True

    def refresh(self, ttl_seconds: int | None = None) -> bool:
        """
        Extend the lock TTL, but only if this instance still owns it.

        Parameters
        ----------
        ttl_seconds:
            New TTL in seconds.  Defaults to the constructor value.

        Returns
        -------
        bool
            ``True`` if the TTL was refreshed, ``False`` if the lock no
            longer belongs to this owner.

        Note
        ----
        The owner check (GET) and TTL extension (EXPIRE) are not atomic.
        In a multi-process scenario, the lock could expire and be acquired
        by another owner between the two calls. Single-process use is assumed.
        """
        current = self._redis.get(self.key)
        if current is None:
            logger.debug("Lock refresh skipped (key gone): %s", self.key)
            return False

        if isinstance(current, bytes):
            current = current.decode("utf-8")

        if current != self._owner_id:
            logger.debug(
                "Lock refresh skipped (owner mismatch): %s", self.key
            )
            return False

        effective_ttl = ttl_seconds if ttl_seconds is not None else self._ttl_seconds
        self._redis.expire(self.key, effective_ttl)
        logger.debug(
            "Lock TTL refreshed: %s (ttl=%ds, owner=%s)",
            self.key,
            effective_ttl,
            self._owner_id,
        )
        return True

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "RedisResourceLock":
        if not self.acquire(wait=True, timeout=self._wait_timeout):
            raise RuntimeError(f"Could not acquire lock: {self._name}")
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.release()
