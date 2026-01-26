# ================= CATVERSE BOT FULL =================
import os
import random
import time
from datetime import datetime, timedelta

from pymongo import MongoClient
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")        # Set in Railway environment variables
MONGO_URI = os.getenv("MONGO_URI")        # Set in Railway environment variables

client = MongoClient(MONGO_URI)
db = client["catverse"]
cats = db["cats"]
global_state = db["global"]

# ================= LEVELS =================
LEVELS = [
    ("🐱 Kitten", 0),
    ("😺 Teen", 30),
    ("😼 Rogue", 60),
    ("🐯 Alpha", 100),
    ("👑 Legend", 160),
]

# ================= HELPERS =================
def get_cat(user):
    cat = cats.find_one({"_id": user.id})
    if not cat:
        cat = {
            "_id": user.id,
            "name": user.first_name,
            "coins": 500,
            "fish": 2,
            "xp": 0,
            "kills": 0,
            "premium": False,
            "dna": {
                "aggression": 1,
                "intelligence": 1,
                "luck": 1,
                "charm": 1,
            },
            "level": "🐱 Kitten",
            "last_msg": 0,
            "protected_until": None,
            "last_daily": None,
            "created": datetime.utcnow()
        }
        cats.insert_one(cat)
    return cat

def evolve(cat):
    total = sum(cat["dna"].values())
    for name, req in reversed(LEVELS):
        if total >= req:
            cat["level"] = name
            break

def dark_night_active():
    state = global_state.find_one({"_id": "dark"})
    if not state:
        return False
    return state["until"] > datetime.utcnow()

def calculate_global_rank(user_id):
    all_cats = list(cats.find().sort("coins", -1))
    for idx, c in enumerate(all_cats, 1):
        if c["_id"] == user_id:
            return idx
    return 0

# ================= ALWAYS ON CHAT =================
async def on_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user = update.effective_user
    cat = get_cat(user)

    now = time.time()
    if now - cat["last_msg"] < 4:
        return

    cat["last_msg"] = now
    cat["xp"] += random.randint(1, 3)
    stat = random.choice(list(cat["dna"]))
    cat["dna"][stat] += 1

    old_level = cat["level"]
    evolve(cat)

    if old_level != cat["level"]:
        await update.message.reply_text(
            f"✨ EVOLVED!\nYou are now **{cat['level']}** 😼",
            parse_mode="Markdown"
        )

    # Fish event
    if random.random() < 0.05:
        context.chat_data["fish"] = True
        await update.message.reply_text(
            "🐟 A glowing fish appeared!\nType: eat | save | share"
        )

    # Dark night trigger
    if random.random() < 0.01 and not dark_night_active():
        global_state.update_one(
            {"_id": "dark"},
            {"$set": {"until": datetime.utcnow() + timedelta(minutes=5)}},
            upsert=True
        )
        await update.message.reply_text(
            "🌑 **DARK NIGHT HAS FALLEN**\n"
            "Rare events stronger… Legends rise 👑",
            parse_mode="Markdown"
        )

    cats.update_one({"_id": user.id}, {"$set": cat})

# ================= FISH ACTION =================
async def fish_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.chat_data.get("fish"):
        return

    cat = get_cat(update.effective_user)
    text = update.message.text.lower()

    if "eat" in text:
        cat["fish"] += 2
        cat["dna"]["aggression"] += 1
        msg = "😻 You ate the fish. Power up!"
    elif "save" in text:
        cat["dna"]["intelligence"] += 2
        msg = "🧠 Smart choice. Brain boosted."
    elif "share" in text:
        cat["dna"]["charm"] += 2
        msg = "💖 Shared fish. Charm increased."
    else:
        return

    evolve(cat)
    context.chat_data.pop("fish")
    cats.update_one({"_id": cat["_id"]}, {"$set": cat})
    await update.message.reply_text(msg)

# ================= ECONOMY COMMANDS =================
async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cat = get_cat(update.effective_user)
    now = datetime.utcnow()
    reward = 1000 if not cat["premium"] else 2000

    if cat.get("last_daily") and now - cat["last_daily"] < timedelta(hours=24):
        await update.message.reply_text("⏳ Daily already claimed.")
        return

    cat["coins"] += reward
    cat["last_daily"] = now
    cats.update_one({"_id": cat["_id"]}, {"$set": cat})
    await update.message.reply_text(f"💰 You received ${reward} daily!")

