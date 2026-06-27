"""
Bassura City Food Shop — Telegram Bot Backend
==============================================
Handles webhook, Mini App orders, and owner notifications.

SETUP: Set BOT_TOKEN and OWNER_CHAT_ID as environment variables.
MODIFY: Edit MENU dict to change prices/items. Edit WELCOME_TEXT for greeting.
"""
import asyncio
import json
import os
import re
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, request, jsonify, Response
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

# =====================================================================
# Configuration
# =====================================================================
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_CHAT_ID = os.getenv("OWNER_CHAT_ID", "") or "6484749863"
PORT = int(os.getenv("PORT", "3000"))

_railway_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "")
if _railway_domain:
    WEBHOOK_URL = f"https://{_railway_domain}"
else:
    WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")

# ---- Fallback values when env vars are not set ----
if not BOT_TOKEN:
    BOT_TOKEN = "8648539997:AAGdMAzaDS7sEejxEf0p2yAm6QPlmTK00mU"

# =====================================================================
# Menu
# =====================================================================
MENU = {
    "cappuccino":   {"name": "Cappuccino",    "price": 20000, "emoji": "☕"},
    "cafe-latte":   {"name": "Cafe Latte",    "price": 20000, "emoji": "🫗"},
    "croissant":    {"name": "Croissant",     "price": 20000, "emoji": "🥐"},
    "fried-noodle": {"name": "Fried Noodles", "price": 20000, "emoji": "🍜"},
}

WELCOME_TEXT = (
    "🍽️ *Bassura Food Shop*\n"
    "Pesan makanan & minuman, kami antar ke unit kamu!\n\n"
    "📋 *Menu Hari Ini:*\n"
    "  ☕ Cappuccino — Rp 20.000\n"
    "  🫗 Cafe Latte — Rp 20.000\n"
    "  🥐 Croissant — Rp 20.000\n"
    "  🍜 Fried Noodles — Rp 20.000\n\n"
    "🛒 Klik tombol di bawah untuk mulai pesan."
)

ORDERS_FILE = Path(__file__).parent / "orders.json"

# =====================================================================
# Order Storage
# =====================================================================
def load_orders():
    if not ORDERS_FILE.exists():
        return []
    try:
        with open(ORDERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []

def save_order(order_data: dict) -> int:
    orders = load_orders()
    order_number = len(orders) + 1
    order_data["order_id"] = order_number
    order_data["status"] = "pending"
    order_data["received_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    orders.append(order_data)
    with open(ORDERS_FILE, "w", encoding="utf-8") as f:
        json.dump(orders, f, ensure_ascii=False, indent=2)
    return order_number

def mark_delivered(order_id: int) -> bool:
    orders = load_orders()
    for o in orders:
        if o.get("order_id") == order_id and o.get("status") == "pending":
            o["status"] = "delivered"
            o["delivered_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with open(ORDERS_FILE, "w", encoding="utf-8") as f:
                json.dump(orders, f, ensure_ascii=False, indent=2)
            return True
    return False

def format_order(order: dict) -> str:
    lines = [f"🛎️ *Pesanan Baru #{order['order_id']}*"]
    lines.append(f"👤 *Nama:* {order['customer_name']}")
    lines.append(f"🏢 *Unit:* {order['unit']}")
    lines.append(f"📞 *Telp:* {order['phone']}")
    if order.get("notes"):
        lines.append(f"📝 *Catatan:* {order['notes']}")
    lines.append("")
    lines.append("*Pesanan:*")
    for item in order.get("items", []):
        lines.append(f"  {item['qty']}x {item['product']} — Rp {item['subtotal']:,}")
    lines.append(f"\n💰 *Total:* Rp {order['total']:,}")
    lines.append(f"⏰ *Waktu:* {order['received_at']}")
    return "\n".join(lines)

# =====================================================================
# Telegram Bot Handlers
# =====================================================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not WEBHOOK_URL:
        await update.message.reply_text(
            "⚠️ Toko belum siap. Mohon tunggu sebentar.", parse_mode="Markdown"
        )
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(text="🛒 Buka Toko", web_app=WebAppInfo(url=WEBHOOK_URL))]
    ])
    await update.message.reply_text(WELCOME_TEXT, parse_mode="Markdown", reply_markup=keyboard)

async def web_app_data_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        order = json.loads(update.message.web_app_data.data)
    except (json.JSONDecodeError, AttributeError):
        await update.message.reply_text("❌ Data pesanan tidak valid.")
        return

    errors = []
    if not order.get("customer_name"): errors.append("Nama tidak boleh kosong.")
    if not order.get("unit"): errors.append("Unit apartemen tidak boleh kosong.")
    if not order.get("items"): errors.append("Keranjang kosong.")
    if not order.get("phone"): errors.append("Nomor telepon tidak boleh kosong.")
    if order.get("unit") and not re.match(r"^[A-Z]\d+[A-Z]+$", order.get("unit", ""), re.IGNORECASE):
        errors.append("Format unit tidak valid. Gunakan format Bassura City, contoh: B29CE.")

    if errors:
        await update.message.reply_text("❌ " + "\n".join(errors), parse_mode="Markdown")
        return

    order_number = save_order(order)

    customer_msg = (
        f"✅ *Pesanan #{order_number} Diterima!*\n\n"
        f"Hai {order['customer_name']}, pesanan kamu akan segera kami proses "
        f"dan diantar ke unit *{order['unit']}*.\n\n"
        f"Total: *Rp {order['total']:,}* (bayar di tempat)\n\n"
        f"Terima kasih! 🍽️"
    )
    await update.message.reply_text(customer_msg, parse_mode="Markdown")

    if OWNER_CHAT_ID:
        try:
            await context.bot.send_message(
                chat_id=OWNER_CHAT_ID,
                text=format_order(order),
                parse_mode="Markdown"
            )
        except Exception as e:
            print(f"Owner notify failed: {e}")

