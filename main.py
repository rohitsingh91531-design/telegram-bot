import os
import telebot
from flask import Flask
from threading import Thread
from pymongo import MongoClient

# --- Configuration ---
# Apne BOT TOKEN aur MongoDB URI ko Environment Variables (Secrets) mein set karein!
BOT_TOKEN = os.environ.get("BOT_TOKEN") 
MONGO_URI = os.environ.get("MONGO_URI") # MongoDB connection string
ADMIN_ID = 6268090266 # <--- YAHAN APNA TELEGRAM USER ID ZAROOR DAALEIN!!!

# --- Database Setup (MongoDB) ---
try:
    client = MongoClient(MONGO_URI)
    db_name = client["FileHostBotDB"] # Aapke database ka naam
    coll_files = db_name["files"] # Files/Links store karne ka Collection
    coll_meta = db_name["metadata"] # Counter aur batch status store karne ka Collection
    print("MongoDB connection successful!")
except Exception as e:
    print(f"MongoDB connection failed: {e}")

bot = telebot.TeleBot(BOT_TOKEN)

# Counter aur batch_status ko MongoDB se manage karein
def get_next_counter():
    # Counter ko increment karke naya value return karein
    result = coll_meta.find_one_and_update(
        {"_id": "link_counter"},
        {"$inc": {"value": 1}},
        upsert=True,
        return_document=True
    )
    return result['value'] if result else 1

def get_meta(key):
    # Metadata fetch karein (e.g., batch_status)
    meta = coll_meta.find_one({"_id": key})
    return meta['value'] if meta else {}

def set_meta(key, value):
    # Metadata set/update karein
    coll_meta.update_one({"_id": key}, {"$set": {"value": value}}, upsert=True)

# --- Batch Status Functions ---
def get_batch_status(user_id):
    status_dict = get_meta("batch_status")
    return status_dict.get(str(user_id), 'off')

def set_batch_status(user_id, status):
    status_dict = get_meta("batch_status")
    status_dict[str(user_id)] = status
    set_meta("batch_status", status_dict)
    
# --- Bot Logic (Same as before, with MongoDB calls) ---

@bot.message_handler(content_types=['document', 'video', 'photo', 'audio', 'voice', 'sticker'])
def handle_files(message):
    # ... (file_id aur file_type extract karne ka code same rahega) ...
    
    # ... (file_id aur file_type extract karne ka code) ...
    if message.document: file_id = message.document.file_id; file_type = "document"
    elif message.video: file_id = message.video.file_id; file_type = "video"
    elif message.photo: file_id = message.photo[-1].file_id; file_type = "photo"
    elif message.audio: file_id = message.audio.file_id; file_type = "audio"
    elif message.voice: file_id = message.voice.file_id; file_type = "voice"
    elif message.sticker: file_id = message.sticker.file_id; file_type = "sticker"

    user_id_str = str(message.from_user.id)
    
    # --- BATCH MODE CHECK ---
    if get_batch_status(user_id_str) == 'on':
        # Batch list ko MongoDB mein store karein
        batch_key = f"batch_{user_id_str}"
        batch_doc = coll_files.find_one({"_id": batch_key})
        batch_list = batch_doc.get('files', []) if batch_doc else []
        
        batch_list.append({'id': file_id, 'type': file_type})
        
        coll_files.update_one(
            {"_id": batch_key}, 
            {"$set": {"type": "temp_batch", "files": batch_list, "owner": user_id_str}},
            upsert=True
        )

        bot.reply_to(message, f"✅ File batch mein add ho gayi! Total files: {len(batch_list)}")
        return
        
    # --- NORMAL MODE ---
    current_counter = get_next_counter() # MongoDB se counter liya
    custom_link = f"file_{current_counter}"
    
    file_info = {'_id': custom_link, 'type': file_type, 'id': file_id, 'owner': user_id_str} 
    coll_files.insert_one(file_info) # MongoDB mein store kiya

    bot_username = bot.get_me().username 
    bot.reply_to(message, 
                 f"✅ File Saved!\n\nAapka **Unique Link** hai -> `{custom_link}`\n\n"
                 f"🔗 **Ready-to-use Deep Link (Copy karke use karein):**\n"
                 f"`https://t.me/{bot_username}?start={custom_link}`"
                )