async def give(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message or not context.args:
        return await update.message.reply_text("Reply to user and type amount.")

    cat = get_cat(update.effective_user)
    target = get_cat(update.message.reply_to_message.from_user)
    try:
        amt = int(context.args[0])
    except:
        return await update.message.reply_text("Invalid amount.")

    fee = int(amt * (0.05 if cat["premium"] else 0.10))
    total = amt + fee
    if cat["coins"] < total:
        return await update.message.reply_text("Not enough coins.")

    cat["coins"] -= total
    target["coins"] += amt
    cats.update_one({"_id": cat["_id"]}, {"$set": cat})
    cats.update_one({"_id": target["_id"]}, {"$set": target})
    await update.message.reply_text(f"💸 Sent ${amt} (Fee: ${fee})")

async def rob(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        return await update.message.reply_text("Reply to rob someone.")

    cat = get_cat(update.effective_user)
    target = get_cat(update.message.reply_to_message.from_user)

    if target.get("protected_until") and target["protected_until"] > datetime.utcnow():
        return await update.message.reply_text("🛡 Target is protected.")

    max_amount = 100000 if cat["premium"] else 10000
    amt = random.randint(100, max_amount)
    if amt > target["coins"]:
        amt = target["coins"]

    tax = 0.05 if cat["premium"] else 0.10
    net = int(amt * (1 - tax))

    target["coins"] -= amt
    cat["coins"] += net

    cats.update_one({"_id": cat["_id"]}, {"$set": cat})
    cats.update_one({"_id": target["_id"]}, {"$set": target})
    await update.message.reply_text(f"😈 You robbed ${net} from {target['name']} (Tax: {int(amt*tax)})")

async def protect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cat = get_cat(update.effective_user)
    cost = 500
    if cat["coins"] < cost:
        return await update.message.reply_text("Not enough coins.")
    cat["coins"] -= cost
    cat["protected_until"] = datetime.utcnow() + timedelta(days=1)
    cats.update_one({"_id": cat["_id"]}, {"$set": cat})
    await update.message.reply_text("🛡 Protection active for 1 day.")

# ================= OTHER COMMANDS =================
async def kill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        return
    cat = get_cat(update.effective_user)
    reward = random.randint(100, 300)
    cat["coins"] += reward
    cat["kills"] += 1
    cat["dna"]["aggression"] += 2
    cats.update_one({"_id": cat["_id"]}, {"$set": cat})
    await update.message.reply_text(f"💀 Kill success!\n+{reward} coins")

async def top_rich(update: Update, context: ContextTypes.DEFAULT_TYPE):
    top = cats.find().sort("coins", -1).limit(10)
    text = "💰 **Top Rich Cats**\n"
    for i, c in enumerate(top, 1):
        text += f"{i}. {c['name']} — {c['coins']}\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def top_kill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    top = cats.find().sort("kills", -1).limit(10)
    text = "💀 **Top Killer Cats**\n"
    for i, c in enumerate(top, 1):
        text += f"{i}. {c['name']} — {c['kills']} kills\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cat = get_cat(update.effective_user)
    d = cat["dna"]
    rank = calculate_global_rank(cat["_id"])
    await update.message.reply_text(
        f"🐾 **Your Cat**\n"
        f"Stage: {cat['level']}\n"
        f"💰 Coins: {cat['coins']}\n"
        f"Global Rank: #{rank} 🏆\n"
        f"🐟 Fish: {cat['fish']}\n"
        f"💀 Kills: {cat['kills']}\n\n"
        f"DNA:\n"
        f"😼 {d['aggression']}  🧠 {d['intelligence']}\n"
        f"🍀 {d['luck']}  💖 {d['charm']}",
        parse_mode="Markdown"
    )

async def games(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🐱 **CATVERSE GUIDE**\n\n"
        "• Game always ON, just chat!\n"
        "• Fish events = eat | save | share\n"
        "• /me — view your cat stats & ranking\n"
        "• Reply + /kill — attack another cat\n"
        "• /toprich — top rich cats\n"
        "• /topkill — top killer cats\n"
        "• /give — gift coins (premium lower fee)\n"
        "• /rob — rob coins (premium higher limit)\n"
        "• /protect — buy 1 day protection\n"
        "• Dark Night 🌑 = rare power boost\n\n"
        "Enjoy your cat life! 😼",
        parse_mode="Markdown"
    )

# ================= MAIN =================
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("me", me))
    app.add_handler(CommandHandler("kill", kill))
    app.add_handler(CommandHandler("toprich", top_rich))
    app.add_handler(CommandHandler("topkill", top_kill))
    app.add_handler(CommandHandler("daily", daily))
    app.add_handler(CommandHandler("give", give))
    app.add_handler(CommandHandler("rob", rob))
    app.add_handler(CommandHandler("protect", protect))
    app.add_handler(CommandHandler("games", games))

    # Chat events
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_chat))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fish_action))

    print("🐱 CATVERSE BOT FULL ECONOMY & RPG IS LIVE")
    app.run_polling()

if __name__ == "__main__":
    main()
