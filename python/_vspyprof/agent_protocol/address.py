"""Where the agent finds its collector."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentAddress:
    """Where the agent connects to and the one-time token it presents: ``host:port:token``."""

    host: str
    port: int
    token: str

    @classmethod
    def parse(cls, text: str) -> AgentAddress:
        """Read ``host:port:token``. Raises ``ValueError`` if ``text`` has another shape."""
        try:
            host, port, token = text.rsplit(":", 2)
            return cls(host, int(port), token)
        except ValueError:
            raise ValueError(f"malformed agent address {text!r}; expected host:port:token") from None

    def __str__(self) -> str:
        return f"{self.host}:{self.port}:{self.token}"
