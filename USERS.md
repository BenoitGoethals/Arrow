# Seeded Users

All accounts share password **`ranger14`**. Created automatically on first boot by `backend/storage/seed.py` (deterministic — RNG seeded with `0xA77017`).

## Admin

| Callsign | Rank | Role |
| --- | --- | --- |
| `benoit` | OF-3 | ADMIN |

## Battle Captain

| Callsign | Rank | Role |
| --- | --- | --- |
| `capt` | OF-2 | BATTLE_CAPTAIN |

## Operators

| Callsign | Rank | Role |
| --- | --- | --- |
| `ECHO-5` | OR-5 | OPERATOR |
| `TANGO-8` | OR-3 | OPERATOR |
| `PAPA-2` | OR-6 | OPERATOR |
| `ALPHA-4` | OR-6 | OPERATOR |
| `CHARLIE-2` | OR-1 | OPERATOR |
| `XRAY-3` | OR-3 | OPERATOR |
| `WHISKEY-1` | OR-5 | OPERATOR |
| `PAPA-1` | OR-3 | OPERATOR |
| `MIKE-9` | OR-6 | OPERATOR |
| `ZULU-7` | OR-4 | OPERATOR |

## Re-seed

```bash
rm arrow.db && uv run python run.py    # auto-seeds on empty DB
# or
uv run arrow-seed --force              # add missing entries to existing DB
```
