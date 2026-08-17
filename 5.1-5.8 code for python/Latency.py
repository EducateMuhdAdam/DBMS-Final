

import os
import csv
import random
import statistics
import time

from datetime import datetime, timedelta
from dotenv import load_dotenv
from pymongo import MongoClient, ASCENDING, DESCENDING

import psutil


load_dotenv("atlas-credentials.env")
uri = os.getenv("MONGODB_URI") or "mongodb://localhost:27017"
client = MongoClient(uri)

db = client["myDatabase"]
posts_collection = db["posts"]

print("Connected to MongoDB!")

TAGLIST = ["Animals", "Sports", "Politics", "Gaming", "Art", "Programming", "Drama", "Nature"]
RANDOMRANGE = {
    "AuthorID": 50,
    "Date": 43800,
    "Likes": 100000,
    "Tags": len(TAGLIST)
}

SCALES = [100_000, 250_000, 500_000]
QUERY_REPS = 30        # timed repetitions per query
WARMUP_REPS = 5        # discarded before timing begins
SEED = 42
BATCH_SIZE = 5000

INDEXES = [
    ("idx_postID", [("postID", ASCENDING)]),
    ("idx_date", [("Date", DESCENDING)]),
    ("idx_tags", [("Tags", ASCENDING)]),
    ("idx_author_likes", [("AuthorID", ASCENDING), ("Likes", ASCENDING)]),
]


def generate_tags():
    indexes = random.sample(range(len(TAGLIST)), random.randint(1, len(TAGLIST)))
    return [TAGLIST[i] for i in indexes]


def generate_post_data(start_id: int, count: int):
    posts = []
    for i in range(count):
        posts.append({
            "postID": start_id + i,
            "AuthorID": random.randint(0, RANDOMRANGE["AuthorID"]),
            "Date": datetime.now() - timedelta(minutes=random.randint(0, RANDOMRANGE["Date"])),
            "PostText": "Post Text Here",
            "Likes": random.randint(0, RANDOMRANGE["Likes"]),
            "Tags": generate_tags()
        })
    return posts


def load(total_posts):
    posts_collection.drop()
    random.seed(SEED)
    for start in range(0, total_posts, BATCH_SIZE):
        count = min(BATCH_SIZE, total_posts - start)
        posts_collection.insert_many(generate_post_data(start, count))


def get_server_process():
   
    pid = client.admin.command("serverStatus").get("pid")
    if pid is None:
        return None
    try:
        return psutil.Process(int(pid))
    except (psutil.NoSuchProcess, ValueError):
        print("  WARNING: the server process is not on this machine.")
        print("  CPU and memory cannot be measured for a remote server.")
        return None


class ResourceMonitor:
 

    def __init__(self, server_proc):
        self.server = server_proc
        self.client_proc = psutil.Process(os.getpid())
        self.cores = psutil.cpu_count()

    def start(self):
        if self.server:
            self.server.cpu_percent()          # prime
        self.client_proc.cpu_percent()
        self.wall_start = time.perf_counter()

    def stop(self):
        elapsed = time.perf_counter() - self.wall_start
        result = {
            "elapsed_s": round(elapsed, 3),
            "cpu_cores_available": self.cores,
            "client_cpu_percent": round(self.client_proc.cpu_percent(), 2),
        }
        if self.server:
            cpu = self.server.cpu_percent()
            mem = self.server.memory_info()
            result.update({
                "server_cpu_percent": round(cpu, 2),
                "server_cpu_normalised": round(cpu / self.cores, 2),
                "server_rss_mb": round(mem.rss / 1048576, 2),
            })
        else:
            result.update({"server_cpu_percent": "", "server_cpu_normalised": "",
                           "server_rss_mb": ""})

        # The server's own view of its memory, for comparison with the value
        # the operating system reports.
        try:
            status = client.admin.command("serverStatus")
            result["server_reported_resident_mb"] = status.get("mem", {}).get("resident", "")
            result["server_reported_virtual_mb"] = status.get("mem", {}).get("virtual", "")
        except Exception:                                   # noqa: BLE001
            result["server_reported_resident_mb"] = ""
            result["server_reported_virtual_mb"] = ""
        return result


