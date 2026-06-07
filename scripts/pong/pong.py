import sys
import asyncio
import os
import gc
from io import BytesIO
from pathlib import Path
from pynput import keyboard
from PIL import Image, ImageOps

# Project paden instellen
project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.append(str(project_root))

from bk_light.config import load_config
from bk_light.panel_manager import PanelManager

class PongGame:
    def __init__(self):
        self.running = True
        
        # Font definitie: 3x5 pixels per cijfer
        self.font = {
            '0': [(0,0), (1,0), (2,0), (0,1), (2,1), (0,2), (2,2), (0,3), (2,3), (0,4), (1,4), (2,4)],
            '1': [(1,0), (1,1), (1,2), (1,3), (1,4)],
            '2': [(0,0), (1,0), (2,0), (2,1), (0,2), (1,2), (2,2), (0,3), (0,4), (1,4), (2,4)],
            '3': [(0,0), (1,0), (2,0), (2,1), (0,2), (1,2), (2,2), (2,3), (0,4), (1,4), (2,4)],
            '4': [(0,0), (2,0), (0,1), (2,1), (0,2), (1,2), (2,2), (2,3), (2,4)],
            '5': [(0,0), (1,0), (2,0), (0,1), (0,2), (1,2), (2,2), (2,3), (0,4), (1,4), (2,4)],
            '6': [(0,0), (1,0), (2,0), (0,1), (0,2), (1,2), (2,2), (0,3), (2,3), (0,4), (1,4), (2,4)],
            '7': [(0,0), (1,0), (2,0), (2,1), (2,2), (2,3), (2,4)],
            '8': [(0,0), (1,0), (2,0), (0,1), (2,1), (0,2), (1,2), (2,2), (0,3), (2,3), (0,4), (1,4), (2,4)],
            '9': [(0,0), (1,0), (2,0), (0,1), (2,1), (0,2), (1,2), (2,2), (2,3), (0,4), (1,4), (2,4)]
        }

        # Paddle instellingen
        self.p1_y, self.p2_y = 12.0, 12.0
        self.paddle_w, self.paddle_h = 2, 8
        self.paddle_speed = 1.8
        
        # Bal instellingen
        self.ball_x, self.ball_y = 16.0, 16.0
        self.ball_dx, self.ball_dy = 0.9, 0.7
        self.ball_speed = 1.0
        self.ball_size = 2 

        self.pressed_keys = set()
        self.score = [0, 0]

    async def force_bootstrap_splash(self, manager):
        """Toont logo met de felle bootstrap methode."""
        try:
            asset_path = project_root / "assets" / "breakout.jpg"
            if asset_path.exists():
                image = Image.open(asset_path).convert("RGB")
                fitted = ImageOps.fit(image, (32, 32), method=Image.Resampling.LANCZOS)
                buffer = BytesIO()
                fitted.save(buffer, format="PNG", optimize=False)
                session = getattr(manager, 'display_session', getattr(manager, 'session', None))
                if session:
                    await session.send_png(buffer.getvalue())
                await asyncio.sleep(4.0)
                await manager.send_image(Image.new("RGB", (32, 32), (0, 0, 0)), delay=0)
        except Exception as e:
            print(f"Splash error: {e}")

    def draw_digit(self, pixels, digit, x_off, y_off, color):
        """Tekent een cijfer op het scherm."""
        pattern = self.font.get(str(digit), [])
        for px, py in pattern:
            if 0 <= x_off + px < 32 and 0 <= y_off + py < 32:
                pixels[x_off + px, y_off + py] = color

    def update(self):
        # Speler 1 (W/S)
        if any(k in self.pressed_keys for k in [keyboard.KeyCode.from_char('w'), keyboard.KeyCode.from_char('W')]):
            self.p1_y = max(0, self.p1_y - self.paddle_speed)
        if any(k in self.pressed_keys for k in [keyboard.KeyCode.from_char('s'), keyboard.KeyCode.from_char('S')]):
            self.p1_y = min(32 - self.paddle_h, self.p1_y + self.paddle_speed)

        # Speler 2 (Up/Down)
        if keyboard.Key.up in self.pressed_keys:
            self.p2_y = max(0, self.p2_y - self.paddle_speed)
        if keyboard.Key.down in self.pressed_keys:
            self.p2_y = min(32 - self.paddle_h, self.p2_y + self.paddle_speed)

        self.ball_x += self.ball_dx * self.ball_speed
        self.ball_y += self.ball_dy * self.ball_speed

        if self.ball_y <= 0 or self.ball_y >= 32 - self.ball_size:
            self.ball_dy *= -1

        # Paddle hits
        if self.ball_x <= self.paddle_w:
            if self.p1_y <= self.ball_y + self.ball_size and self.p1_y + self.paddle_h >= self.ball_y:
                self.ball_dx = abs(self.ball_dx)
                self.ball_speed = min(2.2, self.ball_speed + 0.05)
        
        if self.ball_x >= 32 - self.paddle_w - self.ball_size:
            if self.p2_y <= self.ball_y + self.ball_size and self.p2_y + self.paddle_h >= self.ball_y:
                self.ball_dx = -abs(self.ball_dx)
                self.ball_speed = min(2.2, self.ball_speed + 0.05)

        # Score bijhouden (reset bij 10)
        if self.ball_x < -2:
            self.score[1] = (self.score[1] + 1) % 10
            self.reset_ball()
        elif self.ball_x > 34:
            self.score[0] = (self.score[0] + 1) % 10
            self.reset_ball()

    def reset_ball(self):
        self.ball_x, self.ball_y = 16.0, 16.0
        self.ball_speed = 1.0
        self.ball_dx *= -1

    def render(self):
        img = Image.new("RGB", (32, 32), (0, 0, 0))
        pixels = img.load()
        
        # 1. Teken Cijfers
        self.draw_digit(pixels, self.score[1], 15, 2, (255, 0, 0))    # Rood boven
        self.draw_digit(pixels, self.score[0], 15, 25, (0, 100, 255)) # Blauw onder

        # 2. Teken Paddles
        for ix in range(self.paddle_w):
            for iy in range(self.paddle_h):
                p1y, p2y = int(self.p1_y) + iy, int(self.p2_y) + iy
                if 0 <= p1y < 32: pixels[ix, p1y] = (0, 150, 255)
                if 0 <= p2y < 32: pixels[31-ix, p2y] = (255, 50, 0)
        
        # 3. Teken Bal
        bx, by = int(self.ball_x), int(self.ball_y)
        for ix in range(self.ball_size):
            for iy in range(self.ball_size):
                if 0 <= bx+ix < 32 and 0 <= by+iy < 32:
                    pixels[bx+ix, by+iy] = (255, 255, 255)
        
        return img

async def main():
    config = load_config()
    game = PongGame()

    def on_press(key): game.pressed_keys.add(key)
    def on_release(key):
        if key in game.pressed_keys: game.pressed_keys.remove(key)
        if key == keyboard.Key.esc: game.running = False

    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()

    async with PanelManager(config) as manager:
        await game.force_bootstrap_splash(manager)
        
        while game.running:
            try:
                game.update()
                frame = game.render()
                await manager.send_image(frame, delay=0)
                await asyncio.sleep(0.03)
                gc.collect()
            except Exception as e:
                print(f"Error: {e}")
                await asyncio.sleep(0.5)

if __name__ == "__main__":
    asyncio.run(main())