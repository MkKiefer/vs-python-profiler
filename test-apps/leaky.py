"""Memory demo: an unbounded cache that keeps growing."""
import sys
import time

_cache = {}


class Record:
    def __init__(self, i):
        self.i = i
        self.payload = "x" * 512
        self.tags = [str(i)] * 8


def handle_request(i):
    _cache[i] = Record(i)          # leak: never evicted
    tmp = [bytes(256) for _ in range(20)]  # short-lived garbage
    return len(tmp)


def main(seconds):
    end = time.time() + seconds
    i = 0
    while time.time() < end:
        handle_request(i)
        i += 1
        if i % 500 == 0:
            time.sleep(0.01)
    print("records", len(_cache))


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 8.0)
