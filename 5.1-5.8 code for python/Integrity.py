
import os
import csv
import random
import statistics
import time

from datetime import datetime, timedelta
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import OperationFailure
from pymongo.write_concern import WriteConcern


load_dotenv("atlas-credentials.env")
uri = os.getenv("MONGODB_URI") or "mongodb://localhost:27017"
client = MongoClient(uri)

db = client["myDatabase"]
COLL = "posts"

print("Connected to MongoDB!")

TAGLIST = ["Animals", "Sports", "Politics", "Gaming", "Art", "Programming", "Drama", "Nature"]
RANDOMRANGE = {
    "AuthorID": 50,
    "Date": 43800,
    "Likes": 100000,
    "Tags": len(TAGLIST)
}

SCALES = [100_000, 250_000, 500_000]
WRITE_CONCERN_SCALE = 100_000
REPS = 3
SEED = 42
BATCH_SIZE = 5000

VALIDATOR = {
    "$jsonSchema": {
        "bsonType": "object",
        "required": ["postID", "AuthorID", "Date", "PostText", "Likes", "Tags"],
        "properties": {
            "postID": {"bsonType": ["int", "long"], "minimum": 0},
            "AuthorID": {"bsonType": ["int", "long"],
                         "minimum": 0, "maximum": RANDOMRANGE["AuthorID"]},
            "Date": {"bsonType": "date"},
            "PostText": {"bsonType": "string", "maxLength": 500},
            "Likes": {"bsonType": ["int", "long"], "minimum": 0},
            "Tags": {"bsonType": "array", "minItems": 1,
                     "items": {"bsonType": "string", "enum": TAGLIST}},
        },
    }
}


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


def load(collection, total_posts):
    """Time a full load. Documents are built before the timer starts."""
    batches = []
    for start in range(0, total_posts, BATCH_SIZE):
        count = min(BATCH_SIZE, total_posts - start)
        batches.append(generate_post_data(start, count))

    start_time = time.time()
    for batch in batches:
        collection.insert_many(batch)
    return time.time() - start_time


def repeat_load(total_posts, validated=False, write_concern=None):
    """Load total_posts REPS times, returning throughput for each run."""
    throughputs = []
    for _ in range(REPS):
        db[COLL].drop()
        if validated:
            db.create_collection(COLL, validator=VALIDATOR,
                                 validationLevel="strict",
                                 validationAction="error")
        collection = (db.get_collection(COLL, write_concern=write_concern)
                      if write_concern else db[COLL])

        random.seed(SEED)                    # identical documents every run
        elapsed = load(collection, total_posts)
        throughputs.append(total_posts / elapsed)
    return throughputs


def run_validation():
    print(f"\n{'=' * 58}")
    print("Experiment 1: schema validation overhead")
    print(f"{'=' * 58}")

    rows = []
    for scale in SCALES:
        print(f"\n  Collection size: {scale:,}")
        result = {"scale": scale, "reps": REPS}

        for label, validated in (("no_validator", False), ("jsonschema_validator", True)):
            throughputs = repeat_load(scale, validated=validated)
            mean = statistics.mean(throughputs)
            sd = statistics.stdev(throughputs) if len(throughputs) > 1 else 0.0
            result[f"{label}_mean"] = round(mean, 2)
            result[f"{label}_sd"] = round(sd, 2)
            print(f"    {label:<22} {mean:>10,.0f} docs/sec  (SD {sd:,.0f})")

        overhead = (1 - result["jsonschema_validator_mean"]
                    / result["no_validator_mean"]) * 100
        result["overhead_percent"] = round(overhead, 2)
        print(f"    {'overhead':<22} {overhead:>10.1f} %")
        rows.append(result)

    return rows


def prove_rejection():
    """Confirm the validator actually rejects a malformed document."""
    print(f"\n{'=' * 58}")
    print("Rejection test")
    print(f"{'=' * 58}")

    db[COLL].drop()
    db.create_collection(COLL, validator=VALIDATOR,
                         validationLevel="strict", validationAction="error")

    bad = {
        "postID": -1,                       # violates minimum
        "AuthorID": 9999,                   # exceeds maximum
        "Date": "not-a-date",               # wrong bsonType
        "PostText": "x",
        "Likes": -5,                        # violates minimum
        "Tags": ["NotARealTag"],            # not in enum
    }

    try:
        db[COLL].insert_one(bad)
        print("  NOT REJECTED — the validator is not being enforced.")
        return False
    except OperationFailure as exc:
        print(f"  Rejected as expected (error code {exc.code}).")
        print("  Violations: negative postID, AuthorID out of range,")
        print("              non-date timestamp, negative Likes, undefined tag.")
        return True

def run_write_concern():
    print(f"\n{'=' * 58}")
    print(f"Experiment 2: write concern ({WRITE_CONCERN_SCALE:,} documents)")
    print(f"{'=' * 58}")

    # w='majority' only means something on a replica set. On a standalone
    # server it is accepted but behaves exactly like w=1, so the comparison
    # would be void. Detect the deployment and say so.
    is_replset = bool(client.admin.command("hello").get("setName"))
    print(f"  Deployment: {'replica set' if is_replset else 'STANDALONE'}")
    if not is_replset:
        print("  NOTE: w=majority skipped. Start mongod with --replSet rs0")
        print("        and run rs.initiate() once to measure it.")

    configs = [
        ("w=0 (unacknowledged)", WriteConcern(w=0)),
        ("w=1 (acknowledged)", WriteConcern(w=1)),
        ("w=1, j=True (journaled)", WriteConcern(w=1, j=True)),
    ]
    if is_replset:
        configs.append(("w=majority", WriteConcern(w="majority")))

    rows = []
    baseline = None
    for label, wc in configs:
        throughputs = repeat_load(WRITE_CONCERN_SCALE, write_concern=wc)
        mean = statistics.mean(throughputs)
        sd = statistics.stdev(throughputs) if len(throughputs) > 1 else 0.0
        if baseline is None:
            baseline = mean

        rows.append({
            "write_concern": label,
            "scale": WRITE_CONCERN_SCALE,
            "reps": REPS,
            "mean_docs_per_sec": round(mean, 2),
            "stddev_docs_per_sec": round(sd, 2),
            "relative_to_w0_percent": round(mean / baseline * 100, 1),
            "replica_set": is_replset,
        })
        print(f"  {label:<26} {mean:>10,.0f} docs/sec  (SD {sd:,.0f})")

    return rows


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"  wrote {path}")


def main():
    validation_rows = run_validation()
    rejected = prove_rejection()
    wc_rows = run_write_concern()

    for row in validation_rows:
        row["invalid_document_rejected"] = rejected

    print(f"\n{'=' * 58}")
    print("Writing results")
    print(f"{'=' * 58}")
    write_csv("validation_overhead.csv", validation_rows)
    write_csv("write_concern.csv", wc_rows)

    db[COLL].drop()
    client.close()
    print("\nDone.")


if __name__ == "__main__":
    main()