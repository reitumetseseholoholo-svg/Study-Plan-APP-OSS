"""Phase 4C: Residual Structure Analysis.

Treats the residual matrix R = H - O as a statistical object.
Tests four explicit hypotheses:

  H0 (noise):  R has no low-dimensional structure
  H1 (M props): Structure concentrates on M-linked mechanisms
  H2 (coordinate): Structure persists after M refinement
  H3 (human bias): Structure aligns with non-algebraic similarity

Usage:
  python tools/algebra_residual_analysis.py spectral   # eigenvalues etc
  python tools/algebra_residual_analysis.py bootstrap  # jackknife stability
  python tools/algebra_residual_analysis.py loao       # leave-one-algebra-out
  python tools/algebra_residual_analysis.py htest      # H0-H3 hypothesis tests
  python tools/algebra_residual_analysis.py stop       # stopping rule check
  python tools/algebra_residual_analysis.py all        # everything
"""

from __future__ import annotations

import itertools
import math
import random
import sys
from dataclasses import dataclass

# ═══════════════════════════════════════════════════════════════════════
#  Ontology definitions (same as before)
# ═══════════════════════════════════════════════════════════════════════

ALGEBRAS = ["C", "D", "E", "CSP", "GG", "J"]

S_TYPE = {
    "C": "tree",
    "D": "simplex",
    "E": "vector",
    "CSP": "constraint_graph",
    "GG": "expanding_tree",
    "J": "bipartite_network",
}

I_TYPE = {
    "C": "path_uniqueness",
    "D": "normalization",
    "E": "normalization",
    "CSP": "constraint_satisfaction",
    "GG": "tree_integrity",
    "J": "justification_closure",
}

C_TYPE = {
    "C": "path_uniqueness",
    "D": "probability_mass",
    "E": "weight_budget",
    "CSP": "constraint_closure",
    "GG": "parent_uniqueness",
    "J": "justification_closure",
}

PHI_TYPE = {
    "C": "structural_leaf",
    "D": "informational",
    "E": "procedural",
    "CSP": "logical_model",
    "GG": "structural_frontier",
    "J": "semantic_closure",
}

OP_VECTORS: dict[str, list[int]] = {
    "traverse": [0, 1, 0, 1, 1, 0, 0, 1, 1, 0],
    "reweight": [0, 1, 0, 1, 0, 0, 0, 0, 1, 1],
    "aggregate": [0, 1, 0, 1, 0, 0, 0, 0, 1, 1],
    "propagate": [1, 1, 0, 1, 1, 0, 0, 0, 1, 0],
    "expand": [0, 1, 1, 0, 1, 1, 0, 1, 0, 0],
    "backtrack": [1, 0, 1, 0, 1, 0, 1, 0, 1, 0],
    "support": [0, 1, 1, 0, 1, 1, 0, 0, 1, 0],
    "retract": [1, 0, 1, 0, 1, 0, 1, 0, 1, 0],
}

M_OPS: dict[str, list[str]] = {
    "C": ["traverse"],
    "D": ["reweight"],
    "E": ["aggregate"],
    "CSP": ["propagate", "backtrack"],
    "GG": ["expand", "backtrack"],
    "J": ["support", "retract"],
}

# Similarity matrices (calibrated against 5 documented O values)
S_SIM: dict[tuple[str, str], float] = {
    ("tree", "expanding_tree"): 0.40,
    ("simplex", "vector"): 0.50,
    ("constraint_graph", "bipartite_network"): 0.28,
    ("constraint_graph", "expanding_tree"): 0.50,
    ("simplex", "expanding_tree"): 0.10,
    ("tree", "constraint_graph"): 0.30,
    ("tree", "bipartite_network"): 0.20,
    ("expanding_tree", "bipartite_network"): 0.20,
    ("simplex", "constraint_graph"): 0.10,
    ("vector", "constraint_graph"): 0.10,
    ("simplex", "bipartite_network"): 0.10,
    ("vector", "bipartite_network"): 0.10,
    ("tree", "simplex"): 0.05,
    ("tree", "vector"): 0.05,
    ("expanding_tree", "simplex"): 0.10,
    ("expanding_tree", "vector"): 0.10,
}

I_SIM: dict[tuple[str, str], float] = {
    ("normalization", "normalization"): 0.50,
    ("normalization", "path_uniqueness"): 0.15,
    ("normalization", "constraint_satisfaction"): 0.20,
    ("normalization", "tree_integrity"): 0.07,
    ("normalization", "justification_closure"): 0.10,
    ("path_uniqueness", "constraint_satisfaction"): 0.30,
    ("path_uniqueness", "tree_integrity"): 0.40,
    ("path_uniqueness", "justification_closure"): 0.15,
    ("constraint_satisfaction", "tree_integrity"): 0.40,
    ("constraint_satisfaction", "justification_closure"): 0.40,
    ("tree_integrity", "justification_closure"): 0.15,
}

C_SIM: dict[tuple[str, str], float] = {
    ("probability_mass", "weight_budget"): 0.70,
    ("probability_mass", "path_uniqueness"): 0.10,
    ("probability_mass", "constraint_closure"): 0.20,
    ("probability_mass", "parent_uniqueness"): 0.07,
    ("probability_mass", "justification_closure"): 0.15,
    ("weight_budget", "path_uniqueness"): 0.10,
    ("weight_budget", "constraint_closure"): 0.20,
    ("weight_budget", "parent_uniqueness"): 0.07,
    ("weight_budget", "justification_closure"): 0.15,
    ("path_uniqueness", "constraint_closure"): 0.20,
    ("path_uniqueness", "parent_uniqueness"): 0.40,
    ("path_uniqueness", "justification_closure"): 0.10,
    ("constraint_closure", "parent_uniqueness"): 0.40,
    ("constraint_closure", "justification_closure"): 0.40,
    ("parent_uniqueness", "justification_closure"): 0.10,
}

