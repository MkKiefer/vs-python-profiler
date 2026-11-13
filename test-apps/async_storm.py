"""asyncio demo: many tasks, one blocking callback, a never-awaited coroutine."""
import asyncio
import sys
import time


async def fetch_user(i):
    await asyncio.sleep(0.01 * (i % 5))
    return {"id": i}


async def slow_db_query():
    time.sleep(0.15)  # BUG: blocks the event loop
    await asyncio.sleep(0)


async def worker(name, n):
    for i in range(n):
        await fetch_user(i)
        if i % 20 == 0:
            await slow_db_query()


async def main(seconds):
    end = time.time() + seconds
    while time.time() < end:
        tasks = [asyncio.create_task(worker(f"w{i}", 40), name=f"worker-{i}") for i in range(8)]
        await asyncio.gather(*tasks)
        fetch_user(0)  # BUG: never awaited


if __name__ == "__main__":
    asyncio.run(main(float(sys.argv[1]) if len(sys.argv) > 1 else 8.0))
