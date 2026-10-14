# Blender authoring

Techniques for the build loop in SKILL.md. Read the section for the task at hand; §8 is a lookup table.

## Contents

1. Raycasting
2. Terrain, paths, grade
3. Props, scatter, instancing
4. Water
5. Shells, voids, openings
6. Cameras and sightlines
7. `bpy` pitfalls
8. Technique lookup

---

## 1. Raycasting

Most measurements are raycasts, and most raycast bugs are a ray answering a different question from the one intended.

- **March past skipped objects.** A plain downward ray stops on haze volumes, cave shells, trees, crystals and placed props. Keep a skip list and step a small epsilon past each skipped hit.
- **Name each helper by the question it answers.** One that skips ruins returns terrain (`ground_rock`); one that keeps them returns what a player stands on (`ground_walk`). When the answer must match the engine, take the solid set from the collider prefix rule.
- **Assert the name of the hit object**, not only that something was hit.
- **Raise skip-listed props off the ground by more than one march step** (~4 cm). A prop resting exactly on the surface makes the marcher step through the terrain and return its underside or a surface far below.
- **Stacked surfaces** (helix, bridge over a path): a downward ray returns the topmost. Use a variant that returns the surface nearest the walker's current height.
- **Diagnosing a visual fault:** cast a ray through the bad pixels and print the full hit chain, not only the first hit. This identifies which object is actually in view — a "broken material" is often a different object in front, or a surface seen through thin water.

## 2. Terrain, paths, grade

- **Locate a cliff face** by casting outward from inside the rock at each (azimuth, height). If the hit radius changes monotonically with height there is no overhang; its rate of change is the wall's recession, which limits how many switchback flights fit. A constant lateral offset between switchback runs is used up after `offset / recession` metres of descent; beyond about two flights, move away from the face.
- **Enforce a maximum grade with raise-only relaxation:** `z_i ≥ z_j − h·tan(limit)`, applied along the downhill direction only. For a built ramp, in this order: (1) z by arclength between the two ends; (2) raise-only clamp to `ground + clearance`; (3) raise-only grade relaxation to remove the spikes the clamp created.
- **Switchback landings are separate slab islands.** Sweeping one profile through a reversal folds it through itself (self-intersection, negative volume).
- **A landform resting on terrain** is `ground + thickness`, with thickness via smooth-max, so it cannot pass below the ground.
- **A rigid object spanning terrain** (log, beam, bridge) rests on the highest ground in its contact range: use the max over the range. "Last sample above a threshold" slides down the rim face and buries one end.
- **Section sign-off:** besides reachability from the spawn, the section's intended sightline must work from a position a player can stand on.
- **Carving a channel:** subdivide the corridor until edge length ≲ ⅓ of the feature width, then cut. Keep every displacement octave's period ≥ 3× the mesh edge length.
- **Recovering a centreline from a swept mesh:** first check whether vertex order follows the sweep (near-constant distance between consecutive indices). If not, walk the face graph: up-facing faces joined across shared edges, Dijkstra from highest to lowest. This handles switchbacks and needs no parameterisation. Confirm with an independent measurement before cutting against it.

## 3. Props, scatter, instancing

- **Many small props:** merge into one mesh per material, not one object per prop (e.g. 130 antennae → 2 objects, 2 470 faces). This is the largest available polygon and draw-call saving; apply it to every prop family.
- **Many large props (trees):** a few hidden masters, with instances sharing the mesh datablock (e.g. 136 k unique polys against 4.79 M instanced-equivalent). Shared meshes cannot be lightmapped per object (SKILL.md).
- **Sapling tree cost scales with `levels` and curve resolution, not height:** `levels=3, resU=3, bevelRes=1` gives a 33.5 m tree at 46 k polys; `levels=4` gives a 9.6 m tree at 352 k. Set these at authoring time instead of decimating later.
- **Drive scatter density by the variable that explains it** (distance to water, downslope fraction, distance to the nearest light), e.g. density `1/(1+(d/7)²)` with d = distance to the nearest water source.
- **Define regions by a rejection rule where possible**, e.g. "no tree where the landmark is visible", which makes the forest exactly the area that hides the landmark. Exclude placed objects from their own test so the result does not depend on placement order.
- **Attaching growth to an irregular surface:** cast inward from outside at the target height, take the hit on the intended object, and seat the prop just inside the hit along the surface normal.
- **Replacing a prop's mesh without moving what sits on it:** measure the axis from the existing mesh (centroid of the lowest 20 % of vertices → centroid of the highest 20 %), lathe the new profile around that axis, and swap the mesh datablock in place.
- **Per-prop operations on a merged mesh:** split into islands, measure each island's axis, height, radius and lean, and apply per island.
- **Procedural texture on a long thin object:** noise defaults to Generated coordinates, normalised to the bounding box, so features stretch along the long axis. Use Object coordinates through a Mapping node, scaled so the grain runs along the long axis.
- **Blender's normalised fBm noise is not uniform on 0–1**; its output is roughly normal about 0.5 with σ ≈ 0.065. Place ColorRamp stops within ~2σ of 0.5; stops at 0.3/0.7 discard most of the variation.

## 4. Water

- **Clear water over an unlit bed renders black.** For luminous water, put emissive geometry below the surface for colour and lights just above the surface for illumination. Lights placed below the surface lose most of their output to total internal reflection.
- **Judge water over emissive geometry at ≥ 200 spp.** At lower sample counts, noise on that light path looks like a texture defect. To confirm a defect, re-render the same frame at 400 spp and check whether it moves.
- **Lake with a natural edge:** flood fill from a seed at water level, keep quads whose four corners are below water level, then move boundary vertices outward to where the ground crosses the water line. To find where a water surface ends, march outward from the centreline until ground ≥ water level.
- **Keeping water inside its channel:** sample both banks outside the carve corridor on the carved terrain, set the surface below the lower bank, and carve again (cut-only, so it converges).
- **Water that reads as a mirror** needs a swell octave with metre-scale wavelength, not more fine ripple, plus a shoreline band driven by distance-to-boundary stored as a vertex attribute.

## 5. Shells, voids, openings

- **Hollowing a landmark while keeping it manifold:** index outer and inner surfaces on the same (azimuth, height) grid, mark cells present or absent (rim, windows, door), emit outer and inner faces for present cells and a jamb quad on every edge whose neighbour is absent.
- **Guaranteed wall thickness:** clamp the inner radius to `r_out − WALL_MIN` instead of tuning noise amplitudes; a deep flute then cuts into the void instead of opening a hole.
- **Cutting an opening through terrain:** delete faces inside the bore in local cross-section coordinates (`|u| < w`, `zlo < Δz < zhi`), testing the face centre and every vertex. Check for modifiers first (normals.md §6).
- **Burying a structure that has no rock above it:** raise the heightfield into a noisy ridge over the corridor, then cut the bore.
- **Flat interior floor on natural terrain:** set heightfield vertices to the target z inside a radius, then smoothstep-blend over a rim band so no cliff forms at the edge.
- **Closing a seam between two meshes without a lip:** sample both real surfaces at the edges, interpolate across the gap with smoothstep, and extend an overlap tail ~0.6 m under each neighbour at −0.03 m. Result: coincident at the walking line, no z-fighting, no trip edge.

## 6. Cameras and sightlines

- **Site cameras by search, not by hand**; hand-placed cameras end up inside rock and props. Constraints: lens in open air in all six axis directions; clear ~5 m cone ahead; first hit along the view ray is the subject; no axis ray from the lens returns a back-facing hit; minimum standoff from the subject as a hard constraint (visibility increases monotonically on approach, so an unconstrained search puts the lens inside the subject).
- **Check framing with a coverage histogram** of the objects filling the frame. A camera that satisfies every siting constraint can still be aimed at the wrong object.
- **Visible fraction of an object:** sample its vertices by farthest-point sampling. `verts[::step]` follows build order and clusters on one part.
- **Overlooks:** take the union of visibility over every standing point along the edge. From one central point, the platform itself hides everything steeply below.
- **Blocked sightline:** test twice, once with foliage as an occluder and once rock-only. Blocked by rock: the line never existed (design error). Blocked only by foliage: vegetation has grown into it.
- **Fix camera defaults in the builder** as well as on existing cameras. Check `clip_end` against the scene extent (e.g. 1000 m inside a 3 269 m haze volume truncates every long view). When one camera has a bad setting, histogram that setting across all cameras.

## 7. `bpy` pitfalls

