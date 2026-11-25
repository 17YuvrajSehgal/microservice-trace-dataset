"""One log line, whatever its source."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LogRecord:
    """A log line after its source profile has been applied.

    t       seconds since the epoch, on the TRACE clock (the profile's offset already added);
            None when the line carries no time (a continuation line)
    entity  who wrote it: a container name, a process name, a card id
    kind    what an entity is: container | process | thread | host
    msg     the text, without the source's own prefix (docker timestamp, syslog header)
    src     the file it came from, relative to the run directory
    """

    t: float | None
    entity: str
    kind: str
    msg: str
    src: str