# --- BATCH COMMANDS (MongoDB version) ---
@bot.message_handler(commands=['batch'])
def toggle_batch_mode(message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        bot.reply_to(message, "❌ Sorry, yeh command sirf Admin ke liye hai.")
        return
        
    user_id_str = str(user_id)
    if get_batch_status(user_id) == 'off':
        set_batch_status(user_id, 'on')
        # Temporary batch list start karein
        coll_files.delete_one({"_id": f"batch_{user_id_str}"})
        bot.reply_to(message, "🟢 **Batch Mode ON ho gaya!** Ab files forward karein. Jab ho jaaye, to `/endbatch` type karein.")
    else:
        set_batch_status(user_id, 'off')
        coll_files.delete_one({"_id": f"batch_{user_id_str}"})
        bot.reply_to(message, "🔴 **Batch Mode OFF ho gaya.**")

@bot.message_handler(commands=['endbatch'])
def end_batch_mode(message):
    user_id = message.from_user.id
    if user_id != ADMIN_ID:
        bot.reply_to(message, "❌ Sorry, yeh command sirf Admin ke liye hai.")
        return
        
    user_id_str = str(user_id)
    if get_batch_status(user_id) == 'off':
        bot.reply_to(message, "❌ Batch Mode pehle se hi OFF hai.")
        return

    batch_key = f"batch_{user_id_str}"
    batch_doc = coll_files.find_one({"_id": batch_key})
    batch_list = batch_doc.get('files', []) if batch_doc else []
    
    if not batch_list:
        set_batch_status(user_id, 'off')
        coll_files.delete_one({"_id": batch_key})
        bot.reply_to(message, "⚠️ Batch mein koi files nahi mili. Batch Mode OFF ho gaya.")
        return

    current_counter = get_next_counter() 
    custom_link = f"batch_{current_counter}"
    
    # Final batch document ko coll_files mein insert karein
    coll_files.insert_one({'_id': custom_link, 'type': 'batch', 'files': batch_list, 'owner': user_id_str})
    
    # Batch status aur temporary data clear karein
    set_batch_status(user_id, 'off')
    coll_files.delete_one({"_id": batch_key})

    bot_username = bot.get_me().username
    bot.reply_to(message, 
                 f"🎉 **Batch Complete!** {len(batch_list)} files saved.\n\n"
                 f"Aapka **Unique Batch Link** hai -> `{custom_link}`\n\n"
                 f"🔗 **Ready-to-use Deep Link:**\n"
                 f"`https://t.me/{bot_username}?start={custom_link}`"
                )

# --- Link Triggering (MongoDB Version) ---
@bot.message_handler(func=lambda message: message.text.startswith('file_') or message.text.startswith('batch_'))
def send_file_by_link(message):
    link = message.text
    chat_id = message.chat.id
    
    file_info = coll_files.find_one({"_id": link}) # MongoDB se fetch

    if file_info:
        file_type = file_info.get('type')
        
        try:
            bot.reply_to(message, "...")
            
            if file_type == "batch":
                batch_files = file_info['files']
                for f in batch_files:
                    # ... (send_document/send_video/etc. logic same as previous response) ...
                    if f['type'] == "document": bot.send_document(chat_id, f['id'])
                    elif f['type'] == "video": bot.send_video(chat_id, f['id'])
                    elif f['type'] == "photo": bot.send_photo(chat_id, f['id'])
                    elif f['type'] == "audio": bot.send_audio(chat_id, f['id'])
                    elif f['type'] == "voice": bot.send_voice(chat_id, f['id'])
                    elif f['type'] == "sticker": bot.send_sticker(chat_id, f['id'])
                
            else:
                file_id = file_info['id']
                # ... (Single file send logic same as previous response) ...
                if file_type == "document": bot.send_document(chat_id, file_id)
                elif file_type == "video": bot.send_video(chat_id, file_id)
                elif file_type == "photo": bot.send_photo(chat_id, file_id)
                elif file_type == "audio": bot.send_audio(chat_id, file_id)
                elif file_type == "voice": bot.send_voice(chat_id, file_id)
                elif file_type == "sticker": bot.send_sticker(chat_id, file_id)

        except Exception as e:
            bot.reply_to(message, f"Error: File bhejte samay dikkat aayi: {e}")
            
    else:
        bot.reply_to(message, "❌ Invalid link. Aisa koi link exist nahi karta.")
        
# --- START, ECHO and UPTIME (Same as previous response) ---

@bot.message_handler(commands=['start'])
def send_welcome(message):
    if len(message.text.split()) > 1:
        deep_link_payload = message.text.split()[1] 
        message.text = deep_link_payload 
        send_file_by_link(message) 
    else:
        bot.reply_to(message, "👋 **Welcome!** Mai aapka Personal File Host Bot hu. Files store karne ke liye mujhe **file bhejein**.\nAdmin commands: `/batch`, `/endbatch`")

@bot.message_handler(func=lambda message: True)
def echo_all(message):
    bot.reply_to(message, "Please mujhe koi file bhejein ya file ka link bhejein.")

app = Flask(__name__)
@app.route('/')
def home():
    return "I am a Telegram bot, and I'm alive!"

def run(): app.run(host='0.0.0.0',port=int(os.environ.get('PORT', 8080))) # Use PORT env var
def keep_alive(): t = Thread(target=run); t.start()

keep_alive() 
print("Bot is running...")
bot.infinity_polling()

