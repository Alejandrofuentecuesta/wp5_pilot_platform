"""Derive the frontend name→gender map from Spain's INE name register.

Source: Estadística del Padrón Continuo, "nombres_por_edad_media.xls" —
every first name with 20 or more bearers nationally, by sex.
    https://www.ine.es/daco/daco42/nombyapel/nombres_por_edad_media.xls

The output maps every register entry (simple and compound names alike,
accent-folded) to "m" or "f" by majority sex, so gender can be inferred
from the full string a participant typed. Reuse of INE data is permitted
with attribution.

Usage (requires pandas + xlrd):
    python scripts/derive_name_genders.py <path-to-xls> \
        frontend/lib/name-genders.json
"""
import json
import sys
import unicodedata

import pandas as pd


def fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def load(path: str, sheet: str) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name=sheet, header=6)
    df = df.rename(columns={"Nombre": "name", "Frecuencia": "freq"})
    df = df.dropna(subset=["name", "freq"])
    df["name"] = df["name"].astype(str).str.strip()
    df["freq"] = df["freq"].astype(int)
    return df[["name", "freq"]]


def main() -> None:
    xls_path, out_path = sys.argv[1], sys.argv[2]
    weights: dict[str, dict[str, int]] = {}
    for sheet, sex in (("Hombres", "m"), ("Mujeres", "f")):
        for _, row in load(xls_path, sheet).iterrows():
            key = fold(row["name"])
            weights.setdefault(key, {"m": 0, "f": 0})[sex] += row["freq"]

    mapping = {
        key: ("m" if w["m"] >= w["f"] else "f")
        for key, w in sorted(weights.items())
    }
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(mapping, handle, ensure_ascii=False, separators=(",", ":"))
    print(f"{len(mapping)} entries -> {out_path}")


if __name__ == "__main__":
    main()
