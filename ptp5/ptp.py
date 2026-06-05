import discord
from discord.ext import commands, tasks
import pygetwindow as gw
import pyautogui
import asyncio
import os
import certifi
import aiohttp
from dotenv import load_dotenv

# Wczytanie konfiguracji z pliku .env
load_dotenv()

# Zmienne ogólne
TOKEN = os.getenv('DISCORD_TOKEN')
PC_NAME = os.getenv('COMPUTER_NAME', 'Nieznany_PC')
PREFIX = "!"

# ID Kanału pobierane bezpośrednio z .env (konwertowane na int)
CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID', 0))

# Zmienne Koordynatora
IS_COORDINATOR = os.getenv('IS_COORDINATOR', 'false').lower() == 'true'
STREAMERS_URL = os.getenv('STREAMERS_URL', 'https://example.com/streamers.txt')
INTERVAL = int(os.getenv('MONITOR_INTERVAL_MINUTES', 2))

# Zmienne Twitch API
TWITCH_CLIENT_ID = os.getenv('TWITCH_CLIENT_ID')
TWITCH_CLIENT_SECRET = os.getenv('TWITCH_CLIENT_SECRET')

# Fix dla SSL w systemie
os.environ['SSL_CERT_FILE'] = certifi.where()

# Intenty Discorda
intents = discord.Intents.default()
intents.message_content = True 

bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# Słowniki i flagi stanów
pc_statuses = {}
CURRENTLY_BUSY = False
CURRENT_STREAMER = None

def process_browser(url):
    """Funkcja sterująca przeglądarką"""
    potential_titles = ['chrome', 'firefox', 'edge', 'brave', 'opera', 'browser']
    target = None
    for win in gw.getAllWindows():
        if any(x in win.title.lower() for x in potential_titles) and win.title != "":
            target = win
            break
            
    if target:
        if target.isMinimized: target.restore()
        target.activate()
        target.maximize()
        pyautogui.sleep(0.5)
        pyautogui.hotkey('ctrl', 'l')
        pyautogui.write(url)
        pyautogui.press('enter')
        return target.title
    return None

