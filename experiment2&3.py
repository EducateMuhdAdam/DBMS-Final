import os
import time

from dotenv import load_dotenv
from pymongo import MongoClient


# =========================
# MongoDB Connection
# =========================

load_dotenv("atlas-credentials.env")

uri = os.getenv("MONGODB_URI")
print(uri)
client = MongoClient(uri)

db = client["myDatabase"]
posts_collection = db["posts"]

print("Connected to MongoDB!")

QUERY_FILTER = {"Likes": {"$gt": 95000}}

TRIALS = 7  # run each timed query this many times; report the median to
            # smooth out network/connection jitter (see explanation below)

def run_query():

    start_time = time.perf_counter()

    count = posts_collection.count_documents(QUERY_FILTER)

    end_time = time.perf_counter()

    elapsed = end_time - start_time

    return count, elapsed

def run_query_trials(trials=TRIALS):
    timings = []
    count = None
    for _ in range(trials):
        count, elapsed = run_query()
        timings.append(elapsed)
    return count, timings

def median(values):
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 0:
        return (s[mid - 1] + s[mid]) / 2
    return s[mid]

def get_plan_stages(plan_node):
    stages = []
    node = plan_node
    while node:
        if "stage" in node:
            stages.append(node["stage"])
        node = node.get("inputStage")
    return stages

def explain_query():
    """Runs the same query through explain(), with executionStats
    verbosity, and returns the key metrics needed to show WHY a query
    was fast or slow -- not just that it was."""
    explain_result = db.command(
        "explain",
        {"find": "posts", "filter": QUERY_FILTER},
        verbosity="executionStats"
    )

    winning_plan = explain_result["queryPlanner"]["winningPlan"]
    exec_stats = explain_result["executionStats"]

    return {
        "stages": get_plan_stages(winning_plan),
        "executionTimeMillis": exec_stats["executionTimeMillis"],
        "totalDocsExamined": exec_stats["totalDocsExamined"],
        "totalKeysExamined": exec_stats["totalKeysExamined"],
        "nReturned": exec_stats["nReturned"],
    }

def print_explain(label):
    info = explain_query()
    print(f"\n{label} -- query plan:")
    print(f"  Stages: {' -> '.join(info['stages'])}")
    print(f"  Documents examined: {info['totalDocsExamined']:,}")
    print(f"  Index keys examined: {info['totalKeysExamined']:,}")
    print(f"  Documents returned: {info['nReturned']:,}")
    print(f"  Engine-reported execution time: {info['executionTimeMillis']} ms")
    return info

# -----===== Experiment 2: Query without indexing =====-----

def experiment_2():
    print("===== Experiment 2 =====")
    #Remove Indexes
    try:
        posts_collection.drop_indexes()
    except Exception:
        pass

    print("\nWithout index:")

    count, timings = run_query_trials()
    before_index = median(timings)

    print(f"Posts found: {count:,}")
    print(f"Query times over {TRIALS} trials: {[f'{t:.4f}' for t in timings]}")
    print(f"Median query time: {before_index:.6f} seconds")

    explain_before = print_explain("Experiment 2 (no index)")

    return before_index, explain_before

# -----===== Experiment 3: Query with indexing =====-----

def experiment_3():
    print("===== Experiment 3 =====")

    # Create index
    print("\nCreating index on Likes")

    posts_collection.create_index("Likes")

    print("\nWith index:")

    count, timings = run_query_trials()
    after_index = median(timings)

    print(f"Posts found: {count:,}")
    print(f"Query times over {TRIALS} trials: {[f'{t:.4f}' for t in timings]}")
    print(f"Median query time: {after_index:.6f} seconds")

    explain_after = print_explain("Experiment 3 (with index)")

    return after_index, explain_after

def main():
    bfr, explain_before = experiment_2()
    aft, explain_after = experiment_3()

    improvement = ((bfr - aft) / bfr) * 100
    print(f"\nPerformance improvement (median wall-clock, count_documents): {improvement:.2f}%")

    print("\n===== Explain summary =====")
    print(f"{'Metric':<28}{'No index':<16}{'With index'}")
    print(f"{'Plan stages':<28}{' -> '.join(explain_before['stages']):<16}{' -> '.join(explain_after['stages'])}")
    print(f"{'Docs examined':<28}{explain_before['totalDocsExamined']:<16,}{explain_after['totalDocsExamined']:,}")
    print(f"{'Index keys examined':<28}{explain_before['totalKeysExamined']:<16,}{explain_after['totalKeysExamined']:,}")
    print(f"{'Engine exec time (ms)':<28}{explain_before['executionTimeMillis']:<16}{explain_after['executionTimeMillis']}")
    
if __name__ == "__main__":
    main()
