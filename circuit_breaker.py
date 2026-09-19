"""
circuit_breaker.py
===================
Per-role Circuit Breaker for the Tech News Judge pipeline.

Each model role (evidence_agent, extraction, judge, scorer, escalation) gets
its own independent CircuitBreaker instance, so a failing model only blocks
calls to itself — not the rest of the pipeline.

States:
    CLOSED     -> normal operation, requests pass through
    OPEN       -> too many recent failures, requests are blocked until cooldown expires
    HALF_OPEN  -> cooldown expired, next single request is allowed as a test

Note: this module only defines the CircuitBreaker class. The actual
`circuit_breakers = {role: CircuitBreaker(...) for role in MODEL_REGISTRY}`
dict is built in judge_agent.py (step 4), since it depends on
MODEL_REGISTRY, which lives there.
"""

import logging
import time

logger = logging.getLogger(__name__)


class CircuitBreakerOpenException(Exception):
    """Raised when a call is blocked because its circuit breaker is OPEN."""
    pass


class NonRetryableError(Exception):
    """
    Raised for errors a circuit breaker's cooldown/retry logic can never fix
    (e.g. HTTP 403 'this model requires a subscription'). These are surfaced
    immediately instead of being counted toward the failure threshold, since
    waiting and retrying will never change the outcome.
    """
    pass


class CircuitBreaker:
    """
    Circuit Breaker pattern implementation to prevent retry storms against
    a failing or rate-limited model.

    Attributes:
        name (str): Identifies which role/model this breaker guards
            (used in log messages, e.g. "judge", "escalation").
        failure_threshold (int): Number of consecutive failures allowed
            before the circuit trips to OPEN.
        cooldown_seconds (float): How long to stay OPEN before allowing
            a single test request (HALF_OPEN).
        failure_count (int): Current consecutive failure count.
        state (str): One of "CLOSED", "OPEN", "HALF_OPEN".
        last_state_change (float): Unix timestamp of the last state transition.
    """

    def __init__(self, name: str, failure_threshold: int = 3, cooldown_seconds: float = 30.0):
        """
        Initialize a new Circuit Breaker for a specific model role.

        Args:
            name: A short identifier for this breaker, used in logs
                (e.g. the MODEL_REGISTRY role name: "judge", "extraction", ...).
            failure_threshold: Consecutive failures required to trip the circuit OPEN.
            cooldown_seconds: Seconds to wait after tripping before testing again.
        """
        self.name = name
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.failure_count = 0
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self.last_state_change = time.time()

    def can_execute(self) -> bool:
        """
        Check whether a call is currently allowed to proceed.

        Returns:
            True if the circuit is CLOSED, or OPEN but the cooldown has
            expired (in which case the state transitions to HALF_OPEN and
            a single test request is allowed). False if the circuit is
            still OPEN and within its cooldown window.
        """
        now = time.time()
        if self.state == "OPEN":
            if now - self.last_state_change >= self.cooldown_seconds:
                self.state = "HALF_OPEN"
                self.last_state_change = now
                logger.warning(f"⚡ [{self.name}] Transitioned to HALF_OPEN. Testing next request.")
                return True
            return False
        return True

    def record_success(self):
        """
        Record a successful call. Resets the failure count and closes
        the circuit if it wasn't already CLOSED (e.g. recovering from
        HALF_OPEN after a successful test request).
        """
        if self.state != "CLOSED":
            logger.info(f"✅ [{self.name}] Request succeeded. Resetting state to CLOSED.")
        self.failure_count = 0
        self.state = "CLOSED"
        self.last_state_change = time.time()

    def record_failure(self, exc: Exception = None):
        """
        Record a failed call. Increments the failure count and trips the
        circuit to OPEN if the failure_threshold is reached.

        If the exception looks like a permanent/non-retryable error (e.g.
        HTTP 403 subscription-required), it is raised immediately as a
        NonRetryableError instead of being counted — cooling down and
        retrying would never fix that kind of error.

        Args:
            exc: The exception that caused the failure, if available.
                 Used to detect non-retryable error types.

        Raises:
            NonRetryableError: If the error is detected as permanent.
        """
        if exc is not None:
            msg = str(exc).lower()
            if "403" in msg and "subscription" in msg:
                logger.error(f"🛑 [{self.name}] Non-retryable error (subscription required): {exc}")
                raise NonRetryableError(str(exc)) from exc

        self.failure_count += 1
        logger.warning(f"⚠️ [{self.name}] Recorded failure ({self.failure_count}/{self.failure_threshold})")
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            self.last_state_change = time.time()
            logger.error(f"🛑 [{self.name}] Failure threshold reached! Circuit OPEN for {self.cooldown_seconds}s.")