async def orders_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id != OWNER_CHAT_ID:
        await update.message.reply_text("❌ Perintah ini hanya untuk pemilik toko.")
        return

    orders = load_orders()
    pending = [o for o in orders if o.get("status") == "pending"]
    if not pending:
        await update.message.reply_text("📭 Tidak ada pesanan yang menunggu.")
        return

    lines = ["📋 *Pesanan Menunggu:*\n"]
    for o in pending:
        items_str = ", ".join(f"{i['qty']}x {i['product']}" for i in o.get("items", []))
        lines.append(
            f"*#{o['order_id']}* — {o['customer_name']} ({o['unit']})\n"
            f"  {items_str}  |  Rp {o['total']:,}  |  {o['received_at']}\n"
            f"  _/done\\_ {o['order_id']} untuk tandai selesai_\n"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    if user_id != OWNER_CHAT_ID:
        await update.message.reply_text("❌ Perintah ini hanya untuk pemilik toko.")
        return
    if not context.args:
        await update.message.reply_text("ℹ️ Gunakan: `/done <nomor>`. Contoh: `/done 3`", parse_mode="Markdown")
        return
    try:
        order_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Nomor pesanan harus angka.")
        return

    if mark_delivered(order_id):
        await update.message.reply_text(f"✅ Pesanan *#{order_id}* ditandai selesai.", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ Pesanan #{order_id} tidak ditemukan atau sudah selesai.")

# =====================================================================
# Flask App
# =====================================================================
app = Flask(__name__)
application = None

@app.route("/")
def serve_miniapp():
    html_path = Path(__file__).parent / "index.html"
    if html_path.exists():
        return Response(html_path.read_text(encoding="utf-8"), mimetype="text/html; charset=utf-8")
    return "Mini App not found", 404

@app.route("/health")
def health():
    global application, _bot_loop
    env_keys = sorted(k for k in os.environ.keys())
    # Test if bot can send messages
    can_send = False
    send_error = ""
    if application and _bot_loop and _bot_loop.is_running():
        try:
            async def test():
                me = await application.bot.get_me()
                return me.username
            future = asyncio.run_coroutine_threadsafe(test(), _bot_loop)
            bot_user = future.result(timeout=5)
            can_send = True
        except Exception as e:
            send_error = str(e)
            bot_user = None
    else:
        bot_user = None
    return jsonify({
        "status": "ok",
        "bot_ready": application is not None,
        "bot_username": bot_user,
        "can_send": can_send,
        "send_error": send_error,
        "webhook_url": WEBHOOK_URL,
        "owner_id": OWNER_CHAT_ID,
        "bot_token_len": len(BOT_TOKEN),
    })

# Shared event loop for bot operations
_bot_loop = None

@app.route("/webhook", methods=["POST"])
def webhook():
    global application, _bot_loop
    if application is None:
        return jsonify({"ok": False, "error": "bot not ready"}), 503
    try:
        data = request.get_json(force=True)
        if data:
            update = Update.de_json(data, application.bot)
            if _bot_loop and _bot_loop.is_running():
                future = asyncio.run_coroutine_threadsafe(
                    application.process_update(update), _bot_loop
                )
                future.result(timeout=20)
            else:
                asyncio.run(application.process_update(update))
    except Exception as e:
        print(f"Webhook error: {e}", flush=True)
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True})

# =====================================================================
# Bot initializer (runs in background after Flask starts)
# =====================================================================
def init_bot():
    global application, _bot_loop
    print("🤖 Initializing bot...", flush=True)

    if not BOT_TOKEN:
        print("⚠️ BOT_TOKEN not set — bot disabled", flush=True)
        return

    try:
        app_builder = Application.builder().token(BOT_TOKEN)
        application = app_builder.build()
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("orders", orders_command))
        application.add_handler(CommandHandler("done", done_command))
        application.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, web_app_data_handler))
        print("✅ Handlers registered", flush=True)

        # Create a persistent event loop for the bot
        _bot_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_bot_loop)

        if WEBHOOK_URL:
            async def setup():
                await application.bot.set_webhook(
                    url=f"{WEBHOOK_URL}/webhook",
                    allowed_updates=["message", "callback_query"]
                )
                await application.initialize()
                await application.start()
            _bot_loop.run_until_complete(setup())
            print(f"✅ Webhook set: {WEBHOOK_URL}/webhook", flush=True)

        # Keep the loop running for future webhook calls
        threading.Thread(target=_bot_loop.run_forever, daemon=True).start()

    except Exception as e:
        print(f"❌ Bot init failed: {e}", flush=True)
        traceback.print_exc()

# =====================================================================
# Main
# =====================================================================
if __name__ == "__main__":
    print(f"🚀 Bassura Shop starting on port {PORT}", flush=True)

    # Start bot in background thread AFTER Flask is ready
    threading.Thread(target=init_bot, daemon=True).start()

    # Start Flask immediately — don't wait for bot
    app.run(host="0.0.0.0", port=PORT, debug=False)
