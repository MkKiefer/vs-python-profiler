"""Strings that Tachyon read from the target's memory."""


class CorruptTextError(ValueError):
    """A string read from the target is malformed: the read raced with the target changing it.

    A ``ValueError``, so the sampler counts it like any other torn read (a discarded sample).
    """


class RemoteText:
    """Checks strings read from the target before the store keeps them.

    A torn read can yield a ``str`` whose characters are not valid code points.
    CPython only notices when a character is taken out of it, which may happen
    much later (classifying a file, encoding a delta, saving the profile), and
    then raises ``SystemError``. One bad sample must not stop the sampler or
    break the profile, so such a string is rejected where it enters the store.
    """

    @staticmethod
    def checked(text: str) -> str:
        """``text`` itself; raises ``CorruptTextError`` if one of its characters is not a valid code point."""
        try:
            max(text, default="")  # takes every character out of the string, which validates it
        except SystemError as error:
            raise CorruptTextError(f"malformed string read from the target: {error}") from error
        return text
