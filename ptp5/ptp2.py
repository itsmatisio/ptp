import sys
import os
import time

# --- IMPORTY ---
try:
    import pyautogui
    from PIL import ImageGrab
    import keyboard
except ImportError:
    print("Brak bibliotek! Zainstaluj: pip install pyautogui pillow keyboard")
    time.sleep(5)
    sys.exit()

# Ustawienia koloru (zielony przycisk Twitcha)
TARGET_COLOR = (0, 219, 132) 
TOLERANCE = 35 
MIN_PIXELS = 15
OFFSET = 80

def get_region():
    print("--- KONFIGURACJA REGIONU ---")
    print("1. Ustaw mysz w LEWYM GÓRNYM rogu i naciśnij 'S'")
    keyboard.wait('s')
    x1, y1 = pyautogui.position()
    print(f"Zapisano punkt 1: {x1}, {y1}")
    time.sleep(0.5)
    
    print("2. Ustaw mysz w PRAWYM DOLNYM rogu i naciśnij 'S'")
    keyboard.wait('s')
    x2, y2 = pyautogui.position()
    print(f"Zapisano punkt 2: {x2}, {y2}")
    return (int(x1), int(y1), int(x2), int(y2))

# --- START PROGRAMU ---
region = get_region()
print("\nBot AKTYWNY. Skanuję...")
print("Przytrzymaj 'Q', aby wyłączyć bota.")

try:
    while True:
        if keyboard.is_pressed('q'):
            print("Zamykanie bota...")
            break

        # Przechwycenie obrazu regionu
        img = ImageGrab.grab(bbox=region, all_screens=True).convert('RGB')
        width, height = img.size
        found = False
        
        for x in range(0, width, 5):
            for y in range(0, height, 5):
                r, g, b = img.getpixel((x, y))
                
                if all(abs(p - t) <= TOLERANCE for p, t in zip((r,g,b), TARGET_COLOR)):
                    
                    # Weryfikacja gęstości
                    check_count = 0
                    for dx in range(0, 10, 2):
                        for dy in range(0, 10, 2):
                            if x + dx < width and y + dy < height:
                                pr, pg, pb = img.getpixel((x + dx, y + dy))
                                if all(abs(p - t) <= TOLERANCE for p, t in zip((pr,pg,pb), TARGET_COLOR)):
                                    check_count += 1
                    
                    if check_count > MIN_PIXELS:
                        real_x, real_y = x + region[0], y + region[1]
                        
                        # 1. Kliknięcie w przycisk
                        pyautogui.click(real_x, real_y)
                        print(f"Kliknięto w: {real_x}, {real_y}")
                        
                        # 2. Odskok myszki (ważne, by nie blokować menu)
                        pyautogui.moveTo(max(real_x - OFFSET, region[0]), real_y)
                        
                        # 3. ODŚWIEŻENIE STRONY (F5)
                        time.sleep(0.5) # Krótka pauza przed odświeżeniem
                        pyautogui.press('f5')
                        print("Strona odświeżona (F5).")
                        
                        found = True
                        # Dłuższa przerwa po F5, żeby strona zdążyła się załadować
                        time.sleep(5) 
                        break
            if found: break
            
        time.sleep(0.1)

except Exception as e:
    print(f"Błąd: {e}")
    time.sleep(5)