- **Merged builds store geometry in world space** with the object at the origin, so `matrix_world.translation` is (0, 0, 0). Read position from the vertices.
- **Never set `.rotation_euler` on position-baked geometry.** It rotates about the world origin and moves the geometry far away. Build axis-aligned with swapped dimensions, or recentre the geometry on its origin first.
- **Setting a Geometry Nodes input with `mod[socket_id] = v` does not invalidate the viewport evaluation.** Call `obj.update_tag()` then `view_layer.update()`. Renders use a fresh depsgraph and do reflect the change, so viewport and render disagree until you do.
- **`bpy.data.libraries.load` leaves a Library datablock** that makes `save_as_mainfile` to that path fail ("Cannot overwrite used library"); remove it before saving. Linked (not appended) objects report an identity `matrix_world`; use `matrix_basis`.
- **`Image.pixels` on an sRGB byte image holds sRGB-encoded values.** Encode linear → sRGB before writing, or every albedo darkens. Non-Color images take raw values.
- **Do not render panoramas through the Blender MCP tool**; they exceed the call timeout. Use the Blender CLI.
- **`pgrep -f <script>` matches the waiting shell's own command line**, so `until ! pgrep -f "bake_lighting"; do sleep 30; done` never exits. Match the binary (`pgrep -f "Blender.*bake_lighting"`) or wait for the output file.

## 8. Technique lookup

| Problem | Technique |
|---|---|
| Path needs clearance under overhangs | Try lateral offsets 0.3 → 6.8 m, take the smallest with enough headroom, apply a sliding-window max (widen, never narrow), then smooth |
| Overhanging terrain blocks a route | Raise terrain vertices into an arch iteratively, re-measuring clearance after each pass |
| Pier placement | Sample clearance along the 3-D centreline; place piers where clearance > 3.6 m, with a minimum spacing |
| Branching a new path off an existing one | Branch where the existing path's tangent reverses (radius maximum); branches elsewhere run parallel and never gain headroom |
| Route with many constraints | Sweep departure × landing × bow on the polyline; score grade, headroom, ground contact and the terrain after the landing; build once |
| Bridge grade too steep | Raise the springing (bridgehead), not the landing; a 1.75 m bridgehead took one bridge from 12.6° to 8.9° and gives the parapet a base |
| Landing surveyed only along the centreline | Sample across the full deck width; terraced ground looks flat from the centre band |
| Siting a structure that aims at something | Sweep candidate seats, raycast the aim direction from each, keep the clear seat nearest the intended spot |
| Siting search returns nothing | Check the constraints fit this terrain; e.g. on a cliff-cut stair, turn steep hits into wall seats pushed out along the face normal |
| Making a ruin read as ruined | Break elements to stumps; place debris downhill of the specific element that broke, not uniformly |
| Lights on a ruin | Place them at the breaks — one rule, two heights |
| Lighting a long traversal | One bright anchor (~4 m emitter at 1500 W), visible while walking toward it, instead of many markers |
| Lighting a tall enclosed space | One light per site, in open air over the walking surface; never inside the emissive prop, which shadows it |
| Setting a new light's brightness | Sample an existing render at exposure 0 and match the world's ground-luminance percentiles |
| Did a lighting change work? | Difference the two frames; a crop median is dominated by background |
| Grading a render | Median + p99 + fraction of frame above a threshold; median alone flags a deliberate dark-to-bright reveal as a fault |
| Paving that reads as laid stone | Voronoi of a jittered hex lattice, each cell inset by half a joint width; random seeds produce crazy paving |
| Emissive solid that reads at close range | Transmission + volume absorption for depth, Voronoi `DISTANCE_TO_EDGE` for veins, inverted Layer Weight for rim; measure pixels, since transmission stacks emission. Remove the volume before baking (SKILL.md) |
| Editing a material to fix one object | Count the material's users before and after; copy it rather than editing a shared material |
| A pass reports it processed "all" of a family | Count the family and compare with the number processed |
| A section reads as empty | Usually missing foreground dressing, not a landmark; rank sections by dressing objects and polys per 100 m² |
| Hard edge in a volume with no geometric cause | Change the volume step settings; if the edge moves, it is the march limit (reach = max_steps × step) |
| A bad setting found on one camera or object | Histogram that setting across all of them |
| A fix that did not fix it | Revert it in the same script and record the cost |
| A warning fires | Inspect its metric before acting on it |
| A measurement that changes with sampling rate | Treat it as an indicator, not a value; say so where it is computed |
| A sweep keeps reporting clean | Confirm it covers every object, not a subset |
| Many items fail one check the same way | Look for a shared design cause before fixing items individually |
