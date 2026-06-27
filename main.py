"""
Bassura City Food Shop — Telegram Bot Backend
==============================================
Handles webhook, Mini App orders, and owner notifications.

SETUP:
  1. Copy .env.example to .env and fill in BOT_TOKEN and OWNER_CHAT_ID
  2. Install: pip install -r requirements.txt
  3. Run locally: python main.py
  4. For production: deploy to Railway with PORT and WEBHOOK_URL in env

HOW TO MODIFY:
  - Change menu items: edit the MENU dict (line ~50)
  - Change prices: edit "price" values in MENU
  - Change welcome message: edit WELCOME_TEXT
  - Change owner chat ID: set OWNER_CHAT_ID in .env
"""
import asyncio
import json
import os
import sys
import threading
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
OWNER_CHAT_ID = os.getenv("OWNER_CHAT_ID", "")  # Your Telegram user ID
PORT = int(os.getenv("PORT", "3000"))  # Railway uses 3000 default

# Auto-detect deployment URL.
# Railway sets RAILWAY_PUBLIC_DOMAIN automatically.
# For local dev, set WEBHOOK_URL in .env.
_railway_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "")
if _railway_domain:
    WEBHOOK_URL = f"https://{_railway_domain}"
else:
    WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")

if not BOT_TOKEN:
    print("ERROR: BOT_TOKEN not set. Set it as an environment variable or in .env")
    sys.exit(1)

