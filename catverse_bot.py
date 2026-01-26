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

    default_data = {
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

    if not cat:
        cat = {"_id": user.id, **default_data}
        cats.insert_one(cat)
    else:
        # Auto-fix missing fields for old users
        update_fields = {}
        for key, value in default_data.items():
            if key not in cat:
                update_fields[key] = value
        if update_fields:
            cats.update_one({"_id": user.id}, {"$set": update_fields})
            cat.update(update_fields)

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

# ================= GAME GUIDE =================

async def games(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🐱 *CATVERSE GAME GUIDE*\n\n"
        "Level up your cat, earn coins, and dominate the streets!\n\n"
        "💰 *Economy*\n"
        "/daily – Get daily coins\n"
        "/bal – Check coins\n"
        "/give – Gift coins (reply)\n"
        "/rob – Steal coins (reply)\n\n"
        "⚔️ *Battles*\n"
        "/kill – Attack another cat\n"
        "/protect – 1 day protection\n\n"
        "📊 *Stats*\n"
        "/me – Your cat profile\n"
        "/toprich – Richest cats\n"
        "/topkill – Top fighters\n\n"
        "🎮 *Passive Game*\n"
        "Chat to gain XP & DNA\n"
        "Random fish events 🐟\n"
        "Dark Night global event 🌑"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

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
        await update.message.reply_text("🌑 DARK NIGHT EVENT STARTED!")

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
        msg = "😻 You ate the fish!"
    elif "save" in text:
        cat["dna"]["intelligence"] += 2
        msg = "🧠 Intelligence increased!"
    elif "share" in text:
        cat["dna"]["charm"] += 2
        msg = "💖 Charm increased!"
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
        return await update.message.reply_text("⏳ Already claimed today!")

    reward = 2000
    cat["coins"] += reward
    cat["last_daily"] = now

    cats.update_one({"_id": cat["_id"]}, {"$set": cat})
    await update.message.reply_text(f"🎁 You received {reward} coins!")

async def bal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cat = get_cat(update.effective_user)
    await update.message.reply_text(f"💰 Coins: {cat['coins']}")

async def give(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message or not context.args:
        return await update.message.reply_text("Reply and enter amount.")

    sender = get_cat(update.effective_user)
    receiver = get_cat(update.message.reply_to_message.from_user)

    amount = int(context.args[0])
    tax = int(amount * 0.05)
    final = amount - tax

    if sender["coins"] < amount:
        return await update.message.reply_text("Not enough coins.")

    sender["coins"] -= amount
    receiver["coins"] += final

    cats.update_one({"_id": sender["_id"]}, {"$set": sender})
    cats.update_one({"_id": receiver["_id"]}, {"$set": receiver})

    await update.message.reply_text(f"🐾 Sent {final} coins after tax!")

async def rob(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        return await update.message.reply_text("Reply to rob someone.")

    thief = get_cat(update.effective_user)
    victim_user = update.message.reply_to_message.from_user
    victim = get_cat(victim_user)

    if is_protected(victim):
        return await update.message.reply_text("🛡 Cat is protected!")

    amount = min(random.randint(100, 5000), victim["coins"])

    victim["coins"] -= amount
    thief["coins"] += amount

    cats.update_one({"_id": thief["_id"]}, {"$set": thief})
    cats.update_one({"_id": victim["_id"]}, {"$set": victim})

    await update.message.reply_text(f"😼 You stole {amount} coins!")

    try:
        await context.bot.send_message(victim["_id"], f"💸 You were robbed! Lost {amount} coins.")
    except:
        pass

async def kill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        return await update.message.reply_text("Reply to attack someone.")

    attacker = get_cat(update.effective_user)
    victim = get_cat(update.message.reply_to_message.from_user)

    reward = random.randint(200, 400)
    attacker["kills"] += 1
    victim["deaths"] += 1
    attacker["coins"] += reward

    cats.update_one({"_id": attacker["_id"]}, {"$set": attacker})
    cats.update_one({"_id": victim["_id"]}, {"$set": victim})

    await update.message.reply_text(f"⚔️ Victory! You earned {reward} coins!")

async def protect(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cat = get_cat(update.effective_user)

    if cat["coins"] < 500:
        return await update.message.reply_text("Need 500 coins.")

    cat["coins"] -= 500
    cat["protected_until"] = datetime.now(UTC) + timedelta(days=1)

    cats.update_one({"_id": cat["_id"]}, {"$set": cat})
    await update.message.reply_text("🛡 Protection enabled for 1 day.")

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
        f"⚔️ Wins: {cat.get('kills',0)} | 💀 Deaths: {cat.get('deaths',0)}\n\n"
        f"DNA → 😼 {d['aggression']} | 🧠 {d['intelligence']} | 🍀 {d['luck']} | 💖 {d['charm']}"
    )

# ================= MAIN =================

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("games", games))
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

    print("🐱 CATVERSE STABLE RUNNING...")
    app.run_polling()

if __name__ == "__main__":
    main()
