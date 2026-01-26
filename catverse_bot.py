import os
import random
import time
from datetime import datetime, timedelta, UTC

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

BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")

client = MongoClient(MONGO_URI)
db = client["catverse"]
cats = db["cats"]
global_state = db["global"]

# ================= LEVELS =================

LEVELS = [
    ("🐱 Kitten", 0),
    ("😺 Teen Cat", 30),
    ("😼 Rogue Cat", 60),
    ("🐯 Alpha Cat", 100),
    ("👑 Legend Cat", 160),
]

# ================= DATABASE =================

def get_cat(user):
    cat = cats.find_one({"_id": user.id})
    if not cat:
        cat = {
            "_id": user.id,
            "name": user.first_name,
            "coins": 1000,
            "fish": 2,
            "xp": 0,
            "kills": 0,
            "deaths": 0,
            "premium": True,
            "inventory": {"fish_bait": 0, "shield": 0},
            "dna": {"aggression": 1, "intelligence": 1, "luck": 1, "charm": 1},
            "level": "🐱 Kitten",
            "last_msg": 0,
            "protected_until": None,
            "last_daily": None,
            "created": datetime.now(UTC)
        }
        cats.insert_one(cat)
    return cat

def evolve(cat):
    total = sum(cat["dna"].values())
    for name, req in reversed(LEVELS):
        if total >= req:
            cat["level"] = name
            break

def is_protected(cat):
    return cat.get("protected_until") and cat["protected_until"] > datetime.now(UTC)

def dark_night_active():
    state = global_state.find_one({"_id": "dark"})
    return state and state["until"] > datetime.now(UTC)

def calculate_global_rank(user_id):
    all_cats = list(cats.find().sort("coins", -1))
    for idx, c in enumerate(all_cats, 1):
        if c["_id"] == user_id:
            return idx
    return 0

# ================= PASSIVE CHAT XP =================

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
        await update.message.reply_text(f"✨ Your cat evolved into {cat['level']}!")

    if random.random() < 0.05:
        context.chat_data["fish_event"] = True
        await update.message.reply_text("🐟 A magic fish appeared! Type: eat | save | share")

    if random.random() < 0.01 and not dark_night_active():
        global_state.update_one(
            {"_id": "dark"},
            {"$set": {"until": datetime.now(UTC) + timedelta(minutes=5)}},
            upsert=True
        )
        await update.message.reply_text("🌑 DARK NIGHT EVENT STARTED! Rare bonuses active!")

    cats.update_one({"_id": user.id}, {"$set": cat})

# ================= FISH EVENT =================

async def fish_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.chat_data.get("fish_event"):
        return

    cat = get_cat(update.effective_user)
    text = update.message.text.lower()

    if "eat" in text:
        cat["fish"] += 2
        cat["dna"]["aggression"] += 1
        msg = "😻 You ate the fish and feel stronger!"
    elif "save" in text:
        cat["dna"]["intelligence"] += 2
        msg = "🧠 You studied the fish. Intelligence up!"
    elif "share" in text:
        cat["dna"]["charm"] += 2
        msg = "💖 You shared the fish. Charm increased!"
    else:
        return

    evolve(cat)
    context.chat_data.pop("fish_event")
    cats.update_one({"_id": cat["_id"]}, {"$set": cat})
    await update.message.reply_text(msg)

# ================= ECONOMY =================

async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cat = get_cat(update.effective_user)
    now = datetime.now(UTC)

    if cat.get("last_daily") and now - cat["last_daily"] < timedelta(hours=24):
        return await update.message.reply_text("⏳ Your cat already collected daily fish today!")

    reward = 2000 if cat["premium"] else 1000
    cat["coins"] += reward
    cat["last_daily"] = now

    cats.update_one({"_id": cat["_id"]}, {"$set": cat})
    await update.message.reply_text(f"🎁 Daily reward claimed: {reward} coins!")

async def bal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cat = get_cat(update.effective_user)
    await update.message.reply_text(f"💰 Cat Coins: {cat['coins']}")