# =====================================================================
# Menu — change prices or add items here
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
# Order Storage (JSON file)
# =====================================================================
def load_orders():
    """Load all orders from the JSON file. Returns a list."""
    if not ORDERS_FILE.exists():
        return []
    try:
        with open(ORDERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []

def save_order(order_data: dict) -> int:
    """Save a new order. Returns the order number (1-based)."""
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
    """Mark an order as delivered. Returns True if found and pending."""
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
    """Format an order as a readable Telegram message for the owner."""
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
    """Send welcome message with 'Open Shop' button (Mini App)."""
    # If this is the first user and OWNER_CHAT_ID is not set,
    # remind them to set it.
    if not OWNER_CHAT_ID:
        await update.message.reply_text(
            "⚠️ *OWNER_CHAT_ID belum diatur!*\n\n"
            f"Kirim ID ini ke file .env kamu:\n`OWNER_CHAT_ID={update.effective_user.id}`\n\n"
            "Tanpa ini, kamu tidak akan menerima notifikasi pesanan baru.",
            parse_mode="Markdown"
        )
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            text="🛒 Buka Toko",
            web_app=WebAppInfo(url=WEBHOOK_URL)
        )]
    ])
    await update.message.reply_text(
        WELCOME_TEXT,
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def web_app_data_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle order data sent from the Mini App via sendData()."""
    try:
        order = json.loads(update.message.web_app_data.data)
    except (json.JSONDecodeError, AttributeError):
        await update.message.reply_text("❌ Data pesanan tidak valid. Silakan coba lagi.")
        return

    # --- Validate required fields ---
    errors = []
    if not order.get("customer_name"):
        errors.append("Nama tidak boleh kosong.")
    if not order.get("unit"):
        errors.append("Unit apartemen tidak boleh kosong.")
    if not order.get("items"):
        errors.append("Keranjang kosong — tambahkan item dulu.")
    if not order.get("phone"):
        errors.append("Nomor telepon tidak boleh kosong.")
    if order.get("unit") and "bassura" not in order.get("unit", "").lower():
        errors.append("Maaf, saat ini kami hanya melayani pengiriman di *Bassura City Apartment*.")

    if errors:
        await update.message.reply_text("❌ " + "\n".join(errors), parse_mode="Markdown")
        return

    # --- Save order ---
    order_number = save_order(order)

    # --- Confirm to customer ---
    customer_msg = (
        f"✅ *Pesanan #{order_number} Diterima!*\n\n"
        f"Hai {order['customer_name']}, pesanan kamu akan segera kami proses "
        f"dan diantar ke unit *{order['unit']}*.\n\n"
        f"Total: *Rp {order['total']:,}* (bayar di tempat)\n\n"
        f"Terima kasih! 🍽️"
    )
    await update.message.reply_text(customer_msg, parse_mode="Markdown")

    # --- Notify owner ---
    if OWNER_CHAT_ID:
        try:
            await context.bot.send_message(
                chat_id=OWNER_CHAT_ID,
                text=format_order(order),
                parse_mode="Markdown"
            )
        except Exception as e:
            print(f"Failed to notify owner ({OWNER_CHAT_ID}): {e}")

async def orders_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner command: show all pending orders. Only works for owner."""
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
        items_str = ", ".join(
            f"{i['qty']}x {i['product']}" for i in o.get("items", [])
        )
        lines.append(
            f"*#{o['order_id']}* — {o['customer_name']} ({o['unit']})\n"
            f"  {items_str}\n"
            f"  Rp {o['total']:,} | {o['received_at']}\n"
            f"  _/done\\_ {o['order_id']} untuk tandai selesai_\n"
        )

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner command: mark an order as delivered. Usage: /done 3"""
    user_id = str(update.effective_user.id)
    if user_id != OWNER_CHAT_ID:
        await update.message.reply_text("❌ Perintah ini hanya untuk pemilik toko.")
        return

    if not context.args:
        await update.message.reply_text(
            "ℹ️ Gunakan: `/done <nomor pesanan>`\nContoh: `/done 3`",
            parse_mode="Markdown"
        )
        return

    try:
        order_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Nomor pesanan harus angka.")
        return

    if mark_delivered(order_id):
        await update.message.reply_text(
            f"✅ Pesanan *#{order_id}* ditandai selesai.",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            f"❌ Pesanan #{order_id} tidak ditemukan atau sudah selesai."
        )

# =====================================================================
# Flask App (serves Mini App HTML + webhook endpoint)
# =====================================================================
app = Flask(__name__)

@app.route("/")
def serve_miniapp():
    """Serve the Mini App HTML page."""
    html_path = Path(__file__).parent / "index.html"
    if html_path.exists():
        return Response(html_path.read_text(encoding="utf-8"), mimetype="text/html; charset=utf-8")
    return "Mini App not found", 404

application = None  # Will be set in main()

# =====================================================================
# Webhook mode (production)
# =====================================================================
@app.route("/webhook", methods=["POST"])
async def webhook():
    """Handle incoming Telegram updates via webhook."""
    global application
    if application is None:
        return jsonify({"ok": False, "error": "Application not initialized"}), 500
    try:
        data = request.get_json(force=True)
        if data:
            update = Update.de_json(data, application.bot)
            await application.process_update(update)
    except Exception as e:
        print(f"Webhook error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500
    return jsonify({"ok": True})

# =====================================================================
# Main entry point
# =====================================================================
def main():
    global application

    app_builder = Application.builder().token(BOT_TOKEN)
    application = app_builder.build()

    # Register handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("orders", orders_command))
    application.add_handler(CommandHandler("done", done_command))
    application.add_handler(
        MessageHandler(filters.StatusUpdate.WEB_APP_DATA, web_app_data_handler)
    )

    if WEBHOOK_URL:
        # --- Production: webhook mode ---
        print(f"🌐 Production mode — webhook")
        print(f"   PORT: {PORT}")
        print(f"   URL:  {WEBHOOK_URL}")
        print(f"   Webhook: {WEBHOOK_URL}/webhook")

        # Set webhook on Telegram servers
        async def set_webhook():
            await application.bot.set_webhook(
                url=f"{WEBHOOK_URL}/webhook",
                allowed_updates=["message", "callback_query"]
            )
            await application.initialize()
            await application.start()
            print("✅ Webhook set and bot started.")

        # Run the async setup in the same event loop
        if threading.current_thread() is threading.main_thread():
            # In Railway, the gunicorn process runs Flask sync.
            # We need to initialize the bot async, then serve.
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(set_webhook())

        # Run Flask (gunicorn will import 'app' directly on Railway)
        app.run(host="0.0.0.0", port=PORT, debug=False)

    else:
        # --- Development: polling mode ---
        print("🏠 Development mode — polling")
        print("   Set WEBHOOK_URL in .env for production.")
        application.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