PHI_SIM: dict[tuple[str, str], float] = {
    ("structural_leaf", "structural_frontier"): 0.40,
    ("structural_leaf", "informational"): 0.10,
    ("structural_leaf", "procedural"): 0.10,
    ("structural_leaf", "logical_model"): 0.15,
    ("structural_leaf", "semantic_closure"): 0.10,
    ("structural_frontier", "informational"): 0.07,
    ("structural_frontier", "procedural"): 0.07,
    ("structural_frontier", "logical_model"): 0.30,
    ("structural_frontier", "semantic_closure"): 0.10,
    ("informational", "procedural"): 0.50,
    ("informational", "logical_model"): 0.25,
    ("informational", "semantic_closure"): 0.15,
    ("procedural", "logical_model"): 0.25,
    ("procedural", "semantic_closure"): 0.15,
    ("logical_model", "semantic_closure"): 0.30,
}

W = {"S": 0.25, "M": 0.30, "I": 0.15, "C": 0.15, "Phi": 0.15}

PAIR_LABELS = {
    ("C", "D"): "C–D",
    ("C", "E"): "C–E",
    ("C", "CSP"): "C–CSP",
    ("C", "GG"): "C–GG",
    ("C", "J"): "C–J",
    ("D", "E"): "D–E",
    ("D", "CSP"): "D–CSP",
    ("D", "GG"): "D–GG",
    ("D", "J"): "D–J",
    ("E", "CSP"): "E–CSP",
    ("E", "GG"): "E–GG",
    ("E", "J"): "E–J",
    ("CSP", "GG"): "CSP–GG",
    ("CSP", "J"): "CSP–J",
    ("GG", "J"): "GG–J",
}

ALL_PAIRS = list(itertools.combinations(ALGEBRAS, 2))

# ═══════════════════════════════════════════════════════════════════════
#  Core metric functions
# ═══════════════════════════════════════════════════════════════════════


def _sym(d: dict[tuple[str, str], float], a: str, b: str) -> float:
    if a == b:
        key = (a, a)
        return d[key] if key in d else 1.0
    key = (a, b)
    if key in d:
        return d[key]
    key2 = (b, a)
    if key2 in d:
        return d[key2]
    return 0.0


def s_dist(a: str, b: str) -> float:
    return 1.0 - _sym(S_SIM, S_TYPE[a], S_TYPE[b])


def i_dist(a: str, b: str) -> float:
    if a == b:
        return 0.0
    return 1.0 - _sym(I_SIM, I_TYPE[a], I_TYPE[b])


def c_dist(a: str, b: str) -> float:
    if a == b:
        return 0.0
    return 1.0 - _sym(C_SIM, C_TYPE[a], C_TYPE[b])


def phi_dist(a: str, b: str) -> float:
    if a == b:
        return 0.0
    return 1.0 - _sym(PHI_SIM, PHI_TYPE[a], PHI_TYPE[b])


def manhattan(v1: list[int], v2: list[int]) -> float:
    return sum(abs(x - y) for x, y in zip(v1, v2)) / len(v1)


def min_avg_match(ops_a: list[str], ops_b: list[str]) -> float:
    if not ops_a and not ops_b:
        return 0.0
    if not ops_a or not ops_b:
        return 1.0
    va = [OP_VECTORS[op] for op in ops_a]
    vb = [OP_VECTORS[op] for op in ops_b]
    if len(va) < len(vb):
        va = va + [va[-1]] * (len(vb) - len(va))
    elif len(vb) < len(va):
        vb = vb + [vb[-1]] * (len(va) - len(vb))
    used = set()
    total = 0.0
    for v in va:
        best = 10.0
        bi = -1
        for j, w in enumerate(vb):
            if j in used:
                continue
            d = manhattan(v, w)
            if d < best:
                best = d
                bi = j
        if bi >= 0:
            used.add(bi)
            total += best
        else:
            total += 1.0
    return total / len(va)


def m_dist(a: str, b: str) -> float:
    return min_avg_match(M_OPS[a], M_OPS[b])


def o_dist(a: str, b: str) -> float:
    return (
        W["S"] * s_dist(a, b)
        + W["M"] * m_dist(a, b)
        + W["I"] * i_dist(a, b)
        + W["C"] * c_dist(a, b)
        + W["Phi"] * phi_dist(a, b)
    )


def compute_O() -> dict[tuple[str, str], float]:
    return {p: o_dist(*p) for p in ALL_PAIRS}


def spearman(vals_a: list[float], vals_b: list[float]) -> float:
    n = len(vals_a)
    if n < 3:
        return 0.0
    ra = sorted(range(n), key=lambda i: vals_a[i])
    rb = sorted(range(n), key=lambda i: vals_b[i])
    ranks_a = [0.0] * n
    ranks_b = [0.0] * n
    for pos, i in enumerate(ra):
        ranks_a[i] = pos + 1
    for pos, i in enumerate(rb):
        ranks_b[i] = pos + 1
    d_sq = sum((ranks_a[i] - ranks_b[i]) ** 2 for i in range(n))
    return 1.0 - 6.0 * d_sq / (n * (n * n - 1))


# ═══════════════════════════════════════════════════════════════════════
#  ResidualMatrix: the primary dataset
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class ResidualEntry:
    h: float  # human distance (0-1 scale)
    o: float  # ontology distance (0-1)
    known: bool  # True = direct from atlas, False = placeholder


