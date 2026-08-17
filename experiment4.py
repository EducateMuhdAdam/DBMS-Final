
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

#-----===== Experiment 4: Aggregation =====-----

def popular_tags():

    print("===== Experiment 4A: Popular Tags =====")

    start_time = time.perf_counter()

    pipeline = [

        # Turn the Tags array into individual documents
        {
            "$unwind": "$Tags"
        },

        # Group by tag
        {
            "$group": {
                "_id": "$Tags",
                "total_likes": {
                    "$sum": "$Likes"
                },
                "post_count": {
                    "$sum": 1
                }
            }
        },

        # Most likes first
        {
            "$sort": {
                "total_likes": -1
            }
        }
    ]

    results = posts_collection.aggregate(pipeline)

    for result in results:
        print(
            f"{result['_id']}: "
            f"{result['post_count']:,} posts, "
            f"{result['total_likes']:,} total likes"
        )

    end_time = time.perf_counter()

    print(
        f"\nAggregation time: "
        f"{end_time - start_time:.6f} seconds"
    )

    print()

def popular_authors():

    print("===== Experiment 4B: Most Active Authors =====")

    start_time = time.perf_counter()

    pipeline = [

        {
            "$group": {
                "_id": "$AuthorID",
                "post_count": {
                    "$sum": 1
                },
                "total_likes": {
                    "$sum": "$Likes"
                }
            }
        },

        {
            "$sort": {
                "post_count": -1
            }
        },

        {
            "$limit": 10
        }
    ]

    results = posts_collection.aggregate(pipeline)

    for result in results:
        print(
            f"Author {result['_id']}: "
            f"{result['post_count']:,} posts, "
            f"{result['total_likes']:,} total likes"
        )

    end_time = time.perf_counter()

    print(
        f"\nAggregation time: "
        f"{end_time - start_time:.6f} seconds"
    )

    print()

def average_likes():

    print("===== Experiment 4C: Average Likes =====")

    start_time = time.perf_counter()

    pipeline = [
        {
            "$group": {
                "_id": None,
                "average_likes": {
                    "$avg": "$Likes"
                },
                "maximum_likes": {
                    "$max": "$Likes"
                },
                "minimum_likes": {
                    "$min": "$Likes"
                },
                "total_posts": {
                    "$sum": 1
                }
            }
        }
    ]

    result = list(posts_collection.aggregate(pipeline))

    end_time = time.perf_counter()

    if result:
        data = result[0]

        print(f"Total posts: {data['total_posts']:,}")
        print(f"Average likes: {data['average_likes']:.2f}")
        print(f"Maximum likes: {data['maximum_likes']:,}")
        print(f"Minimum likes: {data['minimum_likes']:,}")

    print(
        f"Aggregation time: "
        f"{end_time - start_time:.6f} seconds"
    )

    print()

def main():
    popular_authors()
    popular_tags()
    average_likes()

if __name__ == "__main__":
    main()