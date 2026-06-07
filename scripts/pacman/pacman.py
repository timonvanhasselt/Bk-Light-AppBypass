import sys
import asyncio
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

# --- CONFIGURATIE ---
EMPTY = 0
WALL = 1
DOT = 2
CHERRY = 3
TUNNEL_DOT = 4

COLOR_MAP = {
    EMPTY: (0, 0, 0),
    WALL: (33, 33, 255),       
    DOT: (150, 150, 150),      
    CHERRY: (255, 0, 0),
    TUNNEL_DOT: (255, 255, 255),
    'PLAYER': (255, 255, 0),   
    'GHOST_RED': (255, 0, 0),
    'GHOST_PINK': (255, 182, 193),
    'GHOST_SCARED_GREEN': (0, 255, 100), 
    'GHOST_SCARED_WHITE': (200, 255, 200) 
}

class Ghost:
    def __init__(self, x, y, color_key, speed, game):
        # speed: lager is sneller (aantal frames per stap)
        self.x, self.y = x, y
        self.spawn_x, self.spawn_y = x, y # Vaste spawn plek
        self.color_key = color_key
        self.speed = speed
        self.game = game
        self.move_counter = 0
        self.last_dir = (0, 0)
        self.new_random_target()

    def reset(self):
        # Keer terug naar de vaste spawn plek
        self.x, self.y = self.spawn_x, self.spawn_y
        self.last_dir = (0, 0)
        self.new_random_target()

    def new_random_target(self):
        self.target_x, self.target_y = random.randint(2, 29), random.randint(2, 29)

    def update(self):
        self.move_counter += 1
        if self.move_counter % self.speed != 0:
            return

        # Bepaal doel
        if self.game.power_timer > 0:
            tx, ty = self.game.player_x, self.game.player_y
            mode_flee = True
        else:
            mode_flee = False
            if random.random() < 0.8:
                tx, ty = self.game.player_x, self.game.player_y
            else:
                tx, ty = self.target_x, self.target_y
                if abs(self.x - self.target_x) < 2 and abs(self.y - self.target_y) < 2:
                    self.new_random_target()

        moves = []
        for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
            # Voorkom direct omkeren om lussen te breken
            if dx == -self.last_dir[0] and dy == -self.last_dir[1] and self.last_dir != (0,0):
                continue
                
            nx, ny = (self.x + dx) % 32, (self.y + dy) % 32
            if self.game.can_move_to(nx, ny):
                dist = abs(nx - tx) + abs(ny - ty)
                moves.append((dx, dy, dist))

        if not moves: # Als ingesloten, sta omkeren toe
            moves.append((-self.last_dir[0], -self.last_dir[1], 0))

        if moves:
            moves.sort(key=lambda m: m[2], reverse=mode_flee)
            # Voeg kleine variatie toe om lussen te voorkomen
            chosen = moves[1] if (len(moves) > 1 and random.random() < 0.15) else moves[0]
            self.x = (self.x + chosen[0]) % 32
            self.y = (self.y + chosen[1]) % 32
            self.last_dir = (chosen[0], chosen[1])