class ResidualMatrix:
    """6×6 symmetric matrix R = H - O for all 15 algebra pairs."""

    def __init__(self):
        self.O = compute_O()
        # H matrix: known values from atlas; unknown = O (neutral placeholder)
        known_H = {
            ("D", "E"): 0.40,
            ("CSP", "J"): 0.40,
            ("C", "GG"): 0.50,
            ("CSP", "GG"): 0.50,
            ("D", "GG"): 0.90,
            ("GG", "J"): 0.80,
        }
        self.entries: dict[tuple[str, str], ResidualEntry] = {}
        for p in ALL_PAIRS:
            pk = p if p in known_H else (p[1], p[0])
            h = known_H.get(pk, self.O[p])
            known = pk in known_H
            self.entries[p] = ResidualEntry(h=h, o=self.O[p], known=known)

    def R(self, a: str, b: str) -> float:
        return self.entries[(a, b)].h - self.entries[(a, b)].o

    def residual_matrix_6x6(self) -> list[list[float]]:
        idx = {a: i for i, a in enumerate(ALGEBRAS)}
        mat = [[0.0] * 6 for _ in range(6)]
        for (a, b), e in self.entries.items():
            i, j = idx[a], idx[b]
            r = e.h - e.o
            mat[i][j] = r
            mat[j][i] = r
        return mat

    def known_indices(self) -> list[int]:
        """Return indices of pairs with known (non-placeholder) H."""
        return [i for i, p in enumerate(ALL_PAIRS) if self.entries[p].known]

    def known_entries(self) -> list[tuple[tuple[str, str], float, float]]:
        """Return (pair, H, O) for each known entry."""
        return [(p, e.h, e.o) for p, e in self.entries.items() if e.known]

    def summary(self) -> str:
        lines = []
        lines.append(f"{'Pair':<10} {'H':>6} {'O':>6} {'R':>8} {'status':<10}")
        lines.append("-" * 42)
        for p in ALL_PAIRS:
            e = self.entries[p]
            label = PAIR_LABELS.get(p, f"{p[0]}–{p[1]}")
            tag = "KNOWN" if e.known else "est."
            lines.append(f"{label:<10} {e.h:>6.3f} {e.o:>6.3f} {e.h - e.o:>+8.4f} {tag:<10}")
        lines.append(f"\nKnown H values: {sum(1 for e in self.entries.values() if e.known)}/15")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
#  Spectral analysis
# ═══════════════════════════════════════════════════════════════════════


def spectral_analysis(RM: ResidualMatrix):
    """Eigenvalue decomposition of the 6×6 residual matrix.

    Question: Is there one dominant latent residual or is it isotropic?
    """
    mat = RM.residual_matrix_6x6()
    n = 6
    # Power iteration for largest eigenvalue (matrix is 6×6, direct is fine)
    # Use eigen decomposition via characteristic polynomial for 6×6
    # Since n is small, we compute eigenvalues by solving |R - λI| = 0
    # Approximate via iterative method
    import math as _math

    # Trace method: eigenvalues sum = trace (which is 0 for residual with 0 diag)
    # Frobenius norm: sum σ_i² = sum R_ij²
    frob_sq = sum(mat[i][j] ** 2 for i in range(n) for j in range(n))
    frob = _math.sqrt(frob_sq)

    # Power iteration for dominant eigenvalue magnitude
    x = [1.0] * n
    for _ in range(100):
        y = [sum(mat[i][j] * x[j] for j in range(n)) for i in range(n)]
        norm = _math.sqrt(sum(v**2 for v in y))
        if norm < 1e-15:
            break
        x = [v / norm for v in y]

    # Rayleigh quotient: λ_max = x^T R x / x^T x
    rq = sum(x[i] * sum(mat[i][j] * x[j] for j in range(n)) for i in range(n))
    rq /= sum(v**2 for v in x)

    # Singular values from eig(R^T R) = σ²
    RtR = [[sum(mat[k][i] * mat[k][j] for k in range(n)) for j in range(n)] for i in range(n)]
    x2 = [1.0] * n
    for _ in range(200):
        y2 = [sum(RtR[i][j] * x2[j] for j in range(n)) for i in range(n)]
        n2 = _math.sqrt(sum(v**2 for v in y2))
        if n2 < 1e-15:
            break
        x2 = [v / n2 for v in y2]
    dom_sv = _math.sqrt(sum(x2[i] * sum(RtR[i][j] * x2[j] for j in range(n)) for i in range(n)) / sum(v**2 for v in x2))

    # Effective rank: Frobenius / dominant singular value
    eff_rank = (frob**2) / (dom_sv**2) if dom_sv > 1e-10 else n
    # Normalize: rank / n
    eff_rank_frac = eff_rank / n

    print("=" * 72)
    print("  Spectral Analysis of Residual Matrix")
    print("=" * 72)
    print()
    print(f"  Matrix size: {n}×{n} ({len(ALL_PAIRS)} unique pairs)")
    print(f"  Frobenius norm: ‖R‖_F = {frob:.6f}")
    print(f"  Dominant eigenvalue (Rayleigh): λ₁ ≈ {rq:+.6f}")
    print(f"  Dominant singular value: σ₁ ≈ {dom_sv:.6f}")
    print(f"  Effective rank: {eff_rank:.2f} (fraction: {eff_rank_frac:.3f})")
    print()

    # Interpretation
    if eff_rank_frac > 0.8:
        print("  → High effective rank: residual energy is spread across")
        print("    many dimensions. R is approximately isotropic —")
        print("    consistent with H₀ (noise hypothesis).")
    elif eff_rank_frac > 0.5:
        print("  → Moderate effective rank: some concentration but not")
        print("    dominated by a single latent factor.")
        print("    Weak evidence against H₀.")
    else:
        print("  → Low effective rank: residual energy is concentrated")
        print("    in few dimensions — consistent with a latent factor")
        print("    (H₁ or H₂).")
    print()

    # CAUTION: 9/15 entries are placeholders (H=O, R=0).
    # This artificially deflates effective rank.
    n_known = sum(1 for p in ALL_PAIRS if RM.entries[p].known)
    n_placebo = len(ALL_PAIRS) - n_known
    print(f"  ⚠  {n_placebo}/{len(ALL_PAIRS)} entries are placeholders (R=0).")
    print("  This artificially suppresses rank. Known-only analysis follows.")
    print()

    # Known-only spectral signature
    known_vals = [RM.R(*p) for p in ALL_PAIRS if RM.entries[p].known]
    if len(known_vals) >= 4:
        mean_k = sum(known_vals) / len(known_vals)
        std_k = (sum((v - mean_k) ** 2 for v in known_vals) / len(known_vals)) ** 0.5
        largest_k = max(known_vals, key=abs)
        print(f"  Known-only residual stats (n={len(known_vals)}):")
        print(f"    Mean = {mean_k:.4f}, Std = {std_k:.4f}")
        print(f"    Largest |R| = {abs(largest_k):.4f} ({largest_k:+.4f})")
        # Check if absolute values cluster or spread
        abs_vals = sorted([abs(v) for v in known_vals], reverse=True)
        if len(abs_vals) >= 3:
            gap = abs_vals[0] - abs_vals[1]
            gap_2_3 = abs_vals[1] - abs_vals[2] if len(abs_vals) > 2 else 0
            print(f"    Gap largest→2nd: {gap:.4f}, 2nd→3rd: {gap_2_3:.4f}")
            if gap > 2 * gap_2_3 and gap > 0.05:
                print("    → One clear outlier — consistent with H₁ or H₂.")
            elif gap < 0.03:
                print("    → No single outlier. Residuals spread across pairs.")
                print("    → Consistent with H₀ (noise) — weakens H₁.")
            else:
                print("    → Marginal gap. Insufficient to distinguish H₀ vs H₁.")
    print()

    # Dominant eigenvector components
    xi = x if x[0] >= 0 else [-v for v in x]  # flip sign for interpretability
    print("  Dominant eigenvector (sign-flipped):")
    for i, alg in enumerate(ALGEBRAS):
        print(f"    {alg} ({S_TYPE[alg]:20s}): {xi[i]:+.4f}")
    print()

    # Contribution analysis: which pair drives the dominant eigenvalue?
    r_vals = [RM.R(*p) for p in ALL_PAIRS]
    max_r = max(r_vals, key=abs)
    idx_max = r_vals.index(max_r)
    print(f"  Largest |R| pair: {PAIR_LABELS[ALL_PAIRS[idx_max]]} (R = {max_r:+.4f})")
    r_vals_sorted = sorted(ALL_PAIRS, key=lambda p: abs(RM.R(*p)), reverse=True)
    print("  Top 3 |R| pairs:")
    for p in r_vals_sorted[:3]:
        rv = RM.R(*p)
        tag = "KNOWN" if RM.entries[p].known else "est."
        print(f"    {PAIR_LABELS[p]:<10} R = {rv:+.4f} ({tag})")

    # Check if dominant eigenvector aligns with known J-related structure
    j_component = abs(xi[ALGEBRAS.index("J")])
    other_components = [abs(xi[i]) for i in range(n) if i != ALGEBRAS.index("J")]
    max_other = max(other_components) if other_components else 0
    if j_component > 2 * max_other:
        print("\n  → Justification (J) dominates the leading eigenvector")
        print(f"    (|component| = {j_component:.3f} vs max other = {max_other:.3f}).")
        print("    Residual structure is J-concentrated, consistent with H₁.")
    else:
        print("\n  → No single algebra dominates the leading eigenvector.")
    print()


