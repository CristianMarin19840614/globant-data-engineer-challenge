# Demo payloads

Paste these into the request body in Swagger (`/docs` → the endpoint →
**Try it out** → **Execute**), so nothing has to be typed live.

| File | Endpoint | Expected |
|---|---|---|
| `partial_batch.json` | `POST /hired-employees` | `200` · received 5, inserted 1, rejected 4 — one per rule of the brief |
| `empty_batch.json` | `POST /departments` | `422` · *List should have at least 1 item* |
| `too_many_rows.json` | `POST /departments` | `422` · *List should have at most 1000 items* |

`partial_batch.json` carries a `_comment` key that the endpoint ignores;
remove it if you prefer a payload with nothing extra in it.

**Order matters.** Run the two analytical queries *before* this batch: the
valid row it inserts is a 2021 hire, so afterwards the first query returns 934
rows instead of 933. Re-running `python load_csv.py --reset` puts everything
back.
