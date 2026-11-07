"""
STEP 2: Read scores.csv and check which criteria move together.

Three measures are computed for every pair of criteria:

  Pearson   = do the two scores rise and fall together in a STRAIGHT LINE?
  Spearman  = do they rise and fall together at all (rank-based)? Better
              suited to 1-5 rating scales.
  dCor      = distance correlation. Catches ANY kind of dependence, not
              just straight-line or one-directional. It is 0 only when
              the two are truly independent. Always between 0 and 1.

Reading them side by side:
  all three low                    -> looks independent
  Pearson low, Spearman/dCor high  -> a real relationship that Pearson
                                      alone would have missed
  all three high                   -> clearly overlapping criteria
"""
import itertools
import os
import numpy as np
import pandas as pd

MIN_BLOGS = 4 
FLAG_AT = 0.7 #if score above 0.7, high correlation
GAP_AT = 0.25       # dCor minus |Pearson| at or above this = hidden link


def distance_correlation(x, y):
    """Szekely-Rizzo-Bakirov distance correlation for two 1-D arrays."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = len(x)
    a = np.abs(x[:, None] - x[None, :])
    b = np.abs(y[:, None] - y[None, :])
    A = a - a.mean(axis=0, keepdims=True) - a.mean(axis=1, keepdims=True) + a.mean()
    B = b - b.mean(axis=0, keepdims=True) - b.mean(axis=1, keepdims=True) + b.mean()
    dcov2 = (A * B).sum() / (n * n)
    dvarx = (A * A).sum() / (n * n)
    dvary = (B * B).sum() / (n * n)
    denom = np.sqrt(dvarx * dvary)
    if denom == 0:
        return 0.0
    return float(np.sqrt(max(dcov2, 0.0) / denom))


def dcor_matrix(data):
    cols = list(data.columns)
    out = pd.DataFrame(np.nan, index=cols, columns=cols)
    for a, b in itertools.combinations_with_replacement(cols, 2):
        if a == b:
            out.loc[a, b] = 1.0
            continue
        pair = data[[a, b]].dropna()
        if len(pair) < MIN_BLOGS:
            continue
        r = distance_correlation(pair[a].to_numpy(), pair[b].to_numpy())
        out.loc[a, b] = out.loc[b, a] = r
    return out


def main():
    if not os.path.exists("scores.csv"):
        raise SystemExit("scores.csv not found.")
    df = pd.read_csv("scores.csv", index_col="blog")
    n_blogs = len(df)
    print(f"Loaded {n_blogs} blog(s), {len(df.columns)} criteria.\n")

    # Drop criteria that are blank almost everywhere or never vary: they
    # cannot be correlated with anything and would only create NaN.
    usable = []
    for col in df.columns:
        values = df[col].dropna()
        if len(values) < MIN_BLOGS:
            print(f"  skipping '{col}': only {len(values)} blog(s) scored it")
        elif values.nunique() == 1:
            print(f"  skipping '{col}': every blog got the same score")
        else:
            usable.append(col)

    if len(usable) < 2:
        raise SystemExit("\nNot enough usable criteria to correlate.")

    data = df[usable]
    print(f"\nCorrelating {len(usable)} criteria.\n")

    pearson = data.corr(method="pearson", min_periods=MIN_BLOGS)
    spearman = data.corr(method="spearman", min_periods=MIN_BLOGS)
    dcor = dcor_matrix(data)

    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 50)

    for name, mat in [("PEARSON", pearson), ("SPEARMAN", spearman),
                      ("DISTANCE CORRELATION", dcor)]:
        print("=" * 70)
        print(name)
        print("=" * 70)
        print(mat.round(2).to_string())
        print()

    pearson.to_csv("pearson_matrix.csv")
    spearman.to_csv("spearman_matrix.csv")
    dcor.to_csv("dcor_matrix.csv")

    cols = list(data.columns)

    print("=" * 70)
    print(f"PAIRS THAT MIGHT NOT BE INDEPENDENT (any measure >= {FLAG_AT})")
    print("=" * 70)
    found = False
    for a, b in itertools.combinations(cols, 2):
        rp, rs, rd = pearson.loc[a, b], spearman.loc[a, b], dcor.loc[a, b]
        vals = [abs(v) for v in (rp, rs, rd) if pd.notna(v)]
        if vals and max(vals) >= FLAG_AT:
            found = True
            print(f"  {a}  vs  {b}")
            print(f"      pearson={rp:.2f}   spearman={rs:.2f}   dcor={rd:.2f}")
    if not found:
        print("  None. No pair crossed the threshold.")

    print("\n" + "=" * 70)
    print(f"HIDDEN LINKS: dCor exceeds |Pearson| by >= {GAP_AT}")
    print("(a real relationship that a straight-line test understates)")
    print("=" * 70)
    found = False
    for a, b in itertools.combinations(cols, 2):
        rp, rd = pearson.loc[a, b], dcor.loc[a, b]
        if pd.isna(rp) or pd.isna(rd):
            continue
        if rd - abs(rp) >= GAP_AT:
            found = True
            print(f"  {a}  vs  {b}")
            print(f"      |pearson|={abs(rp):.2f}   dcor={rd:.2f}")
    if not found:
        print("  None.")

    if n_blogs < 10:
        print(f"\nNOTE: {n_blogs} blogs is a very small sample. dCor in "
              "particular reads high on small samples.")
    elif n_blogs < 30:
        print(f"\nNOTE: {n_blogs} blogs is still small. dCor is biased "
              "upward below ~30 blogs.")

    print("\nSaved: pearson_matrix.csv, spearman_matrix.csv, dcor_matrix.csv")


if __name__ == "__main__":
    main()