import requests
import time
import json
import os
from datetime import datetime
from playwright.sync_api import sync_playwright

BOT_TOKEN = "7832594298:AAGaJtsNHMQ1-CjzSCfa45mdyaWwiQSNgqc"
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
USERS_FILE = "users.json"
PRICE_HISTORY_FILE = "price_history.json"

# ---------------- LOAD / SAVE ---------------- #
def load_users():
    try:
        with open(USERS_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_users(data):
    with open(USERS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def load_price_history():
    try:
        with open(PRICE_HISTORY_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_price_history(data):
    with open(PRICE_HISTORY_FILE, "w") as f:
        json.dump(data, f, indent=2)

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
    try:
        requests.post(f"{BASE_URL}/sendMessage", json=payload, timeout=10)
    except Exception as e:
        print(f"Send message error: {e}")

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
            print(f"Fetched data for '{query}'")
            return data if data else {}
    except Exception as e:
        print(f"Playwright error for '{query}': {e}")
        return {}

# ---------------- PRICE LOGIC ---------------- #
def process_data(user_id, chat_id, query, data, price_history):
    if not data:
        return
    try:
        products = data.get("data", {}).get("data", [])
    except:
        return

    for product in products[:5]:
        name = product.get("name", "Unknown")
        try:
            price = float(product.get("price", 0))
        except:
            continue
        link = product.get("url", "")

        key = f"{user_id}_{name}"

        if key in price_history:
            old_price = price_history[key]
            if old_price > 0:
                drop = ((old_price - price) / old_price) * 100
                if drop >= 10:  # 10% price drop alert
                    send_message(
                        chat_id,
                        f"🔥 PRICE DROP ALERT\n\n{name}\n⬇️ {round(drop,1)}%\n₹{old_price} → ₹{price}\n{link}"
                    )

        price_history[key] = price  # Update price history

# ---------------- TRACKER ---------------- #
def run_tracker(users, price_history):
    print(f"Running tracker for {len(users)} users...")
    for user_id, user in users.items():
        user = normalize_user(user)
        if not user.get("setup_done"):
            continue

        queries = []
        queries += user.get("categories", [])
        queries += [s.replace("_", " ") for s in user.get("subcategories", [])]
        queries += user.get("custom", [])

        for q in queries:
            if not q:
                continue
            data = fetch_data(q, user.get("pincode"))
            process_data(str(user_id), str(user_id), q, data, price_history)

# ---------------- HANDLER ---------------- #
def handle_message(msg, users):
    chat_id = str(msg["chat"]["id"])
    text = msg.get("text", "").lower().strip()

    if chat_id not in users:
        users[chat_id] = {}
    user = normalize_user(users[chat_id])

    # START
    if text == "/start":
        send_message(chat_id, "Please enter your pincode:")
        user["mode"] = "pincode"
        return

    # PINCODE
    if user.get("mode") == "pincode":
        user["pincode"] = text
        user["setup_done"] = True
        user["mode"] = None
        send_message(chat_id, "✅ Setup completed successfully!", main_menu())
        return

    # ADD CATEGORY
    if text == "➕ add category":
        keyboard = {"keyboard": [[c] for c in CATEGORIES], "resize_keyboard": True}
        user["mode"] = "category"
        send_message(chat_id, "Select a category:", keyboard)
        return

    if user.get("mode") == "category":
        if text in CATEGORIES:
            keyboard = {"keyboard": [[s] for s in CATEGORIES[text]], "resize_keyboard": True}
            user["current_category"] = text
            user["mode"] = "subcategory"
            send_message(chat_id, "Select subcategory:", keyboard)
        return

    if user.get("mode") == "subcategory":
        cat = user.get("current_category")
        if cat:
            user["subcategories"].append(f"{cat}_{text}")
            user["mode"] = None
            send_message(chat_id, f"✅ Now tracking {cat} - {text}", main_menu())
        return

    # ADD PRODUCT
    if text == "🔍 add product":
        user["mode"] = "custom"
        send_message(chat_id, "Type the product name you want to track:")
        return

    if user.get("mode") == "custom":
        user["custom"].append(text)
        user["mode"] = None
        send_message(chat_id, f"✅ Now tracking custom product: {text}", main_menu())
        return

    # STATUS
    if text == "📊 status":
        msg_text = "📊 Currently tracking:\n\n"
        for x in user.get("categories", []):
            msg_text += f"• {x}\n"
        for x in user.get("subcategories", []):
            msg_text += f"• {x}\n"
        for x in user.get("custom", []):
            msg_text += f"• {x}\n"
        if not any([user.get("categories"), user.get("subcategories"), user.get("custom")]):
            msg_text += "Nothing yet."
        send_message(chat_id, msg_text, main_menu())
        return

    # DELETE PRODUCT
    if text == "🗑 delete product":
        items = user.get("categories", []) + user.get("subcategories", []) + user.get("custom", [])
        if not items:
            send_message(chat_id, "No products to delete.", main_menu())
            return
        keyboard = {"keyboard": [[i] for i in items], "resize_keyboard": True}
        user["mode"] = "delete"
        send_message(chat_id, "Select item to stop tracking:", keyboard)
        return

    if user.get("mode") == "delete":
        for lst in ["categories", "subcategories", "custom"]:
            if text in user.get(lst, []):
                user[lst].remove(text)
                send_message(chat_id, f"🗑 Stopped tracking: {text}", main_menu())
                user["mode"] = None
                return
        send_message(chat_id, "Item not found.", main_menu())
        user["mode"] = None
        return

    # STOP ALL
    if text == "❌ stop all":
        user["categories"] = []
        user["subcategories"] = []
        user["custom"] = []
        send_message(chat_id, "❌ All tracking has been stopped.", main_menu())
        return

# ---------------- MAIN LOOP ---------------- #
def main():
    users = load_users()
    price_history = load_price_history()
    offset = None
    last_tracker_run = 0

    print("🤖 Price Drop Alert Bot Started - Max 5 users supported")
    print(f"Price history loaded: {len(price_history)} items")

    while True:
        # Handle Telegram messages
        try:
            url = f"{BASE_URL}/getUpdates?timeout=100"
            if offset:
                url += f"&offset={offset}"

            res = requests.get(url, timeout=120).json()

            for update in res.get("result", []):
                offset = update["update_id"] + 1
                if "message" in update:
                    handle_message(update["message"], users)
        except Exception as e:
            print(f"Polling error: {e}")

        save_users(users)

        # Run Playwright tracker every 10 minutes
        current_time = time.time()
        if current_time - last_tracker_run >= 600:   # 600 seconds = 10 minutes
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Running price tracker...")
            run_tracker(users, price_history)
            last_tracker_run = current_time
            save_price_history(price_history)

        time.sleep(30)   # Low CPU usage

if __name__ == "__main__":
    main()
