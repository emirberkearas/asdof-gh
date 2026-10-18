import discord
from discord.ext import commands
import requests
import os
import json
import asyncio
import threading
from flask import Flask
import matplotlib
matplotlib.use('Agg') # Sunucu ortamında ekran olmadan grafik çizmek için
import matplotlib.pyplot as plt
import io

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

    ai_prompt = f"""Sen 112 Acil Çağrı Merkezi triyaj uzmanısın.
Görevin, ihbarın HAYATİ TEHLİKESİNİ ve ACİLİYETİNİ 0.0 ile 100.0 arasında bir YÜZDE PUANI ile değerlendirmektir.

ACİLİYE SKALASI (0 - 100):
- 90.0 - 100.0: Bilinç kaybı, nefes alamama, kalp krizi, ağır yaralanma, yangın, silahlı vurulma.
- 50.0 - 89.9: Kırık, kaza, şiddetli ağrı, yüksek ateş.
- 10.0 - 49.9: Hafif durumlar, panik.
- 0.0 - 5.0: Tost makinesi, bozuk cihaz, geyik sohbet, troller, asılsız çağrılar.

Gelen İhbar: "{message.content}"

Lütfen SADECE aşağıdaki JSON formatında yanıt ver:
{{"puan": YUZDE_PUANI, "ozet": "Kısa vaka özeti (maksimum 5 kelime)"}}
"""

    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(None, score_message_with_kedy, ai_prompt)
    
    try:
        ai_content = response['choices'][0]['message']['content']
        ai_content = ai_content.replace('```json', '').replace('```', '').strip()
        data = json.loads(ai_content)
        
        raw_puan = float(data.get("puan", 0))
        final_puan = int(raw_puan * 1000)
        
        ozet = data.get("ozet", "Özet çıkarılamadı")
        
        message_db[str(message.id)] = {
            "author": message.author.display_name,
            "content": message.content,
            "score": final_puan,
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

# GRAFİK OLUŞTURMA KOMUTU (!chart) - HATA KORUMALI
@bot.command(name="chart")
async def chart(ctx):
    if not message_db:
        await ctx.send("📭 Grafik oluşturmak için henüz kayıtlı bir ihbar yok.")
        return

    msg = await ctx.send("⏳ **Grafik oluşturuluyor, lütfen bekleyin...**")

    try:
        sorted_items = sorted(message_db.items(), key=lambda x: x[1]['score'], reverse=True)[:10]
        sorted_items.reverse()

        labels = []
        scores = []
        colors = []

        for msg_id, data in sorted_items:
            label = f"[{data['time']} | {data['author']}] {data['summary']}"
            labels.append(label)
            scores.append(data['score'])
            
            if data['score'] >= 80000:
                colors.append('#e74c3c')
            elif data['score'] >= 40000:
                colors.append('#f39c12')
            else:
                colors.append('#2ecc71')

        plt.close('all') # Önceki grafikleri temizle
        fig, ax = plt.subplots(figsize=(10, max(4, len(labels) * 0.8)), facecolor='#2f3136')
        ax.set_facecolor('#36393f')

        bars = ax.barh(labels, scores, color=colors, height=0.5)

        for bar in bars:
            width = bar.get_width()
            ax.text(width + 1000, bar.get_y() + bar.get_height()/2, f'{int(width):,} Puan',
                    va='center', ha='left', color='white', fontweight='bold', fontsize=9)

        ax.set_xlim(0, 120000)
        ax.tick_params(colors='white', labelsize=9)
        ax.spines['bottom'].set_color('white')
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['left'].set_color('white')
        
        plt.title("🚑 112 ACİL ÇAĞRI TRİYAJ ACİLİYET GRAFİĞİ", color='white', fontsize=13, fontweight='bold', pad=15)
        plt.xlabel("Aciliyet Puanı (100.000 Üzerinden)", color='white', fontsize=10, labelpad=10)
        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=100, bbox_inches='tight', facecolor=fig.get_facecolor())
        buf.seek(0)
        plt.close(fig)

        file = discord.File(buf, filename="112_triyaj_grafigi.png")
        await msg.delete()
        await ctx.send(file=file)

    except Exception as e:
        await msg.edit(content=f"❌ **Grafik oluşturulurken bir hata oluştu:** `{str(e)}`")

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

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    bot.run(DISCORD_TOKEN)