async def give(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message or not context.args:
        return await update.message.reply_text("Reply to a cat and type amount.")

    sender = get_cat(update.effective_user)
    receiver = get_cat(update.message.reply_to_message.from_user)

    amount = int(context.args[0])
    tax = 0.05
    final = int(amount * (1 - tax))

    if sender["coins"] < amount:
        return await update.message.reply_text("Not enough coins.")

    sender["coins"] -= amount
    receiver["coins"] += final

    cats.update_one({"_id": sender["_id"]}, {"$set": sender})
    cats.update_one({"_id": receiver["_id"]}, {"$set": receiver})

    await update.message.reply_text(f"🐾 You gifted {final} coins after cat tax!")

async def rob(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        return await update.message.reply_text("Reply to rob a cat.")

    thief = get_cat(update.effective_user)
    victim_user = update.message.reply_to_message.from_user
    victim = get_cat(victim_user)

    if is_protected(victim):
        return await update.message.reply_text("🛡 That cat is protected!")

    amount = min(random.randint(100, 5000), victim["coins"])

    victim["coins"] -= amount
    thief["coins"] += amount

    cats.update_one({"_id": thief["_id"]}, {"$set": thief})
    cats.update_one({"_id": victim["_id"]}, {"$set": victim})

    await update.message.reply_text(f"😼 You stole {amount} coins!")

    try:
        await context.bot.send_message(
            victim["_id"],
            f"💸 Your cat was robbed by {update.effective_user.first_name}!\nLost: {amount} coins"
        )
    except:
        pass

async def kill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        return await update.message.reply_text("Reply to attack a cat.")

    attacker = get_cat(update.effective_user)
    victim = get_cat(update.message.reply_to_message.from_user)

    reward = random.randint(200, 400)
    attacker["kills"] += 1
    victim["deaths"] += 1
    attacker["coins"] += reward
    attacker["dna"]["aggression"] += 2

    cats.update_one({"_id": attacker["_id"]}, {"$set": attacker})
    cats.update_one({"_id": victim["_id"]}, {"$set": victim})

    await update.message.reply_text(f"⚔️ Cat battle won! Earned {reward} coins!")

async def protect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cat = get_cat(update.effective_user)

    if cat["coins"] < 500:
        return await update.message.reply_text("Not enough coins for protection.")

    cat["coins"] -= 500
    cat["protected_until"] = datetime.now(UTC) + timedelta(days=1)

    cats.update_one({"_id": cat["_id"]}, {"$set": cat})
    await update.message.reply_text("🛡 Your cat is protected for 1 day.")

# ================= LEADERBOARDS =================

async def toprich(update: Update, context: ContextTypes.DEFAULT_TYPE):
    top = cats.find().sort("coins", -1).limit(10)
    msg = "🏆 Top Rich Cats\n\n"
    for i, c in enumerate(top, 1):
        msg += f"{i}. {c['name']} — {c['coins']} coins\n"
    await update.message.reply_text(msg)

async def topkill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    top = cats.find().sort("kills", -1).limit(10)
    msg = "⚔️ Top Cat Fighters\n\n"
    for i, c in enumerate(top, 1):
        msg += f"{i}. {c['name']} — {c['kills']} wins\n"
    await update.message.reply_text(msg)

# ================= PROFILE =================

async def me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cat = get_cat(update.effective_user)
    d = cat["dna"]
    rank = calculate_global_rank(cat["_id"])

    await update.message.reply_text(
        f"🐾 {cat['level']}\n"
        f"💰 Coins: {cat['coins']}\n"
        f"🏆 Rank: #{rank}\n"
        f"🐟 Fish: {cat['fish']}\n"
        f"⚔️ Wins: {cat['kills']} | 💀 Deaths: {cat['deaths']}\n\n"
        f"DNA → 😼 {d['aggression']} | 🧠 {d['intelligence']} | 🍀 {d['luck']} | 💖 {d['charm']}"
    )

# ================= MAIN =================

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("me", me))
    app.add_handler(CommandHandler("daily", daily))
    app.add_handler(CommandHandler("bal", bal))
    app.add_handler(CommandHandler("give", give))
    app.add_handler(CommandHandler("rob", rob))
    app.add_handler(CommandHandler("kill", kill))
    app.add_handler(CommandHandler("protect", protect))
    app.add_handler(CommandHandler("toprich", toprich))
    app.add_handler(CommandHandler("topkill", topkill))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fish_action))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_chat))

    print("🐱 CATVERSE ULTIMATE BOT RUNNING...")
    app.run_polling()

if __name__ == "__main__":
    main()
