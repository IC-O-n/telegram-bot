import json
import os

DATA_FILE = "user_data.json"

def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def get_user(user_id):
    data = load_data()
    return data.get(str(user_id), {})

def update_user(user_id, new_data):
    data = load_data()
    user_id_str = str(user_id)
    if user_id_str not in data:
        data[user_id_str] = {}
    data[user_id_str].update(new_data)
    save_data(data)