def build_queries(scale):
    cutoff = datetime.now() - timedelta(days=7)

    def q1():
        list(posts_collection.find({"postID": random.randint(0, scale - 1)}))

    def q2():
        list(posts_collection.find({"Date": {"$gte": cutoff}})
             .sort("Date", DESCENDING).limit(20))

    def q3():
        list(posts_collection.find({"Tags": "Nature"}).limit(100))

    def q4():
        list(posts_collection.aggregate([
            {"$group": {"_id": "$AuthorID", "totalLikes": {"$sum": "$Likes"}}},
            {"$sort": {"totalLikes": -1}},
            {"$limit": 10},
        ]))

    return [
        ("Q1 point lookup by postID", q1),
        ("Q2 recent posts, sorted, limit 20", q2),
        ("Q3 posts by tag, limit 100", q3),
        ("Q4 aggregation: top authors by likes", q4),
    ]


def time_query(fn):
    """Return latencies in milliseconds, warm-up runs discarded."""
    for _ in range(WARMUP_REPS):
        fn()
    latencies = []
    for _ in range(QUERY_REPS):
        start = time.perf_counter()
        fn()
        latencies.append((time.perf_counter() - start) * 1000)
    return latencies


def percentile(values, pct):
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1,
                     int(round(pct / 100 * len(ordered) + 0.5)) - 1))
    return ordered[idx]


def main():
    server = get_server_process()
    if server:
        print(f"Monitoring mongod (PID {server.pid}) on "
              f"{psutil.cpu_count()} logical cores.")

    monitor = ResourceMonitor(server)
    latency_rows, resource_rows = [], []

    for scale in SCALES:
        print(f"\n{'=' * 62}")
        print(f"Collection size: {scale:,} documents")
        print(f"{'=' * 62}")

        print("  Loading...")
        load(scale)

        for indexed in (False, True):
            if indexed:
                print("  Building indexes...")
                for name, keys in INDEXES:
                    posts_collection.create_index(keys, name=name)

            label = "indexed" if indexed else "unindexed"
            print(f"  Running queries ({label})...")

            for qname, fn in build_queries(scale):
                monitor.start()
                latencies = time_query(fn)
                usage = monitor.stop()

                row = {
                    "scale": scale,
                    "indexed": indexed,
                    "query": qname,
                    "reps": QUERY_REPS,
                    "mean_ms": round(statistics.mean(latencies), 3),
                    "p50_ms": round(percentile(latencies, 50), 3),
                    "p95_ms": round(percentile(latencies, 95), 3),
                    "stddev_ms": round(statistics.stdev(latencies), 3),
                    "min_ms": round(min(latencies), 3),
                    "max_ms": round(max(latencies), 3),
                }
                latency_rows.append(row)

                usage.update({"scale": scale, "indexed": indexed, "query": qname})
                resource_rows.append(usage)

                print(f"    {qname:<38} {row['mean_ms']:>9.2f} ms   "
                      f"p95 {row['p95_ms']:>9.2f} ms   "
                      f"CPU {usage['server_cpu_normalised'] or 'n/a'}%")

        for name, _ in INDEXES:
            try:
                posts_collection.drop_index(name)
            except Exception:                               # noqa: BLE001
                pass

    print(f"\n{'=' * 62}")
    print("Writing results")
    print(f"{'=' * 62}")
    for path, rows in (("query_latency.csv", latency_rows),
                       ("resource_usage.csv", resource_rows)):
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"  wrote {path}  ({len(rows)} rows)")

    posts_collection.drop()
    client.close()
    print("\nDone.")


if __name__ == "__main__":
    main()