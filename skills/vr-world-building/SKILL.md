---
name: vr-world-building
description: Build walkable social-VR worlds in Blender with Python and export them to Unity for VRChat (Built-in RP) or AltspaceVR/Banter (Unity 6 + URP). Covers terrain surveying, re-runnable prefix-delete build scripts, face-normal audits chosen by mesh topology, walkability checks (slope, step height, headroom, deck width), baking procedural Cycles materials and lighting into textures URP or Built-in can render, FBX transform verification, lightmaps, light budgets, and checks on the saved Unity scene. Use whenever a Blender scene is headed for a game engine, for any Blender-to-Unity FBX export, for VRChat or Altspace/Banter world work, for terrain/path/ruin/scatter generation scripts, when a model is invisible, black or inside-out in Unity, for lightmap or light-budget questions, or when starting a new world project — even if only one piece of this is mentioned.
---

# VR world building: Blender → Unity

| Target | Unity | Pipeline | Read |
|---|---|---|---|
| AltspaceVR / Banter | 6.x | URP, Linear | `references/unity-altspace.md` |
| VRChat | 2022.3 (SDK-pinned) | Built-in | `references/unity-vrchat.md` |

- `references/normals.md` — before generating or editing meshes; when anything is invisible, black or see-through in Unity.
- `references/blender-authoring.md` — raycasting, terrain, paths, scatter, water, hollow shells, cameras, `bpy` pitfalls.
- `scripts/normals_audit.py` — headless normals sweep, exit 1 on any inversion.
- `scripts/verify_fbx.py` — parses written binary FBX files, exit 1 on transform faults.

## Verification rules

A check that measures the wrong thing returns a plausible number, not an error. Apply these to every check in a project:

1. **Validate each check against a known-bad control before trusting it.** Build an input it must fail — a flipped mesh, an FBX exported with Blender defaults, a blocked corridor — and confirm it fails. A check that cannot run (e.g. `ReadPixels` under `-nographics` returns uninitialised memory) reports "not run", never PASS.
2. **Check what the player receives, not the step that produced it.** Parse the written FBX, not the exporter arguments. Probe the saved Unity scene, not the build log. Read each setting back from the asset after writing it. Confirm walkability with Unity physics on the built colliders.
3. **Fix in the content master and its builder script.** A fix made only in the export copy or by hand in Unity is overwritten by the next export. A "fixed" note is unverified until the geometry in the master is re-measured.
4. **Measure renders numerically.** Report median, p75, p99, max, clipped-pixel count, and saturation of the brightest 1 % (the view transform desaturates bright emission to white without clipping it). Compare renders by per-pixel difference, not crop medians. If an input change leaves the render byte-identical, the input is disconnected.
5. **Check plan numbers against the scene before building.** Raycast stated coordinates. Compute grade = Δz / horizontal distance between endpoints and compare with the 35° limit before designing any path, stair or bridge.

## Normals

**Audit face normals on every generated or edited mesh after each build script, without waiting to be asked.** Blender's viewport draws back faces; Unity culls them. An inverted face looks correct in Blender and is invisible in Unity.

Choose the test by mesh topology:

| Topology | Test | Correct | Inverted |
|---|---|---|---|
| Closed solid (every edge has 2 faces) | Signed volume per connected island, about the island's own centroid, in Python floats | > 0 | < 0 |
| Open shell (heightfield, ribbon, deck, ring) | Area-weighted fraction of faces with world `normal.z > 0` (`frac_up`) | ≈ 1.0 | ≈ 0.0 |
| Interior void (tunnel, cave, dome interior) | Fraction of faces with `dot(normal, centroid − face_centre) > 0` | > 0.5 | < 0.5 |
| Horizontal tube (log, branch, pipe) | Rays cast inward from outside the bounding sphere; fraction of first hits that are front-facing | > 0.5 | < 0.5 |

- Signed volume on an open mesh depends on the world origin and is meaningless.
- An interior void's correct normals face inward, so its signed volume is negative. List interior objects explicitly so the closed-solid test never sees them.
- `frac_up` reads 0.48–0.52 on a horizontal tube whichever way it faces.
- **Inversion or hole:** both are invisible in Unity and need opposite fixes. If the spot is see-through in Blender's viewport, the face is missing: count boundary edges (one face) and non-manifold edges, and add geometry. Flip only faces that exist.
- `bmesh.ops.recalc_face_normals` orients each disconnected island independently and arbitrarily, and cannot orient a single open sheet. Orient against a known reference direction, then measure.
- Flip per unique mesh datablock, never per object: a mesh shared by N objects would be flipped N times.

```bash
blender -b world.blend -P ~/.claude/skills/vr-world-building/scripts/normals_audit.py -- --interior TERRAIN_tunnel_ --closed TOWER_shell --tube TREE_trunk
```

