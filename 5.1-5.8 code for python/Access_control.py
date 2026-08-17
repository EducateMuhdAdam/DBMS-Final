
import csv
import random
import sys
import time

from datetime import datetime, timedelta
from pymongo import MongoClient
from pymongo.errors import OperationFailure, ConnectionFailure


# Edit this, or pass it as the first command line argument.
ADMIN_URI = "mongodb://admin:ChangeMe123@localhost:27017/?authSource=admin"

DB_NAME = "myDatabase"
COLL = "posts"
SECOND_COLL = "private_notes"      # used to test collection-scoped roles
UNAUTHORIZED = 13                  # MongoDB error code for an authorisation failure

TAGLIST = ["Animals", "Sports", "Politics", "Gaming", "Art", "Programming", "Drama", "Nature"]
CUSTOM_ROLE = "postsReadOnly"
HANDSHAKE_REPS = 10

# Four principals, from narrowest to broadest privilege.
TEST_USERS = [
    ("bench_reader",  "ReaderPass123",  ["read"],       "read (built-in)"),
    ("bench_writer",  "WriterPass123",  ["readWrite"],  "readWrite (built-in)"),
    ("bench_analyst", "AnalystPass123", [CUSTOM_ROLE],  "postsReadOnly (custom)"),
    ("bench_dbadmin", "AdminPass123",   ["dbAdmin"],    "dbAdmin (built-in)"),
]


def sample_posts(count):
    """A small amount of data so that read operations return something."""
    posts = []
    for i in range(count):
        posts.append({
            "postID": i,
            "AuthorID": random.randint(0, 50),
            "Date": datetime.now() - timedelta(minutes=random.randint(0, 43800)),
            "PostText": "Post Text Here",
            "Likes": random.randint(0, 100000),
            "Tags": random.sample(TAGLIST, random.randint(1, 4)),
        })
    return posts


def provision(admin_client):
    """Create the custom role and the four test users."""
    db = admin_client[DB_NAME]

    # A role granting find on the posts collection only — nothing else in the
    # database. If MongoDB enforces at collection level, bench_analyst will be
    # refused when it reads a different collection.
    try:
        db.command("dropRole", CUSTOM_ROLE)
    except OperationFailure:
        pass
    db.command("createRole", CUSTOM_ROLE,
               privileges=[{
                   "resource": {"db": DB_NAME, "collection": COLL},
                   "actions": ["find"],
               }],
               roles=[])

    for username, password, roles, _ in TEST_USERS:
        try:
            db.command("dropUser", username)
        except OperationFailure:
            pass
        db.command("createUser", username, pwd=password, roles=roles)

    print(f"  Provisioned {len(TEST_USERS)} users and 1 custom role.")


def teardown(admin_client):
    db = admin_client[DB_NAME]
    for username, *_ in TEST_USERS:
        try:
            db.command("dropUser", username)
        except OperationFailure:
            pass
    try:
        db.command("dropRole", CUSTOM_ROLE)
    except OperationFailure:
        pass
    try:
        db.command("dropUser", "escalated")
    except OperationFailure:
        pass
    print("  Removed test users and custom role.")


def operations(db):
    """Nine operations, ordered from least to most privileged."""
    return [
        ("read posts",                lambda: list(db[COLL].find().limit(1))),
        ("count posts",               lambda: db[COLL].count_documents({}, limit=1)),
        ("read other collection",     lambda: list(db[SECOND_COLL].find().limit(1))),
        ("insert into posts",         lambda: db[COLL].insert_one({"probe": True})),
        ("update posts",              lambda: db[COLL].update_one({"probe": True},
                                                                  {"$set": {"probe": False}})),
        ("delete from posts",         lambda: db[COLL].delete_one({"probe": False})),
        ("create index",              lambda: db[COLL].create_index("probe", name="probe_idx")),
        ("list collections",          lambda: db.list_collection_names()),
        ("create user (escalation)",  lambda: db.command("createUser", "escalated",
                                                         pwd="Escalated123",
                                                         roles=["dbOwner"])),
    ]


def measure_handshake(uri):
    """Time connection plus SCRAM authentication, repeated."""
    timings = []
    for _ in range(HANDSHAKE_REPS):
        start = time.perf_counter()
        probe = MongoClient(uri, serverSelectionTimeoutMS=5000)
        probe.admin.command("ping")
        timings.append((time.perf_counter() - start) * 1000)
        probe.close()
    return timings


def main():
    admin_uri = sys.argv[1] if len(sys.argv) > 1 else ADMIN_URI

    try:
        admin_client = MongoClient(admin_uri, serverSelectionTimeoutMS=5000)
        admin_client.admin.command("ping")
    except (ConnectionFailure, OperationFailure) as exc:
        print(f"Could not connect as administrator: {exc}")
        print("Check that mongod is running with --auth and that the URI is correct.")
        print("See the setup notes at the bottom of this file.")
        return

    print("Connected to MongoDB as administrator!")

    # Seed both collections so that reads have something to return.
    adb = admin_client[DB_NAME]
    adb[COLL].drop()
    adb[COLL].insert_many(sample_posts(100))
    adb[SECOND_COLL].drop()
    adb[SECOND_COLL].insert_one({"note": "confidential"})

    provision(admin_client)

    host = admin_uri.split("@")[-1].split("/")[0]
    matrix_rows, auth_rows = [], []

    for username, password, _, role_label in TEST_USERS:
        uri = f"mongodb://{username}:{password}@{host}/?authSource={DB_NAME}"

        timings = measure_handshake(uri)
        auth_rows.append({
            "user": username,
            "role": role_label,
            "reps": HANDSHAKE_REPS,
            "mean_handshake_ms": round(sum(timings) / len(timings), 3),
            "min_handshake_ms": round(min(timings), 3),
            "max_handshake_ms": round(max(timings), 3),
        })

        client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        db = client[DB_NAME]
        print(f"\n  {username} — {role_label}")

        for op_name, op in operations(db):
            try:
                op()
                result, code, message = "ALLOWED", "", ""
            except OperationFailure as exc:
                code = exc.code or ""
                result = "DENIED" if code == UNAUTHORIZED else f"FAILED ({code})"
                message = str(exc).split(",")[0][:110]
            except Exception as exc:                       # noqa: BLE001
                result, code, message = "ERROR", "", str(exc)[:110]

            matrix_rows.append({
                "user": username,
                "role": role_label,
                "operation": op_name,
                "result": result,
                "error_code": code,
                "error_message": message,
            })
            print(f"    {op_name:<26} {result}")

        client.close()

    # Remove anything a successful write left behind.
    adb[COLL].delete_many({"probe": {"$exists": True}})
    try:
        adb[COLL].drop_index("probe_idx")
    except OperationFailure:
        pass

    teardown(admin_client)

    for path, rows in (("access_control_matrix.csv", matrix_rows),
                       ("auth_overhead.csv", auth_rows)):
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"  wrote {path}")

    adb[COLL].drop()
    adb[SECOND_COLL].drop()
    admin_client.close()
    print("\nDone. Screenshot the DENIED lines above as evidence.")


if __name__ == "__main__":
    main()

