import sys
import asyncio
import os
import gc
import random
from pathlib import Path
from pynput import keyboard
from PIL import Image

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
        
        # Paddle
        self.paddle_x = 11.0
        self.paddle_w = 10
        self.paddle_h = 2
        self.paddle_y = 28
        self.paddle_speed = 2.0
        
        # Bal
        self.ball_x = 16.0
        self.ball_y = 15.0
        self.ball_dx = 0.8 # Iets minder agressieve hoek
        self.ball_dy = 1.0
        self.ball_speed = 0.8

        self.colors = [(255, 0, 0), (255, 165, 0), (255, 255, 0), (0, 255, 0)]
        self.bricks = []
        self.generate_bricks()
        self.pressed_keys = set()

    def generate_bricks(self):
        self.bricks = []
        for row in range(4):
            color = self.colors[row]
            for col in range(0, 32, 4):
                self.bricks.append([col, 2 + (row * 3), 4, 2, color, True])

    def reset_ball(self):
        self.ball_x, self.ball_y = 16.0, 15.0
        self.ball_dy = 1.0
        self.ball_dx = random.choice([-0.8, 0.8])

    def update(self):
        if self.in_animation: return False
        
        # Paddle movement
        if keyboard.Key.left in self.pressed_keys:
            self.paddle_x = max(0, self.paddle_x - self.paddle_speed)
        if keyboard.Key.right in self.pressed_keys:
            self.paddle_x = min(32 - self.paddle_w, self.paddle_x + self.paddle_speed)

        # Bal movement
        self.ball_x += self.ball_dx * self.ball_speed
        self.ball_y += self.ball_dy * self.ball_speed

        # Wand botsingen (Strikte grenzen)
        if self.ball_x <= 0:
            self.ball_dx = abs(self.ball_dx)
        elif self.ball_x >= 31:
            self.ball_dx = -abs(self.ball_dx)
        
        if self.ball_y <= 0:
            self.ball_dy = abs(self.ball_dy)

        # Paddle botsing
        if self.paddle_y <= self.ball_y <= self.paddle_y + self.paddle_h:
            if self.paddle_x <= self.ball_x <= self.paddle_x + self.paddle_w:
                self.ball_dy = -abs(self.ball_dy)
                # Richting bepalen op basis van waar de paddle geraakt wordt
                offset = (self.ball_x - self.paddle_x) / self.paddle_w
                self.ball_dx = (offset - 0.5) * 3.0
                self.ball_y = self.paddle_y - 1.1

        # Bricks
        active_found = False
        for b in self.bricks:
            if b[5]:
                active_found = True
                if b[0] <= self.ball_x < b[0] + b[2] and b[1] <= self.ball_y < b[1] + b[3]:
                    b[5] = False
                    self.ball_dy *= -1
                    return False # Stop update direct na hit voor stabiliteit

        if not active_found:
            return True # Start animatie

        if self.ball_y > 33:
            self.reset_ball()
        
        return False

    def render(self):
        img = Image.new("RGB", (32, 32), (0, 0, 0))
        if self.in_animation: return img
        
        pixels = img.load()
        for b in self.bricks:
            if b[5]:
                for ix in range(b[2]):
                    for iy in range(b[3]):
                        pixels[b[0]+ix, b[1]+iy] = b[4]
        
        for ix in range(self.paddle_w):
            for iy in range(self.paddle_h):
                pixels[int(self.paddle_x) + ix, self.paddle_y + iy] = (255, 255, 255)
        
        bx, by = int(self.ball_x), int(self.ball_y)
        if 0 <= bx < 32 and 0 <= by < 32:
            pixels[bx, by] = (0, 255, 255)
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
        while game.running:
            try:
                complete = game.update()
                
                if complete:
                    game.in_animation = True
                    # Hele simpele animatie: 3x flitsen
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
                
                # Belangrijk: iets trager (25 FPS) om vastlopen te voorkomen
                await asyncio.sleep(0.04)
                
                # Regelmatig geheugen legen
                gc.collect()

            except Exception:
                await asyncio.sleep(0.5) # Bij fout, geef paneel rust

if __name__ == "__main__":
    asyncio.run(main())
    
    