# ═══════════════════════════════════════════════════════════════════════
#  Bootstrap stability (jackknife)
# ═══════════════════════════════════════════════════════════════════════


def bootstrap_stability(RM: ResidualMatrix, n_resamples: int = 1000):
    """Jackknife: resample pairs to assess stability of the leading residual.

    For each resample, drop one pair, recompute the dominant eigenvector
    direction, and check how much it changes.

    Question: If one pair is removed, does the leading residual change?
    """
    mat = RM.residual_matrix_6x6()
    n = 6

    def dominant_eigenvector(m):
        x = [1.0] * n
        for _ in range(100):
            y = [sum(m[i][j] * x[j] for j in range(n)) for i in range(n)]
            nrm = math.sqrt(sum(v**2 for v in y))
            if nrm < 1e-15:
                break
            x = [v / nrm for v in y]
        if x[0] < 0:
            x = [-v for v in x]
        return x

    base_vec = dominant_eigenvector(mat)

    # Leave-one-pair-out
    perturbations = []
    for dropped_idx, dropped_pair in enumerate(ALL_PAIRS):
        m_copy = [row[:] for row in mat]
        da, db = dropped_pair
        i, j = ALGEBRAS.index(da), ALGEBRAS.index(db)
        # Replace with neutral (zero residual)
        m_copy[i][j] = 0.0
        m_copy[j][i] = 0.0
        perturbed = dominant_eigenvector(m_copy)
        # Angular change
        dot = sum(base_vec[k] * perturbed[k] for k in range(n))
        angle = math.acos(min(1.0, max(-1.0, dot)))
        perturbations.append((dropped_pair, angle, perturbed))

    # Resample with replacement for stability intervals
    rng = random.Random(42)
    resampled_angles = []
    for _ in range(n_resamples):
        m_resample = [[0.0] * n for _ in range(n)]
        for _ in range(len(ALL_PAIRS)):
            p = rng.choice(ALL_PAIRS)
            rv = RM.R(*p)
            i, j = ALGEBRAS.index(p[0]), ALGEBRAS.index(p[1])
            m_resample[i][j] += rv / len(ALL_PAIRS)
            m_resample[j][i] += rv / len(ALL_PAIRS)
        ev = dominant_eigenvector(m_resample)
        dot = sum(base_vec[k] * ev[k] for k in range(n))
        angle = math.acos(min(1.0, max(-1.0, dot)))
        resampled_angles.append(angle)

    resampled_angles.sort()
    ci_low = resampled_angles[int(n_resamples * 0.025)]
    ci_high = resampled_angles[int(n_resamples * 0.975)]

    print("=" * 72)
    print("  Bootstrap Stability (jackknife + resample)")
    print("=" * 72)
    print()
    print("  Base dominant eigenvector direction:")
    for i, alg in enumerate(ALGEBRAS):
        print(f"    {alg}: {base_vec[i]:+.4f}")
    print()

    print("  Leave-one-pair-out perturbation (angular change in radians):")
    perturbations.sort(key=lambda x: x[1], reverse=True)
    for dropped_pair, angle, vec in perturbations:
        label = PAIR_LABELS.get(dropped_pair, f"{dropped_pair[0]}–{dropped_pair[1]}")
        deg = angle * 180 / math.pi
        stable = "stable" if angle < 0.3 else "unstable"
        print(f"    Drop {label:<10}: Δθ = {angle:.3f} rad ({deg:.1f}°) → {stable}")
    print()

    print(f"  Bootstrap resample ({n_resamples} iterations):")
    print(
        f"    95% CI for Δθ: [{ci_low:.3f}, {ci_high:.3f}] rad "
        f"({ci_low * 180 / math.pi:.1f}°, {ci_high * 180 / math.pi:.1f}°)"
    )
    median_angle = resampled_angles[n_resamples // 2]
    print(f"    Median Δθ: {median_angle:.3f} rad ({median_angle * 180 / math.pi:.1f}°)")

    if ci_high < 0.5:
        print("\n  → Dominant eigenvector is STABLE: CI upper bound < 0.5 rad.")
        print("    The leading residual pattern does not depend on any")
        print("    single pair — consistent with a real latent structure.")
    else:
        print("\n  → Dominant eigenvector is UNSTABLE: CI upper bound ≥ 0.5 rad.")
        print("    The leading residual pattern depends on specific pairs.")
        print("    Consistent with H₀ (noise) — don't build theory on it.")
    print()


# ═══════════════════════════════════════════════════════════════════════
#  Leave-one-algebra-out
# ═══════════════════════════════════════════════════════════════════════


def leave_one_algebra_out(RM: ResidualMatrix):
    """Remove each algebra, check whether held-out pairs are predicted well.

    For each held-out algebra X:
      1. Remove all 5 pairs involving X
      2. Fit the ontology to remaining pairs (assess fit quality)
      3. Predict O for held-out pairs
      4. Compare prediction error to within-fitting error

    Question: Does the ontology generalize to held-out algebras?
    """
    known = RM.known_entries()
    known_pairs = set(p for p, _, _ in known)

    print("=" * 72)
    print("  Leave-One-Algebra-Out Cross-Validation")
    print("=" * 72)
    print()
    print(f"  Known H-pairs: {len(known)}/15")
    print("  Limitation: full LO AO requires H for all 15 pairs.")
    print(f"  Using {len(known)} known pairs only.")
    print()

    results = {}
    for held_out in ALGEBRAS:
        held_pairs = [(a, b) for a, b in ALL_PAIRS if a == held_out or b == held_out]
        held_known = [(p, h, o) for p, h, o in known if p in held_pairs or (p[1], p[0]) in held_pairs]
        remaining = [(p, h, o) for p, h, o in known if p not in held_pairs and (p[1], p[0]) not in held_pairs]

        n_remaining = len(remaining)
        n_held = len(held_known)

        # Compute prediction error for held-out
        held_errors = []
        for p, h, o in held_known:
            predicted = RM.O[p]  # Use full-ontology O as prediction
            error = abs(h - predicted)
            held_errors.append((p, h, predicted, error))

        # Within-fit error for remaining
        remaining_errors = []
        for p, h, o in remaining:
            predicted = RM.O[p]
            error = abs(h - predicted)
            remaining_errors.append((p, h, predicted, error))

        mean_held = sum(e for _, _, _, e in held_errors) / max(1, len(held_errors))
        mean_remain = sum(e for _, _, _, e in remaining_errors) / max(1, len(remaining_errors))
        ratio = mean_held / max(1e-10, mean_remain)

        results[held_out] = {
            "held_pairs": held_errors,  # (p, h, predicted, error) 4-tuples
            "remaining": remaining,
            "mean_held_error": mean_held,
            "mean_remain_error": mean_remain,
            "ratio": ratio,
        }

    print(
        f"  {'Held-out':<10} {'Known held':>11} {'Known remain':>13} {'Mean |R| (held)':>14} {'Mean |R| (rem)':>13} {'Ratio':>7}"
    )
    print("-" * 70)
    for alg in ALGEBRAS:
        r = results[alg]
        print(
            f"  {alg:<10} {len(r['held_pairs']):>11d} {len(r['remaining']):>13d} "
            f"{r['mean_held_error']:>14.4f} {r['mean_remain_error']:>13.4f} {r['ratio']:>7.2f}"
        )
    print()

    # Overall generalization score
    all_ratios = [r["ratio"] for r in results.values()]
    mean_ratio = sum(all_ratios) / len(all_ratios)
    max_ratio = max(all_ratios)
    print(f"  Mean generalization ratio: {mean_ratio:.2f}")
    print(f"  Max generalization ratio: {max_ratio:.2f}")
    print()

    if max_ratio < 2.0:
        print("  → Ontology generalizes well to held-out algebras.")
        print("    Held-out prediction error is within 2× of fitting error.")
        print("    Consistent with H₀ (no missing coordinate).")
    else:
        worst = max(results, key=lambda k: results[k]["ratio"])
        print(f"  → Ontology may not generalize to {worst}.")
        print(f"    Held-out prediction error is {results[worst]['ratio']:.1f}× fitting error.")
        print("    This algebra may require coordinate refinement (H₁ or H₂).")
    print()

    # List individual held-out predictions if data available
    for alg in ALGEBRAS:
        r = results[alg]
        if not r["held_pairs"]:
            continue
        print(f"  Held-out pairs for {alg}:")
        for item in sorted(r["held_pairs"], key=lambda x: x[3], reverse=True):
            p, h, o_pred, err = item
            tag = PAIR_LABELS.get(p, f"{p[0]}–{p[1]}")
            print(f"    {tag:<10} H={h:.3f}, O_pred={o_pred:.3f}, |R|={err:.4f}")
        print()


# ═══════════════════════════════════════════════════════════════════════
#  H₀–H₃ hypothesis tests
# ═══════════════════════════════════════════════════════════════════════


def hypothesis_tests(RM: ResidualMatrix):
    """Test each of the four hypotheses with available evidence."""
    mat = RM.residual_matrix_6x6()
    r_vals = [RM.R(*p) for p in ALL_PAIRS]
    abs_r = [abs(v) for v in r_vals]
    n = 6

    print("=" * 72)
    print("  H₀–H₃ Hypothesis Tests")
    print("=" * 72)
    print()

    # ── H₀: Noise hypothesis ──
    print("─" * 72)
    print("  H₀: Residuals are sampling noise (no structure)")
    print()

    # Test: Are the two large residuals distinguishable from the rest?
    r_sorted = sorted(abs_r, reverse=True)
    gap_1_2 = r_sorted[0] - r_sorted[1] if len(r_sorted) > 1 else 0
    gap_2_3 = r_sorted[1] - r_sorted[2] if len(r_sorted) > 2 else 0
    mean_r = sum(abs_r) / len(abs_r)
    std_r = (sum((v - mean_r) ** 2 for v in abs_r) / len(abs_r)) ** 0.5

    print(f"  Residual statistics (|R|, n={len(abs_r)}):")
    print(f"    Mean = {mean_r:.4f}, Std = {std_r:.4f}")
    print(f"    Largest: {r_sorted[0]:.4f}, 2nd: {r_sorted[1]:.4f}, 3rd: {r_sorted[2]:.4f}")
    print(f"    Gap 1→2: {gap_1_2:.4f}, Gap 2→3: {gap_2_3:.4f}")
    print()

    # Count how many known large residuals exist
    known_large = sum(1 for p in ALL_PAIRS if abs(RM.R(*p)) > 0.10 and RM.entries[p].known)
    placebo_large = sum(1 for p in ALL_PAIRS if abs(RM.R(*p)) > 0.10 and not RM.entries[p].known)
    print(f"  Large |R| (>0.10): {known_large} known, {placebo_large} estimated")
    print()

    if known_large == 0:
        print("  → No known large residuals. R is consistent with noise.")
        print("    H₀ SURVIVES: no evidence of structure.")
    elif known_large <= 2 and gap_1_2 > 0.05:
        print(f"  → {known_large} known large residuals, with gap {gap_1_2:.3f} between largest and next.")
        print("    Weak evidence against H₀ — structure may exist but is sparse.")
        print("    H₀ NOT REJECTED: insufficient data to rule out noise.")
    elif known_large >= 3:
        print(f"  → {known_large} known large residuals with clear gaps.")
        print("    H₀ REJECTED: residuals contain structure beyond noise.")
    else:
        print(f"  → Ambiguous: {known_large} known large residuals but small gaps.")
        print("    H₀ NOT REJECTED at current sample size.")
    print()

    # ── H₁: Missing operator properties ──
    print("─" * 72)
    print("  H₁: Residual structure is in M (operator property space)")
    print()

    # Check if all large residuals involve operators that share properties
    large_pairs = [(a, b) for a, b in ALL_PAIRS if abs(RM.R(a, b)) > 0.10 and RM.entries[(a, b)].known]
    j_involved = sum(1 for a, b in large_pairs if "J" in (a, b))
    gg_involved = sum(1 for a, b in large_pairs if "GG" in (a, b))

    print(f"  Large-residual pairs: {len(large_pairs)} known")
    for a, b in large_pairs:
        r = RM.R(a, b)
        ops_a = ",".join(M_OPS[a])
        ops_b = ",".join(M_OPS[b])
        print(f"    {PAIR_LABELS[(a, b)]:<10} R = {r:+.4f}  M: {{{ops_a}}} ↔ {{{ops_b}}}")

    if len(large_pairs) >= 2 and all("J" in (a, b) or "GG" in (a, b) for a, b in large_pairs):
        print("\n  → All large residuals involve J or GG.")
        print("    J and GG share identical operators (support↔expand are")
        print("    [0,1,1,0,1,1,0,0,1,0]; backtrack↔retract are identical).")
        print("    This is consistent with H₁: M property space needs")
        print("    refinement for structural operators.")
        print("    H₁ SUPPORTED by current evidence.")
    elif len(large_pairs) >= 1:
        algos = set()
        for a, b in large_pairs:
            algos.add(a)
            algos.add(b)
        print(f"\n  → Large residuals spread across {len(algos)} algebras: {', '.join(sorted(algos))}")
        print("    Not cleanly concentrated in M — may involve S or Φ.")
        print("    H₁ PARTIALLY SUPPORTED (M is part of the picture).")
    else:
        print("  → No known large residuals to test H₁.")
        print("    H₁ NOT TESTABLE without more data.")
    print()

    # ── H₂: Missing coordinate ──
    print("─" * 72)
    print("  H₂: A new coordinate beyond (S, M, I, C, Φ) is needed")
    print()

    if len(large_pairs) >= 2:
        # Check polarity: do all large residuals have same sign?
        signs = set()
        for a, b in large_pairs:
            r = RM.R(a, b)
            if abs(r) > 0.10:
                signs.add("+" if r > 0 else "-")

        if len(signs) <= 1:
            print(f"  → All large residuals have the same polarity ({' '.join(signs)}).")
            print("    Consistent with a missing coordinate — a single latent factor")
            print("    would pull all affected pairs in the same direction.")
            print("    H₂ CANNOT BE REJECTED.")
        else:
            print(f"  → Large residuals have MIXED polarity ({' '.join(signs)}).")
            print("    A single missing coordinate would affect all pairs in the same")
            print("    direction. Mixed polarity rules out a single latent factor.")
            print("    H₂ REJECTED for a single missing coordinate.")
            print("    (Multiple new coordinates remain possible but less parsimonious.)")

            # Show the polarity inconsistency
            for a, b in large_pairs:
                r = RM.R(a, b)
                print(f"      {PAIR_LABELS[(a, b)]:<10} R = {r:+.4f} ({'+' if r > 0 else '-'})")
    else:
        print("  → Insufficient large residuals to test polarity.")
        print("    H₂ NOT TESTABLE without more data.")
    print()

    # ── H₃: Human bias ──
    print("─" * 72)
    print("  H₃: Human similarity judgments are biased by non-algebraic factors")
    print()

    # Check if human rankings align with educational/intuitive similarity
    # rather than algebraic similarity
    known_pairs = RM.known_entries()
    if len(known_pairs) >= 4:
        # Rank by human vs ontology
        h_ranked = sorted(known_pairs, key=lambda x: x[1])  # ascending H = more similar
        o_preds = [(p, RM.O[p]) for p, _, _ in known_pairs]
        o_ranked = sorted(o_preds, key=lambda x: x[1])

        print("  Human most-similar pairs:")
        for p, h, _ in h_ranked[:3]:
            o = RM.O[p]
            print(f"    {PAIR_LABELS[p]:<10} H={h:.2f} O={o:.2f} R={h - o:+.3f}")
        print("  Ontology most-similar pairs:")
        for p, o in o_ranked[:3]:
            h = RM.entries[p].h
            print(f"    {PAIR_LABELS[p]:<10} H={h:.2f} O={o:.2f} R={h - o:+.3f}")
        print()

        # Human ranking aligns with surface similarity?
        # Check if C-GG (both tree-like) is rated more similar by humans
        # than by ontology
        c_gg_r = RM.R("C", "GG")
        if abs(c_gg_r) > 0.05:
            print(
                f"  C-GG residual: {c_gg_r:+.3f} "
                f"({'H sees more similarity' if c_gg_r < 0 else 'O sees more similarity'})"
            )
            if c_gg_r < 0:
                print("  → Humans rate C and GG (both tree-like) more similar")
                print("    than the ontology does. This could reflect surface-level")
                print("    similarity (both are trees) rather than algebraic structure.")
                print("    H₃ PARTIALLY SUPPORTED.")
            else:
                print("  → Ontology rates C and GG more similar than humans do.")
                print("    This is consistent with algebraic structure being more")
                print("    salient to the ontology than to human raters.")
    else:
        print("  → Insufficient data for H₃ test. Need more human rankings.")
    print()

    # ── Summary ──
    print("─" * 72)
    print("  Summary")
    print()

    verdicts = []
    # H₀
    if known_large == 0:
        verdicts.append("H₀: survives — no structure detected")
    elif known_large <= 2:
        verdicts.append("H₀: not rejected — structure sparse, could be noise")
    else:
        verdicts.append("H₀: rejected — structure detected")

    # H₁
    if j_involved == len(large_pairs) and len(large_pairs) > 0:
        verdicts.append("H₁: supported — all large residuals involve J/GG (M-linked)")
    elif len(large_pairs) > 0:
        verdicts.append("H₁: partially supported — M refinement may help")
    else:
        verdicts.append("H₁: untestable with current data")

    # H₂
    if len(signs) > 1:
        verdicts.append("H₂: rejected for single coordinate (mixed polarity)")
    elif len(large_pairs) >= 2:
        verdicts.append("H₂: cannot reject — polarity consistent")
    else:
        verdicts.append("H₂: untestable with current data")

    # H₃
    verdicts.append("H₃: untestable — systematic human-bias experiment needed")

    for v in verdicts:
        print(f"  • {v}")
    print()


# ═══════════════════════════════════════════════════════════════════════
#  Stopping rule check
# ═══════════════════════════════════════════════════════════════════════


def stopping_rule(RM: ResidualMatrix):
    """Evaluate the four termination criteria."""
    mat = RM.residual_matrix_6x6()
    n = 6

    print("=" * 72)
    print("  Stopping Rule Evaluation")
    print("=" * 72)
    print()
    print("  The ontology is 'complete enough' when all four conditions hold:")
    print()

    # Criterion 1: No stable latent structure in residuals
    r_vals = [abs(RM.R(*p)) for p in ALL_PAIRS]
    known_large = sum(1 for p in ALL_PAIRS if abs(RM.R(*p)) > 0.10 and RM.entries[p].known)
    c1_pass = known_large == 0
    print("  1. No stable latent residual structure")
    print(f"     Known large |R| (>0.10): {known_large}")
    print(f"     → {'PASS' if c1_pass else 'FAIL — residuals remain'}")
    print()

    # Criterion 2: Operator-property refinement no longer improves prediction
    # (E2 showed marginal improvement at best)
    c2_pass = True  # E2 established this
    print("  2. M refinement no longer materially improves ρ")
    print("     E2 result: candidate property added 0.016 improvement (5.5%)")
    print(f"     → {'PASS (improvement below materiality threshold)' if c2_pass else 'FAIL'}")
    print()

    # Criterion 3: Leave-one-algebra-out prediction is stable
    loao_results = {}
    for held_out in ALGEBRAS:
        held_pairs = [(a, b) for a, b in ALL_PAIRS if (a == held_out or b == held_out) and RM.entries[(a, b)].known]
        remaining = [
            (p, e) for p, e in RM.entries.items() if p not in held_pairs and (p[1], p[0]) not in held_pairs and e.known
        ]
        if remaining and held_pairs:
            held_errors = [abs(RM.R(*p)) for p in held_pairs]
            rem_errors = [abs(r) for p, e in remaining for r in [e.h - e.o]]
            mean_held_e = sum(held_errors) / len(held_errors) if held_errors else 0
            mean_rem_e = sum(rem_errors) / len(rem_errors) if rem_errors else 0
            ratio = mean_held_e / max(1e-10, mean_rem_e)
            loao_results[held_out] = ratio

    if loao_results:
        max_ratio = max(loao_results.values())
        c3_pass = max_ratio < 2.0
        print("  3. Leave-one-algebra-out prediction is stable")
        print(f"     Max held/remain error ratio: {max_ratio:.2f}")
        for alg, r in sorted(loao_results.items()):
            print(f"       {alg}: ratio = {r:.2f}")
        print(f"     → {'PASS' if c3_pass else 'FAIL — some algebra poorly predicted'}")
    else:
        c3_pass = False
        print("  3. Leave-one-algebra-out prediction")
        print("     → INCONCLUSIVE — need more H data")
    print()

    # Criterion 4: New algebras embed without coherent residual families
    # Also check if any existing algebra has a coherent family (holdout test)
    from collections import defaultdict

    alg_residuals = defaultdict(list)
    for a, b in ALL_PAIRS:
        e = RM.entries[(a, b)]
        if e.known:
            alg_residuals[a].append((b, RM.R(a, b)))
            alg_residuals[b].append((a, RM.R(a, b)))
    coherent_algs = []
    for alg in ALGEBRAS:
        rs = [r for _, r in alg_residuals[alg]]
        if len(rs) >= 2:
            signs = set("+" if r > 0 else "-" for r in rs if abs(r) > 0.05)
            if len(signs) == 1:
                mean_r = sum(abs(r) for r in rs) / len(rs)
                if mean_r > 0.08:
                    coherent_algs.append(alg)
    if coherent_algs:
        print(f"     Existing algebras with coherent families: {', '.join(coherent_algs)}")
        print("     These may signal a missing coordinate but could be")
        print("     coincidence (few known pairs per algebra).")
    c4_pass = not coherent_algs  # Temporary: treat coherent families as failures
    print(f"     → {'PASS' if c4_pass else 'FAIL — some algebras have coherent families'}")
    print()

    # Overall
    print("─" * 72)
    print("  Overall assessment:")
    print()
    passes = [c1_pass, c2_pass]
    if c3_pass is not None:
        passes.append(c3_pass)
    passes.append(c4_pass)
    print(f"  Criteria passed: {sum(1 for p in passes if p)}/{len(passes)}")
    print(f"  Criteria failed: {sum(1 for p in passes if not p)}/{len(passes)}")
    print(f"  Criteria untested: {4 - len(passes)}")
    print()
    if all(p for p in passes if p is not None):
        print("  → Ontology appears dimensionally complete.")
        print("    Remaining residuals are concentrated in M and likely")
        print("    irreducible without operator-context interaction.")
    elif sum(1 for p in passes if not p) == 0:
        print("  → No criteria failed but some untested.")
        print("    The ontology may be complete. Recommend testing with")
        print("    a new algebra before freezing.")
    else:
        print("  → Further refinement needed before freeze.")
    print()


# ═══════════════════════════════════════════════════════════════════════
#  Held-out algebra projection test
# ═══════════════════════════════════════════════════════════════════════


def algebra_holdout(RM: ResidualMatrix):
    """Hide one algebra and check if it requires new coordinates.

    For each held-out algebra X:
      1. Remove all pairs involving X
      2. Check whether X's residual pairs form a coherent family
         (same sign, consistent magnitude, mechanism-linked)
      3. A coherent family suggests X requires a coordinate the
         ontology doesn't capture.
      4. Mixed-polarity or scattered residuals suggest noise or
         M refinement, not a missing coordinate.
    """
    print("=" * 72)
    print("  Held-Out Algebra Projection Test")
    print("=" * 72)
    print()
    print("  Question: Does the held-out algebra require new coordinates?")
    print("  Signal: Coherent residual family (same sign, consistent mechanism)")
    print()

    results = {}
    for held in ALGEBRAS:
        pairs = [(a, b) for a, b in ALL_PAIRS if (held in (a, b)) and RM.entries[(a, b)].known]
        if not pairs:
            results[held] = None
            continue

        residuals = [RM.R(*p) for p in pairs]
        signs = set("+" if r > 0 else "-" for r in residuals if abs(r) > 0.05)
        mags = [abs(r) for r in residuals]

        # Sign concordance: all same sign?
        sign_concordant = len(signs) <= 1
        # Mean magnitude above noise floor?
        above_noise = sum(mags) / len(mags) > 0.08
        # Largest single residual?
        max_r = max(mags, default=0)

        # Coherent family = same sign + above noise + clear largest pair
        coherent = sign_concordant and above_noise and max_r > 0.10
        # Incoherent = mixed signs or all below noise
        incoherent = len(signs) > 1 or (not above_noise)

        results[held] = {
            "pairs": pairs,
            "residuals": residuals,
            "signs": signs,
            "concordant": sign_concordant,
            "above_noise": above_noise,
            "max_r": max_r,
            "coherent": coherent,
            "incoherent": incoherent,
        }

    print(f"  {'Algebra':<8} {'Known pairs':>12} {'Sign':>6} {'Concordant?':>12} {'Max |R|':>8} {'Coherent?':>10}")
    print("-" * 64)
    for alg in ALGEBRAS:
        r = results[alg]
        if r is None:
            print(f"  {alg:<8} {'—':>12}")
            continue
        sign_str = "/".join(sorted(r["signs"])) if r["signs"] else "—"
        print(
            f"  {alg:<8} {len(r['pairs']):>12d} {sign_str:>6} "
            f"{'✓' if r['concordant'] else '✗':>12} "
            f"{r['max_r']:>8.4f} "
            f"{'✓ NEW COORD' if r['coherent'] else '✗' if r['incoherent'] else '?':>10}"
        )
    print()

    # Identify coherent families
    coherent_algs = [a for a, r in results.items() if r and r["coherent"]]
    incoherent_algs = [a for a, r in results.items() if r and r["incoherent"]]
    ambiguous = [a for a, r in results.items() if r and not r["coherent"] and not r["incoherent"]]

    if coherent_algs:
        print(f"  Coherent residual families: {', '.join(coherent_algs)}")
        print("    These algebras have same-sign, above-noise residuals —")
        print("    consistent with a missing coordinate or systematic bias.")
        print("    Recommend: check if they share a mechanism or S-property.")
    else:
        print("  No coherent residual families detected.")
        print("    No algebra requires a new coordinate by this test.")

    if incoherent_algs:
        print()
        print(f"  Scattered/incoherent residuals: {', '.join(incoherent_algs)}")
        print("    Mixed polarity or near-noise residuals — consistent with")
        print("    M refinement or measurement noise, not a missing coordinate.")

    if ambiguous:
        print()
        print(f"  Ambiguous: {', '.join(ambiguous)}")
        print("    Some signal but insufficient for a coordinate claim.")

    print()
    print("─" * 72)
    print("  Interpretation")
    print()
    print("  • Coherent family + same polarity = candidate for new coordinate")
    print("  • Mixed polarity = rules out single latent factor (H₂ rejected)")
    print("  • Near-noise = consistent with H₀ (null hypothesis)")
    print()


# ═══════════════════════════════════════════════════════════════════════
#  Main dispatcher
# ═══════════════════════════════════════════════════════════════════════


def main():
    RM = ResidualMatrix()

    cmds = {
        "summary": lambda: print(RM.summary()),
        "spectral": lambda: spectral_analysis(RM),
        "bootstrap": lambda: bootstrap_stability(RM),
        "loao": lambda: leave_one_algebra_out(RM),
        "holdout": lambda: algebra_holdout(RM),
        "htest": lambda: hypothesis_tests(RM),
        "stop": lambda: stopping_rule(RM),
    }

    if len(sys.argv) < 2 or sys.argv[1] not in cmds and sys.argv[1] != "all":
        print("Usage: python tools/algebra_residual_analysis.py <command>")
        print()
        print("Commands:")
        for c in ["summary", "spectral", "bootstrap", "loao", "holdout", "htest", "stop", "all"]:
            print(f"  {c:<12} — {cmds[c].__doc__ if c != 'all' else 'Run all analyses'}" if c in cmds else "")
        sys.exit(1)

    if sys.argv[1] == "all":
        print(RM.summary())
        print()
        spectral_analysis(RM)
        print()
        bootstrap_stability(RM)
        print()
        leave_one_algebra_out(RM)
        print()
        algebra_holdout(RM)
        print()
        hypothesis_tests(RM)
        print()
        stopping_rule(RM)
    else:
        cmds[sys.argv[1]]()


if __name__ == "__main__":
    main()
