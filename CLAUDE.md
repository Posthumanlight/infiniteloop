# Roguelike RPG — Telegram WebApp

Multiplayer turn-based RPG roguelike played in Telegram group chats. Players form a party, explore procedurally generated dungeons room-by-room, and fight enemies in menu-driven turn-based combat. All input happens via Telegram inline keyboards (bot) and a WebApp (combat skill picker, inventory, character sheet).

#Core Desing Principles
This project is evaluated on 2 main principles:
1. DRY
2. SOLID
Always evaluate your code against this principles.


## Tech Stack

- **Bot**: aiogram 3.x (Telegram bot + WebApp launcher)
- **API**: FastAPI (game server, WebApp backend, REST endpoints for combat actions)
- **Logic**: pure Python 3.12+
- **DB**: PostgreSQL via asyncpg
- **Cache**: Redis (combat state, session tokens, turn timers)
- **Migrations**: Alembic
- **WebApp frontend**: React + TypeScript + Vite (served as Telegram WebApp)
- **Testing**: pytest + pytest-asyncio, factory_boy for fixtures

## Project Structure

```
project_root/
├── CLAUDE.md
├── bot/                  # aiogram handlers, routers, middlewares
│   ├── handlers/         # command & callback handlers
│   ├── middlewares/       # auth, rate limiting, session injection
│   └── tools/        # inline keyboards, WebApp buttons
├── server/               # FastAPI app
│   ├── api/              # REST endpoints (combat actions, game state, WebApp)
│   ├── dependencies/     # DI: db sessions, redis, auth
│   └── schemas/          # Pydantic request/response schemas (API layer only)
├── game/                 # PURE game logic — NO I/O, NO db, NO network
│   ├── combat/           # combat engine, turn manager, targeting, effects, skill resolution
│   ├── character/        # base entity, player, enemy, stats, skill definitions
│   ├── items/            # item models, inventory, equipment slots, loot tables
│   ├── world/            # procedural generation, dungeon graph, room templates, encounters
│   ├── events/           # random events, voting logic, outcome resolution
│   └── core/             # base types, enums, dice/RNG, formulas, constants
├── db/              # DB models, repositories, Redis cache layer
│   ├── models/           # SQLAlchemy ORM models
│   ├── repos/            # repository pattern (async, one per aggregate)
│   └── cache/            # Redis helpers for combat state, sessions
├── frontend/               # React frontend (Telegram WebApp)
│   └── src/
│       ├── features/     # combat-ui/, inventory/, character-sheet/
│       └── shared/       # api client, types, telegram-sdk helpers
├── migrations/           # Alembic
├── tests/
│   ├── unit/             # game/ logic tests (no I/O mocking needed)
│   ├── integration/      # API + DB tests
│   └── factories/        # factory_boy model factories
└── docs/                 # specs, design docs, data tables
    ├── ARCHITECTURE.md
    ├── COMBAT.md
    ├── WORLD_GEN.md
    └── DATA_TABLES.md
```

## Critical Architecture Rules

1. **`game/` is pure logic.** No imports from `db/`, `server/`, `bot/`, or any async/IO library. All game functions take frozen dataclasses in and return frozen dataclasses out (via `dataclasses.replace()`). This is the most important rule in the project. If `game/` needs data, the caller passes it in.

2. **Dependency direction is one-way:** `bot/` → `server/` → `game/` ← `storage/`. The `server/` layer orchestrates: it loads state from `storage/`, calls `game/` functions, persists results back. `game/` never knows about persistence.

3. **Combat state lives in Redis** during active fights (fast reads for turn resolution). On combat end, final state flushes to PostgreSQL. Use `db/cache/combat.py` for this.

4. **Every module exposes a public API via `__init__.py`.** Internal helpers are prefixed with `_`. Don't reach into submodules from outside.

## Commands

```bash
# Dev
uvicorn server.main:app --reload          # FastAPI server
python -m bot.main                         # Telegram bot
cd webapp && npm run dev                   # WebApp dev server

# DB
alembic upgrade head                       # Apply migrations
alembic revision --autogenerate -m "msg"   # Create migration

# Test
pytest tests/unit -x                       # Game logic tests (run these first, fast)
pytest tests/integration -x                # API tests (needs DB)
pytest tests/ -x --tb=short                # Full suite

# Lint / Type
ruff check . --fix
mypy game/ server/ bot/ db/
```

