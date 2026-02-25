"""
CommandBusPort — abstract interface for sending commands to the Kafka command bus.

Unlike EventBusPort (fire-and-forget domain events), CommandBusPort sends
*instructions* that a worker is expected to act on.  The return value is the
Kafka partition offset, which the CLI displays as confirmation to the user.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class CommandBusPort(Protocol):
    """Send write commands to the listing.commands Kafka topic."""

    def send_command(self, action: str, payload: dict[str, Any]) -> int:
        """
        Publish a command message and return the Kafka partition offset.

        Args:
            action:  One of the ``CommandAction`` enum values (e.g. ``"create"``).
            payload: JSON-serialisable dict with command-specific data.

        Returns:
            The Kafka partition offset of the produced record (for user feedback).

        Raises:
            RuntimeError: If Kafka is unavailable or the send times out.
        """
        ...  # pragma: no cover