class PacMatrixGame:
    def __init__(self):
        self.width, self.height = 32, 32
        self.player_x, self.player_y = 15, 23
        self.running = True
        self.won = False
        self.power_timer = 0
        self.cherry_spawn_timer = 0
        self.grid = [[EMPTY for _ in range(32)] for _ in range(32)]
        self.create_complex_maze()
        
        # Spookjes sneller gemaakt (speed verlaagd van 4/5 naar 2/3)
        # Ze spawnen nu beide in het midden van het doolhof (GHOST HOUSE)
        self.ghosts = [
            Ghost(15, 14, 'GHOST_RED', 2, self),
            Ghost(16, 14, 'GHOST_PINK', 3, self)
        ]

    def add_wall(self, x, y, w, h):
        for i in range(y, y + h):
            for j in range(x, x + w):
                if 0 <= i < 32 and 0 <= j < 32:
                    self.grid[i][j] = WALL

    def create_complex_maze(self):
        self.grid = [[EMPTY for _ in range(32)] for _ in range(32)]
        self.add_wall(0, 0, 32, 1)
        self.add_wall(0, 31, 32, 1)
        self.add_wall(0, 0, 1, 32)
        self.add_wall(31, 0, 1, 32)
        
        # Tunnel gaten
        for y in [14, 15, 16, 17]:
            self.grid[y][0] = EMPTY
            self.grid[y][31] = EMPTY
            
        # Witte stipjes
        for y in [13, 18]:
            for x in [0, 1, 30, 31]:
                self.grid[y][x] = TUNNEL_DOT

        self.add_wall(3, 3, 5, 2)
        self.add_wall(24, 3, 5, 2)
        self.add_wall(10, 3, 12, 2)
        self.add_wall(3, 8, 2, 5) 
        self.add_wall(27, 8, 2, 5)
        self.add_wall(8, 8, 4, 4)
        self.add_wall(20, 8, 4, 4)
        
        self.add_wall(10, 14, 12, 2) 
        
        self.add_wall(3, 19, 2, 9)
        self.add_wall(27, 19, 2, 9)
        self.add_wall(8, 20, 4, 4)
        self.add_wall(20, 20, 4, 4)
        self.add_wall(10, 27, 12, 2)

        for y in range(2, 30, 3):
            for x in range(2, 30, 3):
                if self.grid[y][x] == EMPTY:
                    self.grid[y][x] = DOT
        self.spawn_cherry()

    def spawn_cherry(self):
        empty_spots = []
        for y in range(2, 30):
            for x in range(2, 30):
                if self.grid[y][x] == EMPTY:
                    empty_spots.append((x, y))
        if empty_spots:
            rx, ry = random.choice(empty_spots)
            self.grid[ry][rx] = CHERRY

    def can_move_to(self, x, y):
        if 14 <= y <= 16: return True
        for dx in range(2):
            for dy in range(2):
                if self.grid[(y + dy) % 32][(x + dx) % 32] == WALL: return False
        return True

    def move(self, dx, dy):
        if self.won: return
        new_x = (self.player_x + dx) % 32
        new_y = (self.player_y + dy) % 32
        if self.can_move_to(new_x, new_y):
            self.player_x, self.player_y = new_x, new_y
            for ex in range(2):
                for ey in range(2):
                    tx, ty = (self.player_x + ex)%32, (self.player_y + ey)%32
                    if self.grid[ty][tx] == DOT: 
                        self.grid[ty][tx] = EMPTY
                    elif self.grid[ty][tx] == CHERRY:
                        self.grid[ty][tx] = EMPTY
                        self.power_timer = 200 
                        self.cherry_spawn_timer = 500 
            if not any(DOT in row for row in self.grid):
                self.won = True

    def check_collision(self):
        if self.won: return
        for g in self.ghosts:
            if abs(self.player_x - g.x) < 2 and abs(self.player_y - g.y) < 2:
                if self.power_timer > 0:
                    g.reset()
                else:
                    self.player_x, self.player_y = 15, 23

    def on_press(self, key):
        try:
            if key == keyboard.Key.up: self.move(0, -1)
            elif key == keyboard.Key.down: self.move(0, 1)
            elif key == keyboard.Key.left: self.move(-1, 0)
            elif key == keyboard.Key.right: self.move(1, 0)
            elif key == keyboard.Key.esc: self.running = False
        except: pass

    def render(self):
        img = Image.new("RGB", (32, 32), (0, 0, 0))
        pixels = img.load()
        for y in range(32):
            for x in range(32):
                cell = self.grid[y][x]
                if cell != EMPTY: pixels[x, y] = COLOR_MAP[cell]
        
        for g in self.ghosts:
            if self.power_timer > 0:
                if self.power_timer < 80 and (self.power_timer // 6) % 2 == 0:
                    c = COLOR_MAP['GHOST_SCARED_WHITE']
                else:
                    c = COLOR_MAP['GHOST_SCARED_GREEN']
            else:
                c = COLOR_MAP[g.color_key]
            for dx in range(2):
                for dy in range(2): pixels[(g.x+dx)%32, (g.y+dy)%32] = c
                
        for dx in range(2):
            for dy in range(2): pixels[(self.player_x+dx)%32, (self.player_y+dy)%32] = COLOR_MAP['PLAYER']
        return img

async def win_animation(manager):
    for _ in range(4):
        color = (random.randint(50,255), random.randint(50,255), random.randint(50,255))
        for step in range(0, 33, 8):
            img = Image.new("RGB", (32, 32), (0, 0, 0))
            pixels = img.load()
            for y in range(step):
                for x in range(32): pixels[x, y] = color
            await manager.send_image(img, delay=0)
            await asyncio.sleep(0.1)

async def main():
    config = load_config()
    game = PacMatrixGame()
    listener = keyboard.Listener(on_press=game.on_press)
    listener.start()

    async with PanelManager(config) as manager:
        while game.running:
            try:
                if game.won:
                    await win_animation(manager)
                    game.won = False
                    game.create_complex_maze()
                    continue

                if game.power_timer > 0: game.power_timer -= 1
                if game.cherry_spawn_timer > 0:
                    game.cherry_spawn_timer -= 1
                    if game.cherry_spawn_timer == 0: game.spawn_cherry()

                for g in game.ghosts: g.update()
                game.check_collision()
                
                await manager.send_image(game.render(), delay=0)
                await asyncio.sleep(0.06) 
            except Exception as e:
                print(f"Panel Error: {e}")
                await asyncio.sleep(0.2)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass