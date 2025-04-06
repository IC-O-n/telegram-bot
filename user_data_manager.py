import json
import os

DATA_FILE = "users.json"

user_storage = {}

def load_users():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_users(users):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, ensure_ascii=False, indent=4)

def get_user(user_id):
    return user_storage.get(user_id, {})

def update_user(user_id, updates: dict):
    user_storage[user_id] = {**user_storage.get(user_id, {}), **updates}














               )
