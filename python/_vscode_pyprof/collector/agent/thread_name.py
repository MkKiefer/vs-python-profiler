"""The name of a thread of the target, as the agent reports it."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ThreadName:
    ident: int | None
    native_id: int | None
    name: str

    @classmethod
    def list_from_wire(cls, raw_threads: list[object]) -> list[ThreadName]:
        """Read ``[[ident, native_id, name], ...]``; entries of another shape are skipped."""
        threads: list[ThreadName] = []
        for raw in raw_threads:
            if isinstance(raw, list) and len(raw) == 3:
                ident, native_id, name = raw
                threads.append(
                    cls(
                        ident=ident if isinstance(ident, int) else None,
                        native_id=native_id if isinstance(native_id, int) else None,
                        name=str(name),
                    )
                )
        return threads

    def ids(self) -> list[int]:
        """Every id samples may carry for this thread (which one depends on the platform)."""
        return [thread_id for thread_id in (self.native_id, self.ident) if thread_id is not None]