`--interior`, `--closed`, `--tube` and `--skip` take an exact name or a name prefix and can repeat. Unlisted meshes are classified automatically: closed if every edge has two faces, otherwise open. Keep these lists in the build scripts; they record which objects need a non-default test. At startup the script runs the closed and open tests on a correct and a flipped control and aborts if either disagrees; the interior and tube tests have no control. Exit status 1 on any inversion, so it can gate a bake.

Failure modes, flipping procedure and correct-by-construction geometry: `references/normals.md`.

## Project structure

| File | Role |
|---|---|
| `world.blend` (content master) | Live modifiers, procedural materials, authored content. All content edits happen here. |
| `export/world_export.blend` | Copy of the master made by the export pipeline: realized, merged, UV'd, baked, pruned. Regenerated on each export; never edited by hand. |

At project start, fix:
- **The name-prefix scheme** (e.g. `TERRAIN_`, `PATH_`, `RUIN_`, `SCAT_`) and which prefixes get colliders in Unity. That one rule defines the walkable set for both the Blender checks and the engine.
- **The bake strategy** (see *Materials, baking, lighting*), because it sets the UV requirements for every build script.
- **The target platform and render pipeline.**

Build scripts:
- **Delete by prefix, then rebuild**, so every script is re-runnable. Test it: run twice, diff the object-name lists, assert no name contains `.` — a `.001` suffix means a prefix is missing from the delete list.
- **Topology-changing scripts** (subdivide, decimate, boolean) cannot restore from a per-vertex attribute, because vertex indices change. Keep a pristine mesh datablock with `use_fake_user = True` and rebuild from a copy each run.
- **Editing geometry that has no builder:** store pre-edit positions in an `orig_co` mesh attribute and compute every edit from it. Re-running re-fits instead of compounding; zeroing the deltas restores the original.
- **Skip lists hide objects by prefix.** A walkable surface whose name matches a skipped prefix is invisible to every grade, headroom and reachability check. Derive the walkable set from the collider prefix rule, not from a hand-maintained skip tuple.

Verification script:
- One script (`verify_world.py`) holds every check and exits non-zero on failure. Separate copies of checks drift apart.
- Fail on conditions that must never hold; warn on conditions that need a look. A suite that fails correct work gets ignored.
- Write each check as an invariant ("every crystal material has emission > 0"), never as a population count ("41 crystal users"), which breaks when content is added.

Saving:
- Save after every step.
- After a CLI process writes the `.blend`, revert any open GUI session before saving from it. The GUI still holds the pre-CLI state, may report `is_dirty == False`, and saving it overwrites the CLI's work.

## Build loop

Techniques for each step: `references/blender-authoring.md`.

1. **Survey.** Raycast the terrain at the design's endpoints; measure Δz, horizontal distance and grade between them. Re-sample each survey point at half the grid spacing and require its neighbours to agree — a point on a knife-edge reads differently at each spacing.
2. **Design** against the measured values.
3. **Build** with a re-runnable prefix-delete script.
4. **Verify the route end to end** with a flood fill from the spawn. Part-level checks (grade, headroom, burial, volume) pass on parts that are individually correct but do not connect.
5. **Check the walking envelope for obstructions.** Cast horizontal rays along the route at several heights up to 1.8 m and report every hit. Ground checks with skip lists cannot see a rock, crystal or trunk standing in the path.
6. **Render the subject and measure its pixels.** A ray-visibility count includes slivers seen through gaps; only a render shows whether the subject is lit and readable.

## Walkability

Verify with a **colliding walk**, not a downward-raycast sampler. The walker:
- collides with all solid geometry — no skip list (a skip list that hides a cave shell hides the cave);
- counts as floor only faces with `normal.z ≥ cos 35° ≈ 0.819` (otherwise it walks ceilings and undersides);
- requires headroom ≥ 1.80 m;
- follows the surface nearest its current height, not the topmost surface (otherwise it walks on anything built over the route, and drops off a helix on alternate turns).

| Quantity | Limit | Basis |
|---|---|---|
| Walked slope | ≤ 35° | |
| Riser height | ≤ 0.30 m | Unity `CharacterController.stepOffset`. Check flights in both directions. |
| Headroom | ≥ 1.80 m | |
| Clear deck width | ≥ 2.5–3 m | Capsule ≈ 1.0 m plus lateral drift while looking at scenery. 0.70 m is fit-through width, not walking width. |
| Kerb on edges with > 2.5 m drop | 0.5 m | Hides the drop at the feet (the cause of vertigo) without blocking the view; taller than the step offset, so it stops the capsule. Prefer to railings; put on deck edges, not terrain rims. |
| Gaps | bridged | No jumps. |

- Report a widening as change in deck **area**. Width needs a lateral basis that is easy to compute wrong; area does not.
- Grid reachability counts vary by a few cells between runs on identical geometry. Compare with a tolerance.

## Materials, baking, lighting

