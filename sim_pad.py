"""How many steps does a competent player actually spend on the pad?

Models coordinate descent — the thing a human naturally does with two axes:
push one axis until the block stops improving, switch axis, repeat. Plateaus
(adjacent errors that resolve the same share of cells) are the interesting
case, so the model tolerates a couple of flat steps before giving up on an
axis, exactly as a player squinting at the block would.
"""
import statistics
from gameengine import config
from gameengine.core import tools_bridge as tb
from gameengine.core.content_loader import load_day
from gameengine.core import candidate_gen

def frac(b, x, y):
    return tb.resolved_fraction(b, x, y)

def play(b, patience=2):
    x, y = b.start_cursor
    steps = 0
    axis = 0
    stuck_axes = 0
    while (x, y) != b.align_true and steps < 400:
        moved_any = False
        for direction in (1, -1):
            flat = 0
            while steps < 400:
                nx = x + (direction if axis == 0 else 0)
                ny = y + (direction if axis == 1 else 0)
                if not (0 <= nx <= b.align_span_x and 0 <= ny <= b.align_span_y):
                    break
                before, after = frac(b, x, y), frac(b, nx, ny)
                if after > before:
                    x, y, steps, flat, moved_any = nx, ny, steps + 1, 0, True
                elif after == before and flat < patience:
                    x, y, steps, flat = nx, ny, steps + 1, flat + 1
                else:
                    break
            if moved_any:
                break
            # that direction was wrong; the probe steps still cost
        if not moved_any:
            stuck_axes += 1
            if stuck_axes >= 4:
                break
        else:
            stuck_axes = 0
        axis ^= 1
    return steps, (x, y) == b.align_true

day = load_day(3)
blocks = []
for seed in range(300):
    for slot in range(day.candidate_count):
        c = candidate_gen.generate(seed, day, slot)
        b = tb.build_cipher_block(c, 3)
        if b.crackable and not b.pre_revealed:
            blocks.append(b)
    if len(blocks) > 220: break

for tier in ("weak", "medium"):
    bs = [b for b in blocks if b.tier == tier]
    res = [play(b) for b in bs]
    solved = [s for s, ok in res if ok]
    fails  = sum(1 for _s, ok in res if not ok)
    if not solved: continue
    fees = [sum(tb.step_overage_charge(i, i + 1) for i in range(s)) for s in solved]
    print(f"{tier:7s} n={len(bs)} unsolved={fails}")
    print(f"   steps  median={statistics.median(solved):.0f} "
          f"mean={statistics.mean(solved):.0f} "
          f"p90={sorted(solved)[int(len(solved)*0.9)]} max={max(solved)}")
    print(f"   fee ⏱  median={statistics.median(fees):.0f} "
          f"mean={statistics.mean(fees):.1f} max={max(fees)}  "
          f"paid-nothing={sum(1 for f in fees if f == 0)*100//len(fees)}%")

print()
print("=== careless players ===")
import random
def random_walk(b, rng, bias=0.55):
    """Wanders: mostly moves toward whichever direction just helped, but
    re-rolls often — the player who is pressing keys and hoping."""
    x = y = 0; steps = 0
    while (x, y) != b.align_true and steps < 500:
        if rng.random() < bias:
            best, bx, by = -1.0, x, y
            for dx, dy in ((1,0),(-1,0),(0,1),(0,-1)):
                nx, ny = x+dx, y+dy
                if 0 <= nx <= b.align_span_x and 0 <= ny <= b.align_span_y:
                    f = frac(b, nx, ny)
                    if f > best: best, bx, by = f, nx, ny
            x, y = bx, by
        else:
            dx, dy = rng.choice([(1,0),(-1,0),(0,1),(0,-1)])
            nx, ny = max(0, min(b.align_span_x, x+dx)), max(0, min(b.align_span_y, y+dy))
            if (nx, ny) == (x, y): continue
            x, y = nx, ny
        steps += 1
    return steps, (x, y) == b.align_true

rng = random.Random(7)
for tier in ("weak", "medium"):
    bs = [b for b in blocks if b.tier == tier]
    res = [random_walk(b, rng) for b in bs]
    solved = [s for s, ok in res if ok]
    if not solved: continue
    fees = [sum(tb.step_overage_charge(i, i+1) for i in range(s)) for s in solved]
    print(f"{tier:7s} unsolved={sum(1 for _s,ok in res if not ok)} "
          f"steps median={statistics.median(solved):.0f} p90={sorted(solved)[int(len(solved)*0.9)]}")
    print(f"        fee ⏱ median={statistics.median(fees):.0f} "
          f"mean={statistics.mean(fees):.1f} max={max(fees)} "
          f"paid-nothing={sum(1 for f in fees if f==0)*100//len(fees)}%")
