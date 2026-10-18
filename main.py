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
    return "112 Acil Triyaj Sistemi 7/24 Aktif!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# --- 2. DISCORD BOT AYARLARI ---
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Hafıza Veritabanı
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

# --- 4. MESAJ DİNLEME VE YAPAY ZEKA BAĞLAMI ---
@bot.event
async def on_message(message):
    # Kendi mesajlarını ve komutları atla
    if message.author.bot or message.content.startswith('!'):
        await bot.process_commands(message)
        return

    # Kedy'nin konuyu anlaması için geçmiş çağrı özetlerini topla (Son 5 çağrı)
    recent_summaries = "\n".join([f"- {v['summary']}" for v in list(message_db.values())[-5:]])
    context_text = f"Mevcut Acil Durum Bağlamı (Son Çağrılar):\n{recent_summaries}\n\n" if recent_summaries else "Henüz geçmiş çağrı yok.\n\n"

    # 112 Acil Çağrı Sistemi Promptu (100.000 üzerinden)
    ai_prompt = f"""Sen bir 112 Acil Çağrı Merkezi triyaj yapay zekasısın.
    Görevin yeni gelen ihbarın aciliyetini (ölüm, yaralanma, yangın, kalp krizi vs.) 0 ile 100.000 arasında puanlamaktır.
    Alakasız puanlama yapmamak için aşağıdaki geçmiş çağrı özetlerini (bağlamı) incele ve yeni çağrının aciliyetine ona göre karar ver.

    {context_text}
    Yeni Çağrı / İhbar: "{message.content}"
    
    Lütfen yanıtını SADECE şu JSON formatında ver (başka hiçbir metin ekleme):
    {{"puan": 85000, "ozet": "Kısa vaka özeti (Maks 5 kelime)"}}
    """

    # Asenkron AI İsteği
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(None, score_message_with_kedy, ai_prompt)
    
    try:
        ai_content = response['choices'][0]['message']['content']
        # Markdown kod bloklarını temizle
        ai_content = ai_content.replace('```json', '').replace('```', '').strip()
        data = json.loads(ai_content)
        
        puan = int(data.get("puan", 0))
        ozet = data.get("ozet", "Özet çıkarılamadı")
        
        # Hafızaya Kaydet
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

# --- 5. KOMUTLAR ---

# Komut 1: !kod (Sıralama)
@bot.command(name="kod")
async def kod(ctx):
    if not message_db:
        await ctx.send("📭 Henüz puanlanmış bir çağrı bulunmuyor.")
        return

    sorted_messages = sorted(message_db.items(), key=lambda x: x[1]['score'], reverse=True)[:10]
    
    embed = discord.Embed(title="🚑 112 ACİL ÇAĞRI TRİYAJ SIRALAMASI", color=discord.Color.red())
    for msg_id, data in sorted_messages:
        desc = f"**Puan:** {data['score']}/100.000 | 🕒 {data['time']} | 👤 {data['author']}\n📝 **Özet:** {data['summary']}\n🔑 **ID:** {msg_id}"
        embed.add_field(name="🚨 İhbar", value=desc, inline=False)
        
    await ctx.send(embed=embed)

# Komut 2: !duzenle (Genişletilmiş Düzenleme - Puan veya Özet)
@bot.command(name="duzenle")
@commands.has_permissions(manage_messages=True)
async def duzenle(ctx, tip: str, mesaj_id: str, *, yeni_deger: str):
    if mesaj_id not in message_db:
        await ctx.send("❌ Bu ID'ye sahip bir ihbar bulunamadı.")
        return
        
    if tip.lower() == "puan":
        try:
            message_db[mesaj_id]["score"] = int(yeni_deger)
            await ctx.send(f"✅ **{mesaj_id}** ID'li ihbarın önceliği **{yeni_deger}/100.000** olarak güncellendi.")
        except ValueError:
            await ctx.send("❌ Lütfen puan için geçerli bir sayı girin.")
    elif tip.lower() == "ozet":
        message_db[mesaj_id]["summary"] = yeni_deger
        await ctx.send(f"✅ **{mesaj_id}** ID'li ihbarın özeti güncellendi:\n*{yeni_deger}*")
    else:
        await ctx.send("❌ Hatalı kullanım. \nÖrnekler:\n`!duzenle puan <ID> 95000`\n`!duzenle ozet <ID> Yeni özet metni`")

# Komut 3: !sil (Tekil ID bazlı mesaj silme)
@bot.command(name="sil")
@commands.has_permissions(manage_messages=True)
async def sil(ctx, mesaj_id: str):
    if mesaj_id in message_db:
        del message_db[mesaj_id]
        await ctx.send(f"🗑️ **{mesaj_id}** ID'li ihbar sistemden tamamen silindi.")
    else:
        await ctx.send("❌ Bu ID'ye sahip bir ihbar bulunamadı.")

# Komut 4: !sifirla (Tüm DB'yi temizleme)
@bot.command(name="sifirla")
@commands.has_permissions(manage_messages=True)
async def sifirla(ctx):
    message_db.clear()
    await ctx.send("🧹 **Tüm 112 Acil Triyaj hafızası ve puanlamalar başarıyla sıfırlandı!**")

# Komut 5: !sohbetisil (Discord kanalını temizleme)
@bot.command(name="sohbetisil")
@commands.has_permissions(manage_messages=True)
async def sohbetisil(ctx, miktar: int = 100):
    await ctx.channel.purge(limit=miktar + 1)
    # Temizlendi bilgisini 3 saniye gösterip siler
    msg = await ctx.send(f"🧨 Son {miktar} mesaj kanaldan temizlendi.")
    await asyncio.sleep(3)
    await msg.delete()

# Yetki Hatası Yakalayıcı
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("🚫 Bu komutu kullanmak için `Mesajları Yönet` yetkisine sahip bir moderatör olmalısınız.")

# --- 6. BAŞLATMA ---
if __name__ == "__main__":
    threading.Thread(target=run_flask).start()
    bot.run(DISCORD_TOKEN)
