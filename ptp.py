import sys
import os
import time
import asyncio
import threading
import logging
from datetime import datetime
import socket  # Potrzebne do pobrania nazwy komputera
import subprocess
import winreg

# GUI Imports
import tkinter as tk
from tkinter import scrolledtext, messagebox, simpledialog

# Bot Discord & Logic Imports
import discord
from discord.ext import commands, tasks
import pygetwindow as gw
import pyautogui
from PIL import ImageGrab
import keyboard
import certifi
import aiohttp
from dotenv import load_dotenv

# Wczytanie konfiguracji z pliku .env
load_dotenv()

# --- REJESTRACJA GLOBALNEJ NAZWY PC ---
PC_NAME = os.getenv('COMPUTER_NAME', 'Nieznany_PC')

# --- FUNKCJA BEZPIECZNEGO WYKRYWANIA I ZMIANY NAZWY ---
def check_and_ask_for_name_change(main_root):
    global PC_NAME
    system_pc_name = socket.gethostname()
    PC_NAME = system_pc_name  # Domyślnie przypisujemy nazwę z systemu
    
    # Sprawdzamy czy nazwa zaczyna się od DESKTOP- lub WIN-
    if system_pc_name.upper().startswith("DESKTOP-") or system_pc_name.upper().startswith("WIN-"):
        
        # Tworzymy okno potomne (Toplevel) zintegrowane z główną pętlą GUI
        ask_win = tk.Toplevel(main_root)
        ask_win.title("Wykryto domyślną nazwę komputera")
        ask_win.geometry("400x150")
        ask_win.attributes("-topmost", True)
        
        # Wyśrodkowanie okienka na ekranie
        ask_win.update_idletasks()
        width = ask_win.winfo_width()
        height = ask_win.winfo_height()
        x = (ask_win.winfo_screenwidth() // 2) - (width // 2)
        y = (ask_win.winfo_screenheight() // 2) - (height // 2)
        ask_win.geometry(f'{width}x{height}+{x}+{y}')

        decision = {"action_taken": False}
        
        def on_yes():
            decision["action_taken"] = True
            ask_win.destroy()
            # Wywołanie okienka wpisywania nazwy
            new_name = simpledialog.askstring("Nowa nazwa", "Podaj nową nazwę dla tego komputera:", parent=main_root)
            if new_name and new_name.strip():
                global PC_NAME
                PC_NAME = new_name.strip()
                main_root.title(f"PC: {PC_NAME}")
                log_d(f"Nazwa komputera zmieniona na: {PC_NAME}")

        def on_no():
            decision["action_taken"] = True
            ask_win.destroy()
            log_d(f"Pozostawiono domyślną nazwę komputera: {PC_NAME}")

        label_text = tk.StringVar()
        label_text.set(f"Twój PC to: {system_pc_name}\nCzy chcesz zmienić tę nazwę w programie?\nAutomatyczne pominięcie za: 5s")
        lbl = tk.Label(ask_win, textvariable=label_text, pady=10)
        lbl.pack()
        
        btn_frame = tk.Frame(ask_win)
        btn_frame.pack(pady=10)
        
        tk.Button(btn_frame, text="Tak", width=10, command=on_yes).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="Nie", width=10, command=on_no).pack(side=tk.LEFT, padx=10)
        
        # Odliczanie 5 sekund za pomocą mechanizmu .after (nie zamraża okna)
        def countdown(remaining):
            if decision["action_taken"]:
                return
            if remaining <= 0:
                if not decision["action_taken"]:
                    decision["action_taken"] = True
                    ask_win.destroy()
                    log_d(f"Czas minął. Pozostawiono nazwę: {PC_NAME}")
                return
            
            label_text.set(f"Twój PC to: {system_pc_name}\nCzy chcesz zmienić tę nazwę w programie?\nAutomatyczne pominięcie za: {remaining}s")
            main_root.after(1000, lambda: countdown(remaining - 1))

        countdown(5)
        
        # Blokada interakcji z oknem głównym, dopóki decyzja nie zapadnie
        ask_win.transient(main_root)
        ask_win.grab_set()
        main_root.wait_window(ask_win)

# --- KONFIGURACJA ZMIENNYCH ---
TOKEN = os.getenv('DISCORD_TOKEN')
PREFIX = "!"
CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID', 0))
IS_COORDINATOR = os.getenv('IS_COORDINATOR', 'false').lower() == 'true'
STREAMERS_URL = os.getenv('STREAMERS_URL', 'https://example.com/streamers.txt')
INTERVAL = int(os.getenv('MONITOR_INTERVAL_MINUTES', 2))
TWITCH_CLIENT_ID = os.getenv('TWITCH_CLIENT_ID')
TWITCH_CLIENT_SECRET = os.getenv('TWITCH_CLIENT_SECRET')

# --- SZTYWNE USTAWIENIA REGIONU KLIKACZA ---
X1, Y1 = 945, 585
X2, Y2 = 1277, 675
REGION_CLICKER = (X1, Y1, X2, Y2)

os.environ['SSL_CERT_FILE'] = certifi.where()

# Stany globalne
pc_statuses = {}
CURRENTLY_BUSY = False
CURRENT_STREAMER = None
clicker_running = True  # Klikacz uruchomiony automatycznie od startu

# --- LOGGERY ---
logger_discord = logging.getLogger('DiscordBot')
logger_discord.setLevel(logging.INFO)
logger_clicker = logging.getLogger('TwitchClicker')
logger_clicker.setLevel(logging.INFO)

class TextHandler(logging.Handler):
    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget
    def emit(self, record):
        msg = self.format(record)
        def append():
            self.text_widget.configure(state='normal')
            self.text_widget.insert(tk.END, msg + '\n')
            self.text_widget.configure(state='disabled')
            self.text_widget.yview(tk.END)
        self.text_widget.after(0, append)

def log_d(message):
    logger_discord.info(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")

def log_c(message):
    logger_clicker.info(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")

# --- FUNKCJE AUTOMATYCZNEGO URUCHAMIANIA PRZEGLĄDARKI ---
def znajdz_przegladarke():
    """Przeszukuje rejestr Windows w poszukiwaniu znanych przeglądarek."""
    szukane_przegladarki = [
        "Google Chrome", "Brave", "Opera", "Opera GX", 
        "Firefox", "Chromium", "Waterfox"
    ]
    
    sciezka_rejestru = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
    
    for przegladarka in szukane_przegladarki:
        exe_name = {
            "Google Chrome": "chrome.exe",
            "Brave": "brave.exe",
            "Opera": "opera.exe",
            "Opera GX": "opera.exe",
            "Firefox": "firefox.exe",
            "Chromium": "chromium.exe",
            "Waterfox": "waterfox.exe"
        }.get(przegladarka)

        try:
            for root_reg in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    klucz = winreg.OpenKey(root_reg, f"{sciezka_rejestru}\\{exe_name}")
                    sciezka, _ = winreg.QueryValueEx(klucz, "")
                    winreg.CloseKey(klucz)
                    if os.path.exists(sciezka):
                        return sciezka, przegladarka
                except FileNotFoundError:
                    continue
        except Exception:
            pass

    return None, None

def maksymalizuj_okno_przegladarki(nazwa_przegladarki):
    """Szuka okna aktywnej przeglądarki i wymusza jego maksymalizację."""
    log_c("Próbuję zmaksymalizować okno przeglądarki...")
    
    frazy_tytulu = [nazwa_przegladarki, "GitHub Pages", "start.html"]
    if "Chrome" in nazwa_przegladarki:
        frazy_tytulu.append("Google Chrome")

    for _ in range(10): 
        time.sleep(0.5)
        for okno in gw.getAllWindows():
            if any(fraza.lower() in okno.title.lower() for fraza in frazy_tytulu if okno.title):
                try:
                    okno.maximize()
                    log_c(f"Zmaksymalizowano okno: {okno.title}")
                    return True
                except Exception as e:
                    log_c(f"Nie udało się zmaksymalizować: {e}")
                    return False
    log_c("Nie znaleziono aktywnego okna przeglądarki do zmaksymalizowania.")
    return False

def uruchom_autostart():
    """Wątek uruchamiający przeglądarkę ze wskazaną stroną startową."""
    URL = "https://itsmatisio.github.io/start.html"

    # Automatyczne szukanie i odpalanie przeglądarki
    browser_path, nazwa_przegladarki = znajdz_przegladarke()
    
    if browser_path:
        log_c(f"Autostart: Uruchamiam {nazwa_przegladarki}")
        try:
            subprocess.Popen([browser_path, URL])
            maksymalizuj_okno_przegladarki(nazwa_przegladarki)
        except Exception as e:
            log_c(f"Problem z uruchomieniem przeglądarki: {e}")
    else:
        log_c("Nie wykryto przeglądarki z listy, odpalam domyślną...")
        import webbrowser
        webbrowser.open(URL)

    log_c("Autostart: Sekwencja uruchamiania przeglądarki zakończona.")

# --- BOT DISCORD ---
intents = discord.Intents.default()
intents.message_content = True 
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

def process_browser(url):
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

@bot.event
async def on_ready():
    log_d(f'--- BOT URUCHOMIONY: {PC_NAME} ---')
    if IS_COORDINATOR:
        twitch_monitor.change_interval(minutes=INTERVAL)
        twitch_monitor.start()

@tasks.loop(minutes=2)
async def twitch_monitor():
    global pc_statuses
    try:
        channel = bot.get_channel(CHANNEL_ID)
        if not channel: return
        await channel.send("!raport_statusu")
        await asyncio.sleep(5) 
    except Exception as e:
        log_d(f"Błąd koordynatora: {e}")

@bot.event
async def on_message(message):
    global pc_statuses
    if message.channel.id == CHANNEL_ID:
        log_d(f"{message.author.name}: {message.content}")
    if IS_COORDINATOR and message.content.startswith("RAPORT:"):
        try:
            parts = message.content.split(" | ")
            pc_id = parts[0].replace("RAPORT: ", "").strip()
            status = parts[1].replace("STATUS: ", "").strip()
            pc_statuses[pc_id] = {"status": status}
        except: pass
    await bot.process_commands(message)

@bot.command(name="raport_statusu")
async def raport_statusu(ctx):
    status_str = "ZAJĘTY" if CURRENTLY_BUSY else "WOLNY"
    await ctx.send(f"RAPORT: {PC_NAME} | STATUS: {status_str} | STREAMER: {CURRENT_STREAMER}")

@bot.command(name="odpal_stream")
async def odpal_stream(ctx, pc_name: str, url: str, streamer_name: str):
    global CURRENTLY_BUSY, CURRENT_STREAMER
    if pc_name.lower() != PC_NAME.lower() or CURRENTLY_BUSY: return
    title = process_browser(url)
    if title:
        CURRENTLY_BUSY = True
        CURRENT_STREAMER = streamer_name.lower()
        log_d(f"Odpalono: {streamer_name}")

@bot.command(name="zamknij_stream")
async def zamknij_stream(ctx, pc_name: str):
    global CURRENTLY_BUSY, CURRENT_STREAMER
    if pc_name.lower() != PC_NAME.lower(): return
    pyautogui.hotkey('ctrl', 'w')
    CURRENTLY_BUSY = False
    CURRENT_STREAMER = None
    log_d("Zamknięto stream.")

# --- TWITCH CLICKER LOGIC ---
def twitch_clicker_loop():
    global clicker_running
    TARGET_COLOR = (0, 219, 132) 
    TOLERANCE = 35 
    MIN_PIXELS = 15
    OFFSET = 80

    if clicker_running:
        log_c("Klikacz uruchomiony automatycznie przy starcie.")

    while True:
        if not clicker_running:
            time.sleep(1)
            continue

        if keyboard.is_pressed('q'):
            clicker_running = False
            root.after(0, lambda: btn_click.config(text="Uruchom Klikacza", bg="lightgreen"))
            log_c("Wyłączono klikacza (klawisz Q)")
            continue

        try:
            img = ImageGrab.grab(bbox=REGION_CLICKER, all_screens=True).convert('RGB')
            width, height = img.size
            found = False
            
            for x in range(0, width, 5):
                for y in range(0, height, 5):
                    r, g, b = img.getpixel((x, y))
                    if all(abs(p - t) <= TOLERANCE for p, t in zip((r,g,b), TARGET_COLOR)):
                        check_count = 0
                        for dx in range(0, 10, 2):
                            for dy in range(0, 10, 2):
                                if x+dx < width and y+dy < height:
                                    pr, pg, pb = img.getpixel((x+dx, y+dy))
                                    if remove_ptp := all(abs(p-t) <= TOLERANCE for p,t in zip((pr,pg,pb), TARGET_COLOR)):
                                        check_count += 1
                        
                        if check_count > MIN_PIXELS:
                            real_x, real_y = x + REGION_CLICKER[0], y + REGION_CLICKER[1]
                            pyautogui.click(real_x, real_y)
                            log_c(f"Kliknięto przycisk w: {real_x}, {real_y}")
                            pyautogui.moveTo(max(real_x - OFFSET, REGION_CLICKER[0]), real_y)
                            time.sleep(0.5)
                            pyautogui.press('f5')
                            log_c("Strona odświeżona.")
                            found = True
                            time.sleep(5)
                            break
                if found: break
            time.sleep(0.5)
        except Exception as e:
            time.sleep(2)

# --- GUI ---
def toggle_clicker():
    global clicker_running
    clicker_running = not clicker_running
    btn_click.config(text="Zatrzymaj Klikacza" if clicker_running else "Uruchom Klikacza", 
                     bg="coral" if clicker_running else "lightgreen")
    log_c("Klikacz uruchomiony" if clicker_running else "Klikacz zatrzymany")

def start_bot_thread():
    def run():
        asyncio.run(bot.start(TOKEN))
    threading.Thread(target=run, daemon=True).start()
    btn_disc.config(state='disabled', text="Bot Discord Aktywny")

# --- INICJALIZACJA APLIKACJI (SEKWENCJA STARTOWA) ---
root = tk.Tk()
root.geometry("900x500")

# Automatyczne minimalizowanie przy starcie komputera
root.iconify() 

top = tk.Frame(root)
top.pack(pady=10)

btn_disc = tk.Button(top, text="Połącz Discord", command=start_bot_thread, bg="lightblue")
btn_disc.pack(side=tk.LEFT, padx=10)

btn_click = tk.Button(top, text="Zatrzymaj Klikacza", command=toggle_clicker, bg="coral")
btn_click.pack(side=tk.LEFT, padx=10)

tk.Label(top, text=f"Region skanowania: {X1, Y1} -> {X2, Y2}", fg="gray").pack(side=tk.LEFT, padx=10)

log_frame = tk.Frame(root)
log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

f1 = tk.LabelFrame(log_frame, text="Discord")
f1.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
txt_d = scrolledtext.ScrolledText(f1, state='disabled', bg="black", fg="lightgreen", font=("Consolas", 8))
txt_d.pack(fill=tk.BOTH, expand=True)

f2 = tk.LabelFrame(log_frame, text="Klikacz Twitch")
f2.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
txt_c = scrolledtext.ScrolledText(f2, state='disabled', bg="black", fg="orange", font=("Consolas", 8))
txt_c.pack(fill=tk.BOTH, expand=True)

logger_discord.addHandler(TextHandler(txt_d))
logger_clicker.addHandler(TextHandler(txt_c))

# 1. URUCHOM SPRAWDZENIE NAZWY (Wyświetli okienko Toplevel, jeśli zajdzie potrzeba)
check_and_ask_for_name_change(root)

# 2. USTAWIENIE TYTUŁU OKNA PO DECYZJI O NAZWIE
root.title(f"PC: {PC_NAME}")

# 3. URUCHOMIENIE PĘTLI KLIKACZA W TLE
threading.Thread(target=twitch_clicker_loop, daemon=True).start()

# 4. ZINTEGROWANY AUTOSTART (Sama Przeglądarka)
threading.Thread(target=uruchom_autostart, daemon=True).start()

# Automatyczne uruchomienie bota, jeśli token istnieje w .env
if TOKEN:
    start_bot_thread()

root.mainloop()
