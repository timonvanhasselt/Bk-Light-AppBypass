import sys
import asyncio
import os
import gc
import random
from io import BytesIO
from pathlib import Path
from pynput import keyboard
from PIL import Image, ImageOps

# Zorg dat de bk_light module gevonden kan worden
project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

from bk_light.config import load_config
from bk_light.panel_manager import PanelManager

class BrickItGame:
    def __init__(self):
        self.running = True
        self.in_animation = False
        
        # Paddle instellingen[cite: 2]
        self.paddle_x = 11.0
        self.paddle_w = 10
        self.paddle_h = 2
        self.paddle_y = 28
        self.paddle_speed = 2.0
        
        # Bal instellingen (2x2 blokje conform jouw verzoek)[cite: 2]
        self.ball_x = 16.0
        self.ball_y = 15.0
        self.ball_dx = 0.8 
        self.ball_dy = 1.0
        self.ball_speed = 0.8
        self.ball_size = 2 

        # Fellere kleuren gebaseerd op breakout_2.jpg[cite: 2]
        self.colors = [
            (255, 20, 147),  # Deep Pink
            (255, 69, 0),    # Red-Orange
            (255, 215, 0),   # Gold
            (50, 205, 50),   # Lime Green
            (30, 144, 255),  # Dodger Blue
            (148, 0, 211)    # Dark Violet
        ]
        self.bricks = []
        self.generate_bricks()
        self.pressed_keys = set()

    def generate_bricks(self):
        """Genereert banen van 2 pixels hoog die strak tegen elkaar liggen[cite: 2]."""
        self.bricks = []
        for row in range(6):
            color = self.colors[row % len(self.colors)]
            for col in range(0, 32, 4):
                # Breedte 4, Hoogte 2[cite: 2]
                self.bricks.append([col, 1 + (row * 2), 4, 2, color, True])

    async def show_logo_splash(self, manager):
        """
        Toont het logo met de exacte hoogwaardige schaling uit bootstrap_demo.py[cite: 3].
        Dit zorgt voor de scherpste en felste weergave op het paneel.
        """
        try:
            # Pad naar de asset (breakout.jpg)[cite: 3]
            asset_path = project_root / "assets" / "breakout.jpg"
            if asset_path.exists():
                # Openen en converteren naar RGB[cite: 3]
                image = Image.open(asset_path).convert("RGB")
                
                # De cruciale stap: ImageOps.fit met LANCZOS resampling[cite: 3]
                # Dit voorkomt dat het plaatje 'modderig' wordt op 32x32.
                fitted = ImageOps.fit(image, (32, 32), method=Image.Resampling.LANCZOS)
                
                # Stuur de geoptimaliseerde afbeelding naar het paneel
                await manager.send_image(fitted, delay=0)
                
                # Toon het logo gedurende 4 seconden voor maximale impact
                await asyncio.sleep(4.0) 
                
                # Kort zwart scherm voor een vloeiende overgang naar het spel
                await manager.send_image(Image.new("RGB", (32, 32), (0, 0, 0)), delay=0)
                await asyncio.sleep(0.5)
        except Exception as e:
            print(f"Splash error: {e}")

    def reset_ball(self):
        self.ball_x, self.ball_y = 16.0, 15.0
        self.ball_dy = 1.0
        self.ball_dx = random.choice([-0.8, 0.8])

    def update(self):
        if self.in_animation: return False
        
        # Besturing
        if keyboard.Key.left in self.pressed_keys:
            self.paddle_x = max(0, self.paddle_x - self.paddle_speed)
        if keyboard.Key.right in self.pressed_keys:
            self.paddle_x = min(32 - self.paddle_w, self.paddle_x + self.paddle_speed)

        # Bal beweging
        self.ball_x += self.ball_dx * self.ball_speed
        self.ball_y += self.ball_dy * self.ball_speed

        # Randen
        if self.ball_x <= 0:
            self.ball_dx = abs(self.ball_dx)
        elif self.ball_x >= 32 - self.ball_size:
            self.ball_dx = -abs(self.ball_dx)
        
        if self.ball_y <= 0:
            self.ball_dy = abs(self.ball_dy)

        # Paddle botsing (rekening houdend met bal-grootte)
        if self.paddle_y <= self.ball_y + self.ball_size - 1 <= self.paddle_y + self.paddle_h:
            if self.paddle_x <= self.ball_x <= self.paddle_x + self.paddle_w:
                self.ball_dy = -abs(self.ball_dy)
                offset = (self.ball_x - self.paddle_x) / self.paddle_w
                self.ball_dx = (offset - 0.5) * 3.0
                self.ball_y = self.paddle_y - self.ball_size - 0.1

        # Bricks botsing
        active_found = False
        for b in self.bricks:
            if b[5]:
                active_found = True
                if (b[0] < self.ball_x + self.ball_size and 
                    b[0] + b[2] > self.ball_x and 
                    b[1] < self.ball_y + self.ball_size and 
                    b[1] + b[3] > self.ball_y):
                    b[5] = False
                    self.ball_dy *= -1
                    return False 

        if not active_found:
            return True 

        if self.ball_y > 33:
            self.reset_ball()
        
        return False

    def render(self):
        img = Image.new("RGB", (32, 32), (0, 0, 0))
        if self.in_animation: return img
        
        pixels = img.load()
        # Teken Bricks
        for b in self.bricks:
            if b[5]:
                for ix in range(b[2]):
                    for iy in range(b[3]):
                        px, py = b[0]+ix, b[1]+iy
                        if 0 <= px < 32 and 0 <= py < 32:
                            pixels[px, py] = b[4]
        
        # Teken Paddle
        for ix in range(self.paddle_w):
            for iy in range(self.paddle_h):
                px, py = int(self.paddle_x) + ix, self.paddle_y + iy
                if 0 <= px < 32 and 0 <= py < 32:
                    pixels[px, py] = (255, 255, 255)
        
        # Teken Bal (4 pixels groot)
        bx, by = int(self.ball_x), int(self.ball_y)
        for ix in range(self.ball_size):
            for iy in range(self.ball_size):
                px, py = bx + ix, by + iy
                if 0 <= px < 32 and 0 <= py < 32:
                    pixels[px, py] = (255, 255, 255)
        return img

async def main():
    config = load_config()
    game = BrickItGame()

    def on_press(key): game.pressed_keys.add(key)
    def on_release(key):
        if key in game.pressed_keys: game.pressed_keys.remove(key)
        if key == keyboard.Key.esc: game.running = False

    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()

    async with PanelManager(config) as manager:
        # Stap 1: Toon het logo in hoge kwaliteit zoals de bootstrap demo[cite: 3]
        await game.show_logo_splash(manager)
        
        # Stap 2: Start het spel
        while game.running:
            try:
                complete = game.update()
                
                if complete:
                    game.in_animation = True
                    for _ in range(3):
                        await manager.send_image(Image.new("RGB", (32, 32), (0, 255, 0)), delay=0)
                        await asyncio.sleep(0.2)
                        await manager.send_image(Image.new("RGB", (32, 32), (0, 0, 0)), delay=0)
                        await asyncio.sleep(0.1)
                    
                    game.generate_bricks()
                    game.reset_ball()
                    game.in_animation = False
                
                frame = game.render()
                await manager.send_image(frame, delay=0)
                del frame
                
                # Stabiele FPS om de Bluetooth-verbinding niet te overbelasten[cite: 1]
                await asyncio.sleep(0.04)
                gc.collect()

            except Exception:
                await asyncio.sleep(0.5) 

if __name__ == "__main__":
    asyncio.run(main())