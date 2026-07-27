"""Seed extra non-admin users for RBAC negative tests (Task 4).

Inserts three users (site_engineer, pm, purchase) with matching sessions.
Prints their tokens on stdout as JSON.
"""
import asyncio, os, uuid, json
from datetime import datetime, timezone, timedelta
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv("/app/backend/.env")


async def main():
    c = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = c[os.environ["DB_NAME"]]
    now = datetime.now(timezone.utc)
    out = {}
    for role in ("site_engineer", "pm", "purchase"):
        uid = f"user_task4_{role}"
        user = {
            "user_id": uid,
            "email": f"{role}@vasuinfosec.com",
            "name": role.title(),
            "role": role,
            "roles": [role],
            "is_active": True,
            "created_at": now,
        }
        await db.users.update_one({"user_id": uid}, {"$set": user}, upsert=True)
        tok = f"dev_task4_{role}_" + uuid.uuid4().hex[:12]
        await db.user_sessions.update_one(
            {"session_token": tok},
            {
                "$set": {
                    "session_token": tok,
                    "user_id": uid,
                    "created_at": now,
                    "expires_at": now + timedelta(days=7),
                }
            },
            upsert=True,
        )
        out[role] = tok
    print(json.dumps(out))


if __name__ == "__main__":
    asyncio.run(main())
