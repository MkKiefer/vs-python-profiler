"""CPU-heavy demo: a few hot functions, one worker thread."""
import threading
import time


def fib(n):
    return n if n < 2 else fib(n - 1) + fib(n - 2)


def parse_rows(n):
    return [line.split(",") for line in ("a,b,c,%d" % i for i in range(n))]


def checksum(rows):
    total = 0
    for row in rows:
        for cell in row:
            total = (total * 31 + hash(cell)) & 0xFFFFFFFF
    return total


class Worker:
    def run(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            checksum(parse_rows(20_000))


def main(seconds=float(__import__("sys").argv[1]) if len(__import__("sys").argv) > 1 else 6.0):
    t = threading.Thread(target=Worker().run, args=(seconds,), name="checksum-worker")
    t.start()
    end = time.time() + seconds
    while time.time() < end:
        fib(22)
        time.sleep(0.002)
    t.join()
    print("done")


if __name__ == "__main__":
    main()
