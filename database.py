import os
import random
from datetime import datetime, timedelta
from random import sample
from dotenv import load_dotenv
from pymongo import MongoClient


DATA = ["PostID", "AuthorID", "Date", "PostText", "Likes", "Tags"]
TAGLIST = ["Animals", "Sports", "Politics", "Gaming", "Art", "Programming", "Drama", "Nature"]
RANDOMRANGE = {
    "AuthorID": 50,
    "Date": 43800,
    "Likes": 100000,
    "Tags": len(TAGLIST)
}
def generate_tags():
    indexes = random.sample(range(len(TAGLIST)), random.randint(0, len(TAGLIST)))
    return [TAGLIST[i] for i in indexes]

def generate_post_data(count: int):
    posts = []
    for i in range(count):
        posts.append({
            "postID": i,
            "AuthorID": random.randint(0, RANDOMRANGE["AuthorID"]),
            "Date": datetime.now() - timedelta(minutes=random.randint(0, RANDOMRANGE["Date"])),
            "PostText": "Post Text Here",
            "Likes": random.randint(0, RANDOMRANGE["Likes"]),
            "Tags": generate_tags()
        })
    return posts

def main():
    load_dotenv()

    uri = os.getenv("MONGODB_URI")

    client = MongoClient(uri)

    db = client["myDatabase"]
    posts_collection = db["posts"]

    print("Connected to MongoDB!")

    posts = generate_post_data(1000)

    posts_collection.insert_many(posts)

    print("Inserted", len(posts), "posts!")

if __name__ == "__main__":
    main()