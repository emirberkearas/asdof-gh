import os
import re
import threading
import asyncio
import requests
from flask import Flask
import discord
from discord.ext import commands

# ==========================================
# 1. FLASK WEB SUNUCUSU (7/24 UYANIK KALMA MODÜLÜ)
# ==========================================
app = Flask(__name__)

@app.route('/')
def home():
    return "LegalBot & Puanlama Sistemi 7/24 Aktif!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    # Render'ın botu kapatmaması için web sunucusu arka planda çalışır
    app.run(host='0.0.0.0', port=port, use_reloader=False)

# ==========================================
# 2. AYARLAR VE HAFIZA VERİTABANI
# ==========================================
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
KEDY_API_KEY = os.environ.get("KEDY_API_KEY")

intents = discord.Intents.default()
intents.message_content = True  # Discord portalından bu izni açmayı unutma!
bot = commands.Bot(command_prefix="!", intents=intents)

# Geçici Bellek (RAM üzerinde çalışır)
# Yapı: { msg_id: {"author": "Ahmet", "time": "14:30", "content": "...", "score": 8500, "summary": "..."} }
message_db = {}

# ==========================================
# 3. KEDY AI ASENKRON PUANLAMA MOTORU
# ==========================================
async def evaluate_message_async(content):
    prompt = f"""
    Aşağıdaki mesajı incele: "{content}"
    1. Mesajın önemini 0-10000 arası puanla.
    2. Mesajın ne anlattığını max 4 kelimeyle özetle.
    SADECE ŞU FORMATTA YANIT VER:
    PUAN: [Sayı] | ÖZET: [Özet metni]
    """

    headers = {
        "Authorization": f"Bearer {KEDY_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "novaq",
        "messages": [{"role": "user", "content": prompt}]
    }

    try:
        # Botu dondurmamak için isteği ayrı thread'de atıyoruz (Çok sağlam kılan kısım burası)
        response = await asyncio.to_thread(
            requests.post,
            "https://api.kedy.dev/v1/chat/completions",
            json=payload,
            headers=headers,
            timeout=15
        )
        
        if response.status_code == 200:
            text = response.json()['choices'][0]['message']['content'].strip()
            match = re.search(r"PUAN:\s*(\d+)\s*\|\s*ÖZET:\s*(.*)", text)
            if match:
                return int(match.group(1)), match.group(2)
        
        return 0, "Değerlendirilemedi"
    except Exception as e:
        print(f"API Hatası: {e}")
        return 0, "Sistem Hatası"

# ==========================================
# 4. BOT OLAYLARI VE DİNLEME (EVENT)
# ==========================================
@bot.event
async def on_ready():
    print(f"✅ {bot.user} başarıyla bağlandı! Puanlama dinleniyor...")

@bot.event
async def on_message(message):
    # Kendi mesajlarını veya komutları (! ile başlayanları) puanlama
    if message.author.bot or message.content.startswith("!"):
        await bot.process_commands(message)
        return

    # Arka planda mesajı puanla
    score, summary = await evaluate_message_async(message.content)
    
    # Sadece 0'dan büyük puan alan mantıklı mesajları kaydet
    if score > 0:
        message_db[message.id] = {
            "author": message.author.display_name,
            "time": message.created_at.strftime("%H:%M"),
            "content": message.content,
            "score": score,
            "summary": summary
        }

    # Komutların çalışmaya devam etmesi için şart
    await bot.process_commands(message)

# ==========================================
# 5. KULLANILABİLİR KOMUTLAR
# ==========================================

# KOMUT 1: !kod (Sıralamayı Gösterir)
@bot.command(name="kod")
async def sirala(ctx):
    if not message_db:
        await ctx.send("📭 Henüz puanlanmış bir mesaj yok.")
        return

    # Puanlara göre büyükten küçüğe sıralama
    sorted_msgs = sorted(message_db.items(), key=lambda x: x[1]['score'], reverse=True)

    output = "🏆 **MESAJ ÖNEM SIRALAMASI (10.000 ÜZERİNDEN)** 🏆\n\n"
    for msg_id, data in sorted_msgs[:10]: # Sadece en iyi 10 mesajı gösterir (spamı engeller)
        output += f"🔹 **Puan: {data['score']}** | 🕒 `{data['time']}` | 👤 **{data['author']}**\n"
        output += f"📝 *Özet:* {data['summary']}\n"
        output += f"🔑 *ID:* `{msg_id}`\n\n"

    await ctx.send(output)

# KOMUT 2: !duzenle (Moderatörler Puan Değiştirir)
@bot.command(name="duzenle")
@commands.has_permissions(manage_messages=True)
async def duzenle(ctx, msg_id: int, yeni_puan: int):
    if msg_id in message_db:
        eski_puan = message_db[msg_id]['score']
        message_db[msg_id]['score'] = yeni_puan
        await ctx.send(f"✅ Başarılı! `{msg_id}` ID'li mesajın puanı **{eski_puan}** ➡️ **{yeni_puan}** olarak güncellendi.")
    else:
        await ctx.send("❌ Hata: Bu ID'ye ait bir mesaj bulunamadı.")

# Yetki hatası kontrolü
@duzenle.error
async def duzenle_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("🚫 Bu komutu sadece mesaj silme/yönetme yetkisi olan **Moderatörler** kullanabilir.")

# ==========================================
# 6. SİSTEMİ BAŞLATMA
# ==========================================
if __name__ == "__main__":
    # Flask sunucusunu ayrı bir kanalda (thread) başlatıyoruz
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Discord botunu başlatıyoruz
    bot.run(DISCORD_TOKEN)
