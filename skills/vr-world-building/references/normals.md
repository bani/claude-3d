# Normals

Detail for the *Normals* section of SKILL.md.

## Contents

1. Making inversions visible in Blender
2. Inversion or hole
3. Tests by topology
4. Validating a test
5. Failure modes and their detectors
6. Flipping
7. Winding and vertex normals in Unity
8. Double-sided material fallback
9. Geometry that is correct by construction

---

## 1. Making inversions visible in Blender

- **Material backface culling + render** (EEVEE or Cycles). Inverted faces disappear, as they will in Unity.
- **Face Orientation overlay.** It draws the far half of every closed solid red from the current viewpoint; that is expected. Only these indicate an inversion: a near surface facing the camera drawn red; a top cap drawn red when seen from above; a wall top with no blue (up-facing) faces.

Both are for spotting problems. The programmatic sweep is the check.

## 2. Inversion or hole

| | Inverted face | Missing face (hole) |
|---|---|---|
| Blender viewport (double-sided) | Looks correct | See-through |
| Unity | Invisible | See-through |
| Diagnose with | Normals tests (§3) | Boundary-edge count (edges with one face) and non-manifold-edge count |
| Fix | Flip winding | Add geometry |

Flipping cannot fill a hole. Check topology before changing winding.

## 3. Tests by topology

### Closed solid — signed volume per island > 0

Implementation: `islands_signed_volume()` in `scripts/normals_audit.py`. `bm.calc_volume(signed=True)` returns a single whole-mesh value, so a small inverted island is masked by a large correct one; it is not a substitute.

- Compute per connected island, about that island's own centroid, in Python floats (float64). `vert.co` is float32, and summing about the world origin loses all precision beyond ~100 m.
- A loose vertex is a one-vertex island with volume exactly 0.0. Test `v < 0`, not `v <= 0`, and report loose vertices separately from inversions. `bmesh.ops.convex_hull` leaves interior points in the mesh: delete its `geom_interior` and `geom_unused` outputs.

### Open shell — area-weighted `frac_up`

Heightfields, ribbons, decks, flat rings, water surfaces. Correct ≈ 1.0, inverted ≈ 0.0; `normals_audit.py` flags ≤ 0.02.

- Never use signed volume on an open mesh: the result depends on the world origin.
- If an object should be judged by volume, build it closed. An open composite (e.g. column + bowl) can read negative volume while correctly oriented, and flipping it then inverts it.

### Interior void — faces point at the centroid

Tunnels, caves, dome interiors. Correct normals face the player, so signed volume is negative, and that is correct. Test the fraction of faces with `dot(normal, centroid − face_centre) > 0`; correct > 0.5.

- The reference point is the vertex centroid. On a strongly curved void (U-bend, ring) the wall on the inside of the bend faces away from the centroid and reads as inverted, which can hide or fake a real fault. Test curved voids in segments.

### Horizontal tube — ray test

Logs, branches, pipes, tree crowns, roots. `frac_up` reads 0.48–0.52 whichever way the faces point. Cast rays inward from outside the bounding sphere and count front-facing first hits.

- Needs the object in the active view layer; meaningful only on closed meshes.
- The baseline is not 100 % front-facing: single-sided foliage legitimately reads back-facing (≈ 30 % on one tree). Compare a variant with its source mesh, not with an ideal.

## 4. Validating a test

Before a sweep, build a correct primitive and a flipped copy **of the topology the test targets**, at a realistic distance from the origin (e.g. 150 m, where float32 error appears), and assert they disagree in the expected direction:

```python
assert val["_probe_good"] > 0 > val["_probe_flipped"], val
```

The control's topology has to match: a cube reads `frac_up` 0.167 flipped or not (one face in six points up either way), so it cannot validate the open-shell test.

`normals_audit.py` validates the closed test (cube) and the open test (grid) this way and aborts if a control disagrees. The interior and tube tests have no control; before relying on them, run them on a real object and on a flipped copy of it.

The same rule covers every audit: a check that reads a buffer asserts the buffer holds real data, and a check that cannot run reports that it did not run.

## 5. Failure modes and their detectors

No single operator catches all of these. Revolve, sweep, extrude and lathe builders produce most of them.

