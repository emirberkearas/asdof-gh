import discord
from discord.ext import commands
import requests
import os
import json
import asyncio
import threading
from flask import Flask

# --- 1. RENDER 7/24 UYANIK TUTMA (FLASK) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "112 Acil Çağrı Triyaj Sistemi 7/24 Aktif!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# --- 2. DISCORD BOT AYARLARI ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Hafıza Veritabanı (RAM)
message_db = {}

# Ortam Değişkenleri
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
KEDY_API_KEY = os.environ.get("KEDY_API_KEY")

# --- 3. KEDY AI İSTEK FONKSİYONU ---
def score_message_with_kedy(prompt):
    try:
        response = requests.post(
            "https://api.kedy.dev/v1/chat/completions",
            json={
                "model": "novaq",
                "messages": [{"role": "user", "content": prompt}],
            },
            headers={
                "Authorization": f"Bearer {KEDY_API_KEY}",
                "Content-Type": "application/json"
            },
            timeout=15
        )
        return response.json()
    except Exception as e:
        print("API Hatası:", e)
        return None

# --- 4. MESAJ DİNLEME VE TRİYAJ ANALİZİ ---
@bot.event
async def on_message(message):
    if message.author.bot or message.content.startswith('!'):
        await bot.process_commands(message)
        return

    # Hafızadaki mevcut acil durum özetlerini bağlam olarak topla
    recent_summaries = "\n".join([f"- {v['summary']} (Puan: {v['score']})" for v in list(message_db.values())[-5:]])
    context_text = f"Sistemdeki Son İhbarlar:\n{recent_summaries}\n\n" if recent_summaries else "Henüz aktif ihbar yok.\n\n"

    # GÜÇLENDİRİLMİŞ 112 TRİYAJ PROMPTU (SIKI PUANLAMA KURALLARI)
    ai_prompt = f"""Sen 112 Acil Çağrı Merkezi için çalışan son derece strict (sıkı) bir yapay zekâ triyaj uzmanısın.
Görevin, gelen ihbarın HAYATİ ACİLİYETİNİ 0 ile 100.000 arasında puanlamaktır.

STRICT PUANLAMA KURALLARI:
1. GERÇEK ACİL DURUMLAR (80.000 - 100.000 Puan): Kalp krizi, ağır yaralanma, bilinç kaybı, yangın, silahlı çatışma, trafik kazası, nefes darlığı.
2. ORTA DERECELİ ACİL (30.000 - 79.999 Puan): Hafif yaralanma, küçük ev kazaları, panik atağı, maddi hasarlı kaza.
3. ASILSIZ / BOŞ / EŞYA / TROLL İHBARLAR (0 - 5.000 Puan): Tost makinesi, bilgisayar, bozuk eşya, annemin kızması, sohbet etme, troller veya 112 hattını meşgul eden saçma durumlar. BUNLARA KESİNLİKLE YÜKSEK PUAN VERME!

Mevcut İhbar Bağlamı:
{context_text}

Gelen Yeni İhbar: "{message.content}"

Lütfen SADECE aşağıdaki JSON formatında yanıt ver (ekstra hiçbir metin/açıklama ekleme):
{{"puan": 100, "ozet": "Kısa vaka özeti (maksimum 5 kelime)"}}
"""

    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(None, score_message_with_kedy, ai_prompt)
    
    try:
        ai_content = response['choices'][0]['message']['content']
        ai_content = ai_content.replace('```json', '').replace('```', '').strip()
        data = json.loads(ai_content)
        
        puan = int(data.get("puan", 0))
        ozet = data.get("ozet", "Özet çıkarılamadı")
        
        message_db[str(message.id)] = {
            "author": message.author.display_name,
            "content": message.content,
            "score": puan,
            "summary": ozet,
            "time": message.created_at.strftime("%H:%M")
        }
    except Exception as e:
        print("Yapay Zeka Ayrıştırma Hatası:", e)

    await bot.process_commands(message)

# --- 5. MODERASYON VE TRİYAJ KOMUTLARI ---

@bot.command(name="kod")
async def kod(ctx):
    if not message_db:
        await ctx.send("📭 Henüz kayıtlı bir acil çağrı ihbarı bulunmuyor.")
        return

    sorted_messages = sorted(message_db.items(), key=lambda x: x[1]['score'], reverse=True)[:10]
    
    embed = discord.Embed(
        title="🚑 112 ACİL ÇAĞRI TRİYAJ ÖNCELİK SIRALAMASI (100.000 ÜZERİNDEN)", 
        color=discord.Color.red()
    )
    for msg_id, data in sorted_messages:
        desc = f"**Puan:** {data['score']}/100.000 | 🕒 {data['time']} | 👤 {data['author']}\n📝 **Özet:** {data['summary']}\n🔑 **ID:** `{msg_id}`"
        embed.add_field(name="🚨 İhbar", value=desc, inline=False)
        
    await ctx.send(embed=embed)

@bot.command(name="duzenle")
@commands.has_permissions(manage_messages=True)
async def duzenle(ctx, tip: str, mesaj_id: str, *, yeni_deger: str):
    if mesaj_id not in message_db:
        await ctx.send("❌ Bu ID'ye sahip bir ihbar bulunamadı.")
        return
        
    tip_clean = tip.lower()
    if tip_clean == "puan":
        try:
            message_db[mesaj_id]["score"] = int(yeni_deger)
            await ctx.send(f"✅ **`{mesaj_id}`** ID'li ihbarın puanı **{yeni_deger}/100.000** olarak güncellendi.")
        except ValueError:
            await ctx.send("❌ Puan için geçerli bir sayı giriniz.")
    elif tip_clean == "ozet":
        message_db[mesaj_id]["summary"] = yeni_deger
        await ctx.send(f"✅ **`{mesaj_id}`** ID'li ihbarın özeti güncellendi:\n*{yeni_deger}*")
    else:
        await ctx.send("❌ Hatalı kullanım.\nKullanım Şekli:\n`!duzenle puan <ID> <YeniPuan>`\n`!duzenle ozet <ID> <YeniÖzet>`")

@bot.command(name="sil")
@commands.has_permissions(manage_messages=True)
async def sil(ctx, mesaj_id: str):
    if mesaj_id in message_db:
        del message_db[mesaj_id]
        await ctx.send(f"🗑️ **`{mesaj_id}`** ID'li ihbar triyaj listesinden silindi.")
    else:
        await ctx.send("❌ Bu ID'ye sahip bir ihbar bulunamadı.")

@bot.command(name="sifirla")
@commands.has_permissions(manage_messages=True)
async def sifirla(ctx):
    message_db.clear()
    await ctx.send("🧹 **Tüm 112 Acil Triyaj puanlama hafızası sıfırlandı!**")

@bot.command(name="sohbetisil")
@commands.has_permissions(manage_messages=True)
async def sohbetisil(ctx, miktar: int = 100):
    await ctx.channel.purge(limit=miktar + 1)
    msg = await ctx.send(f"🧨 Son {miktar} mesaj kanaldan temizlendi.")
    await asyncio.sleep(3)
    await msg.delete()

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("🚫 Bu moderasyon komutunu kullanmak için `Mesajları Yönet` yetkisi gereklidir.")

# --- 6. UYGULAMAYI BAŞLATMA ---
if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    bot.run(DISCORD_TOKEN)
