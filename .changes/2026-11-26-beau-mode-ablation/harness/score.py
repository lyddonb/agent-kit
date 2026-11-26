import json
from pathlib import Path

META = Path(__file__).resolve().parent
ITEMS = ["cause", "fix", "proof", "scope", "reply"]


def share(rows, x, y, item):
    wins = ties = n = 0
    for s in rows:
        a, b = s[x][item], s[y][item]
        n += 1
        wins += a > b
        ties += a == b
    return ((wins + 0.5 * ties) / n if n else None), n


def main():
    rows, missing = [], []
    for f in sorted((META / "judged").glob("t*.json")):
        j = json.loads(f.read_text())
        (rows.append(j["scores"]) if j["scores"] else missing.append((j["task"], j["status"])))
    out = {"tasks_scored": len(rows), "missing": missing, "items": {}}
    for i in ITEMS:
        nn, _ = share(rows, "full1", "full2", i)
        s1, _ = share(rows, "slim", "full1", i)
        s2, _ = share(rows, "slim", "full2", i)
        band = abs(nn - 0.5)
        pooled = (s1 + s2) / 2
        means = {a: sum(r[a][i] for r in rows) / len(rows) for a in ("full1", "full2", "slim")}
        out["items"][i] = {"full1_over_full2": nn, "band": band, "slim_over_full1": s1, "slim_over_full2": s2,
                           "slim_over_full": pooled, "holds": pooled >= 0.5 - band, "mean_score": means}
    out["recommendation"] = "slim" if all(v["holds"] for v in out["items"].values()) else "keep"
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
