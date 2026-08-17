from pymongo import MongoClient
c = MongoClient("mongodb://localhost:27018")
c.admin.command("createUser", "admin", pwd="ChangeMe123",
                roles=[{"role": "root", "db": "admin"}])
print("admin created")