Cycles node graphs do not export: URP and Built-in cannot evaluate them, and materials driven by `Geometry → Position`, Generated or Object coordinates leave meshes with no UVs. UV unwrapping and baking are required export stages; plan them from the first build script.

| Strategy | Fits | Notes |
|---|---|---|
| Bake lighting only; albedo procedural in a custom engine shader | Large terrain | Cycles DIFFUSE, direct + indirect, `use_pass_color = False`. The atlas holds irradiance only, so its resolution follows lighting gradients, not surface detail. 5.5 km² fit in 2 × 4096² BC6H (33.6 MB). |
| Tileable textures + palette atlas | Built environments with repeated materials | Flat colours share one small palette texture (e.g. 64²); gradients share one atlas strip. |
| Unique baked albedo per surface | Small scenes only | 5.5 km² at 10 cm/texel needs eight 8192² maps per channel. |

- **Measure material values by baking, not by reading the node graph.** A graph read returns unlinked socket defaults and misses anything driven through links (ramps, textures). Bake a Cycles EMIT + DIFFUSE probe per material on the real object at its real position, through UV0 — lightmap (UV1) islands are sub-pixel at probe resolution.
- **Set lightmap texel density by lighting need, not area**, e.g. 8 texels/m within 20 m of a light and 0.5 texels/m elsewhere. Split objects that span both zones.
- **A shared mesh cannot be lightmapped per object.** UV1 is stored in the mesh but the atlas rectangle is allocated per object, so every user gets the last rectangle written. Check `mesh.users` before allocating UV1. Make the mesh single-user where that adds little geometry; otherwise take those objects off the lightmap and light them with probes plus realtime lights (the usual treatment for foliage).
- **Remove volume shader links before baking.** Every bake ray marches through every volume (removing them gave a > 12× speedup), and URP/Lit and Standard cannot render volume absorption anyway. Reproduce the look with base colour and emission.
- **Float formats skip the view transform.** Blender writes EXR without the view transform (AgX, Filmic) and PNG with it. An AgX PNG among linear EXR lightmaps is graded twice under the engine tonemapper. Ship EXR and tonemap once, in the engine.
- **Keep emission strength ≈ 1–2**, tuned at the nearest viewing distance; above that the view transform desaturates it toward white.

**Light budget.** Classify every Blender light. Broad fill bakes into the lightmap and does not ship as a light. Keep realtime only one directional sun and the lights that must reach dynamic or unlightmapped objects (avatars, foliage). Blender point-light power to radiant intensity: I = P / 4π W/sr.

## Export

Set both FBX exporter options. The defaults are wrong for Unity in two independent ways, and both still render correctly, so the fault shows up only later in child offsets, PhysBone radii or an Animator binding:

```python
apply_scale_options = 'FBX_SCALE_ALL'   # default writes UnitScaleFactor 1.0 + Lcl Scaling [100,100,100]
bake_space_transform = True             # default writes Lcl Rotation [-90,0,0] over Z-up vertices
```

Verify every written file:

```bash
python3 ~/.claude/skills/vr-world-building/scripts/verify_fbx.py export/fbx/
```

It fails unless `UnitScaleFactor == 100` and `UpAxis == 1`, fails on either fault signature on a model node (`Lcl Scaling ≈ [100,100,100]`, `Lcl Rotation ≈ [−90,0,0]`), and prints the vertex bounding box — confirm the Y extent is the model's height. It tests the signatures rather than any non-identity transform, because placed instances legitimately carry rotation and scale. Report the verified numbers, not the exporter flags.

**Coordinates.** Blender `(x, y, z)` → Unity `(−x, z, −y)`. The map has determinant −1 (right-handed to left-handed); `(x, z, y)` mirrors every converted position while the FBX geometry stays correct. Check any hand-converted coordinate against an object the FBX placed.

**Machines.** Re-export cost depends on whether Blender and the target Unity editor are on the same machine. Follow the machine rules in the global CLAUDE.md.

## Pre-flight checklist

- [ ] Normals audited with the test that matches each mesh's topology; the audit's controls passed.
- [ ] Backface-culled render of all revolved, swept and lathed geometry.
- [ ] Every fix is in the master and its builder, not only in the export file.
- [ ] Each build script run twice: identical object-name lists, no `.001` names.
- [ ] Route walkable from spawn under a colliding walk: slope ≤ 35°, risers ≤ 0.30 m, headroom ≥ 1.80 m, deck ≥ 2.5 m, kerbs on exposed edges.
- [ ] No procedural, Generated- or Object-coordinate material reaches export; UVs exist before any bake.
- [ ] Shared mesh datablocks audited before per-object UV1 or material-slot changes.
- [ ] Material values measured by bake.
- [ ] `verify_fbx.py` exits 0 on every written file; bounding-box height is on Y.
- [ ] Saved Unity scene probed: lightmaps bound, collider under the spawn, expected realtime light count, skybox assigned.
- [ ] Triangle and light budgets recorded, with decimation candidates named.