- **a. Whole-island inversion.** Signature: a closed island with negative signed volume, or an open island whose area-weighted normals point at its own centroid. Common on surfaces of revolution built profile-first. Fix: flip the island.
- **b. Mixed winding within one island.** Signature: `|signed volume| > bounding-box volume`, impossible for a clean solid. A whole-island flip only mirrors the problem. Fix: recalculate outside, then flip any island that settled inward. Guard with the volume/bbox ratio so boxes (ratio = 1) are untouched.
- **c. Open shell with near-zero volume** (coping rings, basin rims, hedge tops, washers). Both volume tests miss it. Detect by shape-specific signature: a top cap with no up-facing faces, a flat ring whose faces all point down. Scope the fix to named objects: planter bottoms, vase rims and lamp caps are legitimately down-facing.
- **d. Many disconnected islands.** `recalc_face_normals` orients each island arbitrarily (≈ 50 % wrong on 300 loose discs). Orient each island against a known reference (trunk axis, normal of the surface it sits on), then measure.
- **e. A single open sheet.** `recalc_face_normals` has no volume to reason about and can leave the whole sheet inverted (`frac_up = 0.0`). Measure `frac_up` and flip explicitly.
- **f. Decimation that collapsed thin parts into tiny closed sacs.** Signature: thousands of islands of ~5 faces and an elevated back-facing hit fraction. Recalc cannot repair it — it orients each sac outward from its own inverted volume. Fix: include the back-facing fraction in the decimation-ratio search so such ratios are rejected.
- **g. Hollow shell whose wall is the enclosed volume.** Proof of correctness: closed + 0 non-manifold edges + 0 inconsistently wound edge pairs + signed volume > 0. Do not classify faces as inner or outer by radius; that mixes the two surfaces where they come close.

## 6. Flipping

- **Flip unique mesh datablocks, not objects.** Objects sharing a mesh would flip it once each.
- **In a multi-step fix, order matters and the bundle is usually not idempotent.** A step that deliberately adds an inward-facing shell (e.g. a dome interior) runs last, or the inverted-island pass flips it back out. Run the bundle once, after merge, and say so in the code.
- **Modifiers move the evaluated surface away from the base mesh.** Before any raycast-driven mesh edit (deleting faces, moving vertices), check `ob.modifiers` and compare `len(ob.data.polygons)` with the evaluated mesh's polygon count. A Solidify modifier can offset the evaluated surface by metres, so edits land in the wrong place.

## 7. Winding and vertex normals in Unity

A Unity mesh stores triangle winding (which side is front) and vertex normals (shading) independently; Unity does not derive one from the other.

- **Do not make a surface double-sided by duplicating faces with reversed winding.** The coincident faces share vertices; under smooth shading their opposite normals average toward zero and shade dark and blotchy. Give the surface thickness (Solidify) instead.
- **Do not Solidify a mesh that is already closed.** A lathe profile that touches the axis at both ends is a solid. Only open shells (dome, open bowl) need it.
- **When flipping a triangle by script in Unity, also negate its vertex normals** — only on vertices used by that triangle alone; changing shared vertices breaks neighbouring triangles.

## 8. Double-sided material fallback

`Render Face: Both` (URP Lit) or a `Cull Off` shader (Built-in) hides inverted or missing faces and survives FBX reimport, because material assets are not regenerated. It is unusable when the faulty faces share a material with large correct areas (e.g. a world-wide palette material): every surface using it becomes double-sided. Fix the source geometry.

## 9. Geometry that is correct by construction

- **Call `bmesh.ops.recalc_face_normals` in the builder, then measure**; §5 d, e and f are cases where it does not help.
- **Irregular faceted props** (crystals, shards, stones): convex hull of a jittered point cloud. A hull's faces always point outward. Delete `geom_interior` and `geom_unused`.
- **Hollow shells:** index outer and inner surfaces on the same parameter grid and emit a jamb quad on every edge whose neighbouring cell is absent. Openings and ragged rims come from one mask, and the result is closed and manifold.
- **Quad grids:** emit a known winding. With `a` at (i, j), `a+1` at (i+1, j) and `b = a + row_length` at (i, j+1): `(a, a+1, b+1, b)` gives +Z normals, `(a, b, b+1, a+1)` gives −Z. Measure `frac_up` on every generated surface after its first build.

Before starting a long bake or export, rerun the check that invalidated the previous one.