async def get_twitch_access_token():
    """Pobiera token uwierzytelniający do Twitch API z obsługą błędów i bez SSL"""
    if not TWITCH_CLIENT_ID or not TWITCH_CLIENT_SECRET:
        print("[Koordynator] [BŁĄD TWITCH] Brak TWITCH_CLIENT_ID lub TWITCH_CLIENT_SECRET w pliku .env!")
        return None
        
    url = f"https://id.twitch.tv/oauth2/token?client_id={TWITCH_CLIENT_ID}&client_secret={TWITCH_CLIENT_SECRET}&grant_type=client_credentials"
    try:
        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.post(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("access_token")
                else:
                    print(f"[Koordynator] [BŁĄD TWITCH] Serwer Twitch zwrócił status: {response.status}")
                    print(f"[Koordynator] Szczegóły błędu: {await response.text()}")
                    return None
    except Exception as e:
        print(f"[Koordynator] [BŁĄD TWITCH] Nie można połączyć się z API Twitch: {e}")
    return None

async def check_live_streamers(streamers_list, token):
    """Sprawdza, którzy streamerzy z listy są LIVE (z pominięciem SSL)"""
    if not streamers_list or not token:
        return []
    
    headers = {
        "Client-ID": TWITCH_CLIENT_ID,
        "Authorization": f"Bearer {token}"
    }
    query = "&user_login=".join(streamers_list)
    url = f"https://api.twitch.tv/helix/streams?user_login={query}"
    
    try:
        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    return [stream['user_login'].lower() for stream in data['data']]
                else:
                    print(f"[Koordynator] [BŁĄD TWITCH] Nie udało się pobrać statusów live. Status: {response.status}")
    except Exception as e:
        print(f"[Koordynator] [BŁĄD TWITCH] Wyjątek podczas sprawdzania live: {e}")
    return []

async def fetch_streamers_from_web():
    """Pobiera tekstową listę streamerów z URL podanego w .env (z User-Agent i bez SSL)"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    try:
        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(STREAMERS_URL, headers=headers) as response:
                if response.status == 200:
                    text = await response.text()
                    lista = [line.strip().lower() for line in text.splitlines() if line.strip()]
                    print(f"[Koordynator] Pomyślnie pobrano {len(lista)} streamerów z URL.")
                    return lista
                else:
                    print(f"[Koordynator] [BŁĄD WWW] Serwer zwrócił status: {response.status} (Nie można pobrać listy)")
    except Exception as e:
        print(f"[Koordynator] [BŁ^\D WWW] Wyjątek podczas pobierania listy: {e}")
    return []

@bot.event
async def on_ready():
    print(f'--- BOT URUCHOMIONY NA: {PC_NAME} ---')
    if IS_COORDINATOR:
        if CHANNEL_ID == 0:
            print("[OSTRZEŻENIE] DISCORD_CHANNEL_ID w pliku .env jest niepoprawne lub równe 0!")
        print(f"Uruchamiam tryb Koordynatora sieci PC. Odświeżanie co {INTERVAL} min.")
        twitch_monitor.change_interval(minutes=INTERVAL)
        twitch_monitor.start()

# --- PĘTLA KOORDYNATORA ---
@tasks.loop(minutes=2)
async def twitch_monitor():
    global pc_statuses
    print("\n[Koordynator] --- ROZPOCZYNAM SPRAWDZANIE ---")
    
    try:
        channel = bot.get_channel(CHANNEL_ID)
        if not channel:
            print(f"[Koordynator] [BŁĄD] Nie można odnaleźć kanału o ID: {CHANNEL_ID}. Sprawdź plik .env!")
            return
            
        print("[Koordynator] Wysyłam prośbę o raporty do maszyn...")
        await channel.send("!raport_statusu")
        
        print("[Koordynator] Czekam 5 sekund na odpowiedzi od maszyn...")
        await asyncio.sleep(5) 
        
        print("[Koordynator] Pobieram listę streamerów z URL...")
        streamers = await fetch_streamers_from_web()
        if not streamers:
            print("[Koordynator] Lista streamerów jest pusta. Przerywam cykl.")
            return
        
        print("[Koordynator] Loguję się do Twitch API...")
        twitch_token = await get_twitch_access_token()
        
        if not twitch_token:
            print("[Koordynator] Brak ważnego tokenu Twitch. Pomijam sprawdzanie streamów w tym cyklu.")
            return
            
        print("[Koordynator] Sprawdzam na Twitchu, kto jest LIVE...")
        live_streamers = await check_live_streamers(streamers, twitch_token)
        print(f"[Koordynator] Aktualnie LIVE: {live_streamers}")
        print(f"[Koordynator] Zarejestrowane maszyny w sieci: {list(pc_statuses.keys())}")
        
        # Przydzielanie maszyn
        for streamer in live_streamers:
            already_watched = any(info['streamer'] == streamer for info in pc_statuses.values())
            
            if not already_watched:
                free_pc = None
                for pc_id, info in pc_statuses.items():
                    if info['status'] == "WOLNY":
                        free_pc = pc_id
                        break
                
                if free_pc:
                    print(f"[Koordynator] Przydzielam {free_pc} do oglądania {streamer}")
                    await channel.send(f"!odpal_stream {free_pc} https://twitch.tv/{streamer} {streamer}")
                    pc_statuses[free_pc] = {"status": "ZAJĘTY", "streamer": streamer}
                else:
                    print(f"[Koordynator] Brak wolnych PC dla: {streamer}")

        # Zwalnianie maszyn
        for pc_id, info in pc_statuses.items():
            if info['status'] == "ZAJĘTY" and info['streamer'] not in live_streamers:
                print(f"[Koordynator] Streamer {info['streamer']} wyłączył live. Zwalniam {pc_id}")
                await channel.send(f"!zamknij_stream {pc_id}")
                
        print("[Koordynator] --- ZAKOŃCZONO CYKL ---")

    except Exception as main_error:
        print(f"[Koordynator] [KRYTYCZNY BŁĄD PĘTLI]: {main_error}")
        print("[Koordynator] Pętla spróbuje ponownie za 2 minuty...")

# --- NASŁUCHIWANIE WIADOMOŚCI ---
@bot.event
async def on_message(message):
    global pc_statuses
    
    # DEBUG: Wyświetla w konsoli KAŻDĄ wiadomość z wybranego kanału
    if message.channel.id == CHANNEL_ID:
        print(f"[DEBUG KANAŁU] {message.author}: {message.content}")
    
    # Koordynator nasłuchuje raportów (od wszystkich użytkowników i botów)
    if IS_COORDINATOR and message.content.startswith("RAPORT:"):
        try:
            parts = message.content.split(" | ")
            pc_id = parts[0].replace("RAPORT: ", "").strip()
            status = parts[1].replace("STATUS: ", "").strip()
            streamer = parts[2].replace("STREAMER: ", "").strip()
            streamer = None if streamer == "None" else streamer
            
            pc_statuses[pc_id] = {"status": status, "streamer": streamer}
            print(f"[Koordynator] ✅ ZAREJESTROWANO STATUS MASZYNY: {pc_id} ({status})")
        except Exception as e:
            print(f"[Koordynator] Błąd parsowania raportu: {e}")

    # Przetwarzaj normalnie komendy zaczynające się od prefixu (!)
    if message.content.startswith(PREFIX):
        await bot.process_commands(message)

# --- KOMENDY DISCORDA ---

@bot.command(name="raport_statusu")
async def raport_statusu(ctx):
    status_str = "ZAJĘTY" if CURRENTLY_BUSY else "WOLNY"
    await ctx.send(f"RAPORT: {PC_NAME} | STATUS: {status_str} | STREAMER: {CURRENT_STREAMER}")

@bot.command(name="odpal_stream")
async def odpal_stream(ctx, pc_name: str, url: str, streamer_name: str):
    global CURRENTLY_BUSY, CURRENT_STREAMER
    if pc_name.lower() != PC_NAME.lower():
        return

    if CURRENTLY_BUSY:
        return

    try:
        window_title = process_browser(url)
        if window_title:
            CURRENTLY_BUSY = True
            CURRENT_STREAMER = streamer_name.lower()
            await ctx.send(f"-> [{PC_NAME}] Sukces. Oglądam {streamer_name}.")
        else:
            await ctx.send(f"BLAD: Nie znaleziono przegladarki na {PC_NAME}")
    except Exception as e:
        await ctx.send(f"BLAD na {PC_NAME}: {e}")

@bot.command(name="zamknij_stream")
async def zamknij_stream(ctx, pc_name: str):
    global CURRENTLY_BUSY, CURRENT_STREAMER
    if pc_name.lower() != PC_NAME.lower():
        return

    try:
        pyautogui.hotkey('ctrl', 'w') 
        await ctx.send(f"-> [{PC_NAME}] Zamknięto stream {CURRENT_STREAMER}. Jestem WOLNY.")
        CURRENTLY_BUSY = False
        CURRENT_STREAMER = None
    except Exception as e:
        await ctx.send(f"Bląd podczas zamykania na {PC_NAME}: {e}")

@bot.command(name="lista_pc")
async def lista_pc(ctx):
    await asyncio.sleep(1) 
    status_str = "ZAJĘTY" if CURRENTLY_BUSY else "WOLNY"
    await ctx.send(f"[ ONLINE ] Komputer: **{PC_NAME}** | Status: **{status_str}**")

@bot.command(name="screen")
async def screen(ctx, pc_name: str):
    if pc_name.lower() != PC_NAME.lower() and pc_name.lower() != "all":
        return
    try:
        ss_path = f"quick_{PC_NAME}.png"
        pyautogui.screenshot(ss_path)
        await ctx.send(f"Podglad z {PC_NAME}:", file=discord.File(ss_path))
        os.remove(ss_path)
    except Exception as e:
        await ctx.send(f"Blad screena na {PC_NAME}: {e}")

# --- URUCHOMIENIE BOTA ---
async def start_bot():
    connector = aiohttp.TCPConnector(ssl=False)
    async with bot:
        bot.http.connector = connector
        await bot.start(TOKEN)

if __name__ == "__main__":
    if TOKEN:
        asyncio.run(start_bot())
    else:
        print("Brak tokenu w pliku .env")