## Code Conventions

- All models in `game/` use `@dataclass(frozen=True)` — game state is immutable; functions return new state via `dataclasses.replace()`.
- Use `Annotated` types for FastAPI dependencies, not bare `Depends()`.
- SQLAlchemy models use `Mapped[]` type annotations (2.0 style), not `Column()`.
- Repositories return domain dataclasses, not ORM objects — conversion happens at the repo boundary.
- Async everywhere in `bot/`, `server/`, `storage/`. Sync only in `game/`.
- Type hints on every function signature. `Any` requires a comment explaining why.
- Use `Enum` for all fixed sets (damage types, classes, item slots, room types, target types).

## Game Design Essentials

### Combat (Menu-Based)
- **No grid.** Combat is party vs. enemy group, JRPG-style.
- On a player's turn, they pick an action via WebApp or inline keyboard: **Action** (skill), or **Item**.
- Skills have target types: `single_enemy`, `all_enemies`, `single_ally`, `all_allies`, `self`.
- For `single_enemy` / `single_ally` targets, the player picks from a list (not a grid position).
- Enemies are an ordered list with visible HP bars. Players select target by index/name.
- Turn order, initiative, buffs/debuffs, and status effects are the tactical depth — not positioning.

### Turn System
- Initiative order based on speed stat + configurable dice roll (see `constants.toml: initiative_dice`).
- Each turn: one action (skill or item). No action points, no movement.
- Turn timer: 45 seconds. Auto-skip on timeout.
- All players and enemies act in initiative order (not simultaneous).

### Exploration (Room-Based)
- Dungeon is a **graph of rooms** (nodes + edges), not a spatial grid.
- Party moves room to room. Each room has a type: `combat`, `treasure`, `event`, `shop`, `rest`, `boss`.
- On entering a room, content resolves automatically or via player choices (voting for events).
- Fog of war: only adjacent rooms are visible. Revealed rooms stay on a simple map (WebApp shows a node graph).

### Character Classes
- Define classes in `game/core/data/classes.toml` as data, not class hierarchies. A class is a stat template + skill list + equipment restrictions.
- **Two-tier stat system:**
  - **MajorStats** (fixed fields): `attack`, `hp`, `speed`, `crit_chance`, `crit_dmg`, `resistance`, `energy`, `mastery`.
  - **MinorStats** (per-damage-type %): `{type}_dmg_pct`, `{type}_def_pct` — stored as a flat dict, accessed via `get_dmg_pct(DamageType)` / `get_def_pct(DamageType)`.
- All balance data (formulas, effects, skills, classes, enemies) lives in TOML files under `game/core/data/`.

### Procedural Generation
- Use seeded RNG (`random.Random(seed)`) — every generated dungeon must be reproducible from its seed.
- Generate a graph of rooms (branching paths, loops, dead ends), then populate each room from templates.
- Location templates in `game/world/templates/` as data files (TOML or JSON).
- Difficulty scales with depth (room distance from entrance).

### Multiplayer & Voting
- A "session" = one Telegram group playing together. Session ID derived from chat_id.
- **Event voting**: random events present 2-4 options. Each player votes. Majority wins; ties broken randomly.
- **Exploration voting**: when paths branch, party votes on which direction to take.
- Party size: 1-4 players (solo allowed).

## Data-Driven Design

Game balance data (class stats, item stats, enemy stats, loot tables, XP curves) lives in `docs/DATA_TABLES.md` and/or TOML files in `game/core/data/`. Logic reads from these; don't hardcode numbers in functions. When adding new content (enemies, items, skills), add data entries — don't write new code unless it's a new mechanic.

## When Compacting

Preserve: current task, list of modified files, test status, which module you're working in, any active design decisions.

## PR / Commit Conventions

- Conventional commits: `feat(combat):`, `fix(world):`, `refactor(storage):`, etc.
- One module per PR when possible. Never mix `game/` logic changes with `storage/` schema changes in the same commit.
