import requests
import time
import json
from playwright.sync_api import sync_playwright

from flask import Flask
from threading import Thread

app = Flask('')

@app.route('/')
def home():
    return "Bot running"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

BOT_TOKEN = "7832594298:AAGaJtsNHMQ1-CjzSCfa45mdyaWwiQSNgqc"
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
USERS_FILE = "users.json"

# ---------------- LOAD / SAVE ---------------- #

def load_users():
    try:
        with open(USERS_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_users(data):
    with open(USERS_FILE, "w") as f:
        json.dump(data, f)

# ---------------- NORMALIZE USER ---------------- #

def normalize_user(user):
    user.setdefault("categories", [])
    user.setdefault("subcategories", [])
    user.setdefault("custom", [])
    user.setdefault("alerts", {})
    user.setdefault("setup_done", False)
    user.setdefault("mode", None)
    user.setdefault("pincode", None)
    return user

# ---------------- UI ---------------- #

def main_menu():
    return {
        "keyboard": [
            ["➕ Add Category", "🔍 Add Product"],
            ["📊 Status", "🗑 Delete Product"],
            ["❌ Stop All"]
        ],
        "resize_keyboard": True
    }

CATEGORIES = {
    "chicken": ["breast", "curry_cut", "boneless"],
    "milk": ["toned", "full_cream"],
    "eggs": ["white_eggs", "brown_eggs"],
    "vegetables": ["onion", "tomato", "potato"]
}

# ---------------- TELEGRAM ---------------- #

def send_message(chat_id, text, keyboard=None):
    payload = {
        "chat_id": chat_id,
        "text": text
    }
    if keyboard:
        payload["reply_markup"] = keyboard

    requests.post(f"{BASE_URL}/sendMessage", json=payload)

# ---------------- PLAYWRIGHT FETCH ---------------- #

def fetch_data(query, pincode):
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            page.goto("https://quickcompare.in/")
            page.fill("input", query)
            page.wait_for_timeout(5000)

            data = page.evaluate("window.__NUXT__")
            browser.close()

            return data if data else []

    except Exception as e:
        print("Error:", e)
        return []

# ---------------- PRICE LOGIC ---------------- #

price_history = {}

def process_data(user_id, chat_id, query, data):
    if not data:
        return

    # simulate extraction (adjust based on real structure)
    try:
        products = data["data"]["data"]
    except:
        return

    for product in products[:5]:
        name = product.get("name", "Unknown")
        price = float(product.get("price", 0))
        link = product.get("url", "")

        key = f"{user_id}_{name}"

        if key in price_history:
            old_price = price_history[key]

            if old_price > 0:
                drop = ((old_price - price) / old_price) * 100

                if drop >= 10:  # ✅ 10% threshold
                    send_message(
                        chat_id,
                        f"🔥 PRICE DROP ALERT\n\n{name}\n⬇️ {round(drop,1)}%\n₹{old_price} → ₹{price}\n{link}"
                    )

        price_history[key] = price

# ---------------- TRACKER ---------------- #

def run_tracker(users):
    for user_id, user in users.items():

        user = normalize_user(user)

        if not user["setup_done"]:
            continue

        queries = []

        queries += user["categories"]
        queries += [s.replace("_", " ") for s in user["subcategories"]]
        queries += user["custom"]

        for q in queries:
            data = fetch_data(q, user["pincode"])
            process_data(user_id, user_id, q, data)

# ---------------- HANDLER ---------------- #

def handle_message(msg, users):
    chat_id = str(msg["chat"]["id"])
    text = msg.get("text", "").lower()

    if chat_id not in users:
        users[chat_id] = {}

    user = normalize_user(users[chat_id])

    # START
    if text == "/start":
        send_message(chat_id, "Enter your pincode:")
        user["mode"] = "pincode"
        return

    # PINCODE
    if user["mode"] == "pincode":
        user["pincode"] = text
        user["setup_done"] = True
        user["mode"] = None

        send_message(chat_id, "✅ Setup done!", main_menu())
        return

    # ADD CATEGORY
    if text == "➕ add category":
        keyboard = {"keyboard": [[c] for c in CATEGORIES], "resize_keyboard": True}
        user["mode"] = "category"
        send_message(chat_id, "Select category:", keyboard)
        return

    if user["mode"] == "category":
        if text in CATEGORIES:
            keyboard = {"keyboard": [[s] for s in CATEGORIES[text]], "resize_keyboard": True}
            user["current_category"] = text
            user["mode"] = "subcategory"
            send_message(chat_id, "Select subcategory:", keyboard)
        return

    if user["mode"] == "subcategory":
        cat = user.get("current_category")

        if cat:
            user["subcategories"].append(f"{cat}_{text}")
            user["mode"] = None

            send_message(
                chat_id,
                f"✅ Tracking started for {cat} {text}\n📡 Monitoring...",
                main_menu()
            )
        return

    # ADD PRODUCT
    if text == "🔍 add product":
        user["mode"] = "custom"
        send_message(chat_id, "Type product name:")
        return

    if user["mode"] == "custom":
        user["custom"].append(text)
        user["mode"] = None

        send_message(
            chat_id,
            f"✅ Tracking started for {text}\n📡 Monitoring...",
            main_menu()
        )
        return

    # STATUS
    if text == "📊 status":
        msg = "📊 Tracking:\n\n"

        for x in user["categories"]:
            msg += f"• {x}\n"
        for x in user["subcategories"]:
            msg += f"• {x}\n"
        for x in user["custom"]:
            msg += f"• {x}\n"

        send_message(chat_id, msg, main_menu())
        return

    # DELETE PRODUCT
    if text == "🗑 delete product":
        items = user["categories"] + user["subcategories"] + user["custom"]

        if not items:
            send_message(chat_id, "Nothing to delete", main_menu())
            return

        keyboard = {"keyboard": [[i] for i in items], "resize_keyboard": True}
        user["mode"] = "delete"
        send_message(chat_id, "Select to delete:", keyboard)
        return

    if user["mode"] == "delete":
        if text in user["categories"]:
            user["categories"].remove(text)
        elif text in user["subcategories"]:
            user["subcategories"].remove(text)
        elif text in user["custom"]:
            user["custom"].remove(text)

        user["mode"] = None
        send_message(chat_id, f"🗑 Removed {text}", main_menu())
        return

    # STOP ALL
    if text == "❌ stop all":
        user["categories"] = []
        user["subcategories"] = []
        user["custom"] = []

        send_message(chat_id, "❌ All tracking stopped", main_menu())
        return

# ---------------- MAIN LOOP ---------------- #

def main():
    keep_alive()
    users = load_users()
    offset = None

    while True:
        url = f"{BASE_URL}/getUpdates?timeout=100"

        if offset:
            url += f"&offset={offset}"

        res = requests.get(url).json()

        for update in res.get("result", []):
            offset = update["update_id"] + 1

            if "message" in update:
                handle_message(update["message"], users)

        save_users(users)

        # run tracker every cycle
        run_tracker(users)

        time.sleep(60)

if __name__ == "__main__":
    main()
