import os
import random
import time

from datetime import datetime, timedelta
from random import sample
from dotenv import load_dotenv
from pymongo import MongoClient


load_dotenv("atlas-credentials.env")

uri = os.getenv("MONGODB_URI")
print(uri)
client = MongoClient(uri)

db = client["myDatabase"]
posts_collection = db["posts"]

print("Connected to MongoDB!")

DATA = ["PostID", "AuthorID", "Date", "PostText", "Likes", "Tags"]
TAGLIST = ["Animals", "Sports", "Politics", "Gaming", "Art", "Programming", "Drama", "Nature"]
RANDOMRANGE = {
    "AuthorID": 50,
    "Date": 43800,
    "Likes": 100000,
    "Tags": len(TAGLIST)
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

def insert_data(total_posts, batch_size=5000):
    start_time = time.time()
    for start in range(0, total_posts, batch_size):
        count = min(batch_size, total_posts - start)
        posts = generate_post_data(start, count)
        posts_collection.insert_many(posts)
        inserted = start + count
        print(f"Inserted {inserted:,} / {total_posts:,}")

    end_time = time.time()
    elapsed = end_time - start_time
    print(f"\nInsertion completed!")
    print(f"Documents inserted: {total_posts:,}")
    print(f"Time taken: {elapsed:.2f} seconds")
    print(f"Documents/second: {total_posts / elapsed:.2f}")

def main():
    insert_data(10)

if __name__ == "__main__":
    main()