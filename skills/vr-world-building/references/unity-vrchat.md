# VRChat: Unity + Built-in RP

Target: Built-in render pipeline (not URP), VRChat Worlds SDK, scripting in Udon / UdonSharp.

## Contents

1. Export pipeline
2. FBX material and texture traps
3. Merge, instance and modifier hazards
4. Legacy transform convention
5. Unity import settings
6. Lighting and skybox
7. Reflection probes on merged objects
8. Quest: fog, budget, shaders
9. VRChat components, Udon, particles
10. Editor-scripting meshes

---

## 1. Export pipeline

Encode the export as one driver script with `start=`/`stop=` stage slicing: some stages exceed tool/RPC timeouts and must be resumable. Make each stage idempotent or guarded.

Ordering constraints:
- UV pass before any bake or texture mapping.
- Convert materials to FBX-compatible form and realize all Geometry Nodes objects before merging into sections.
- Steps that key off mesh names (e.g. doubling impostor faces) run before the merge renames meshes.
- Palette swap and normals fix run inside the section build, after the merge.
- Create marker empties before any step that reads them (e.g. bench extraction reads `ST_*`).
- Finish with: collapsed-chunk audit → prune → final audit → FBX export.

**Chunking:** one chunk per section × {hard, foliage}, so architecture is lightmapped and foliage is probe-lit. Keep unmerged: interactive objects, Udon targets, particle anchors, pickups, seats, collider meshes.

**Colliders:** low-poly invisible `COL_*` meshes (ground, path slabs, hedge and wall boxes, fountain cylinders, floors, steps). Visual meshes get no colliders.

**Markers:** named empties emitted from the same build data (`ST_bench0..13`, `SPAWN`, `FX_fire`), so seat positions and facings come from the source rather than hand placement in Unity.

**Geometry-based classifiers** (vertex-count bands, bbox-diagonal gates) must be re-tuned after any subdivision or decimation of the props they classify.

## 2. FBX material and texture traps

- **The FBX exporter drops any texture routed through MixRGB or SeparateColor.** Wire `Image Texture → BSDF socket` directly. Split packed channels (roughness/metal) into separate greyscale images; wire AO in Unity.
- **Packed images with an empty `filepath` are skipped without warning**, and the object renders white. Check `img.filepath` on every image before export; save packed images to files and re-point them.
- **Generated- and Object-coordinate procedurals do not survive export** and also break on realize/join. Convert to UV + image (or vertex colour) before any realize or merge.
- **Procedurally built meshes have no UV layer.** A bake or texture export before the UV pass produces garbage with no error.
- **`convert()` / Realize Instances leaves the UV layer without `active_render`,** so every texture samples UV (0, 0) and the object renders as one texel. Set `uv_layers[0].active_render = True` after realizing, and audit it.
- **Box-projection UV passes must skip faces whose material uses authored image-texture UVs.** Otherwise a prop that shares a mesh with a tileable material loses its UVs. Reproject only the tileable faces.
- **`use_mesh_modifiers=True`** bakes modifiers (e.g. Smooth by Angle) into the export without applying them destructively to shared meshes.

## 3. Merge, instance and modifier hazards

- **Joining drops the modifiers of every non-active object.** Apply modifiers before merging.
- **Shared mesh + per-object material-slot overrides breaks FBX export** ("Cannot register a valid material index"). Make the mesh single-user before splitting slots, remapping indices or editing in place.
- **Editing a shared mesh in place changes every user.** A per-object `material_index` remap on a multi-user mesh runs once per user and shifts the indices repeatedly.
- **Collapsed chunk:** after merge/split/slot surgery, a multi-slot mesh with every face on slot 0 renders entirely in the first material. Root cause unknown. Audit for this signature after every merge, join, split, extract or slot cleanup; repair by KD-tree nearest-face matching against the content master. The finder also returns legitimate single-material meshes and parked archetypes, so scope repairs to the real section chunks.
- **Park archetypes far off-scene** (x ≈ 500) and exclude them from scene-wide audits and the prune step.
- **Archetypes built from joined primitives have unexpected origins.** Check world bounding boxes after placing them.

## 4. Legacy transform convention

Correct FBX settings are in SKILL.md (*Export*). An existing VRChat project exported with Blender defaults (UnitScaleFactor 1, `Lcl Scaling [100,100,100]`, `Lcl Rotation [−90,0,0]`) has children tuned against those parent transforms: VRCStations, particle systems, colliders. Switching to the correct convention sets the parents to scale 1 / rotation 0 and displaces every such child.

- **Keep both conventions:** one driver writes two export folders — the correct convention for new targets, the legacy one for the existing VRChat project — with a `README.txt` in the legacy folder explaining why its files look wrong. Writing both in the same stage keeps them in sync. Verify the legacy folder with `verify_fbx.py --legacy`, which fails if the old convention is *absent*.
- **Or migrate:** per object, unparent to scene root → revert the parent's Transform override → re-parent (Unity preserves world transform on both drags). Never use *Revert All* on these prefab instances: added GameObjects and components are overrides, so it deletes the VRCStations and particle systems.

On a correct export, a Blender `rot_z` appears on the FBX Y axis, and any remaining `Lcl Scaling` values are authored per-instance scales, none ≈ 100.

## 5. Unity import settings

- **Reimport by overwriting the FBX at the same path;** material remaps and extracted textures are kept. Deleting and re-adding the asset loses them.
- **Editor-side mesh edits do not survive reimport** (the FBX mesh is a read-only sub-asset). If a tool replaced a MeshFilter's mesh with an in-memory copy, reimporting the FBX does not update that object until its Mesh field is re-pointed. When a replaced file changes nothing, check the MeshFilter reference first.
- **Palette, atlas and gradient-strip textures:** mipmaps off, Point filter, Clamp wrap, no compression. Mip averaging blends neighbouring atlas cells and flattens gradients.
- **Tileable bakes** (grass, hedge): Wrap Repeat; material tiling (1, 1) if the tiling was baked into world-metre UVs.
- **Index Format: Auto** — merged chunks exceed 65 535 vertices.
- **Generate Lightmap UVs on `*_hard` chunks only.** Foliage, trees and impostors: Contribute GI on, Receive GI = Light Probes, so they cast baked shadows but stay out of the atlas.
- **Wire metallic and smoothness explicitly** (Standard smoothness = 1 − roughness); otherwise metal reads as plastic.
- **Material settings FBX cannot carry** are set by name in Unity; list them in the hand-off doc (impostors → cutout + two-sided; glass, embers → emissive; jets → transparent; water → water shader).
- **`COL_*` meshes** → MeshCollider, renderer disabled.

## 6. Lighting and skybox

- **Skybox:** equirect HDR, import HDR on, sRGB off → material with `Skybox/Panoramic`, Mapping Latitude-Longitude, exposure ≈ 1.0–1.3, assigned in Lighting → Environment.
- **Sun:** one directional light, Baked (Mixed for realtime avatar shadows), rotated in Y to line up with the skybox sun. Environment lighting source and reflections: Skybox, so light probes pick up the horizon colour.
- **Low sun:** Indirect Intensity 1.5–2, or shadowed ground goes muddy. Emissive materials (lamp glass, embers) ≈ 2–4.
- **Bake flat albedo** (Diffuse Color pass), never the lit render.
- **Colours tuned under AgX in Blender read darker and more saturated in Unity.** Add an ACES tonemapper (the closest stock match to AgX) on the Reference Camera, with slight bloom and a warm white balance.
- **Fog:** Exponential Squared, low density; hides the draw distance at no cost (on Quest see §8).

## 7. Reflection probes on merged objects

Built-in RP picks reflection probes per renderer by bounding-box overlap. A merged mesh spanning distant locations (e.g. all fountain water in one mesh) has a world-sized AABB and samples one wrong probe everywhere.

Fixes, cheapest first:
1. Renderer *Reflection Probes: Off* → falls back to the skybox, often right for water and metal.
2. *Anchor Override* → samples probes as if located at a chosen transform.
3. Split the mesh per location in the export pipeline (so it survives reimport) and give each part a probe.

Probe setup: tight boxes, Box Projection on for flat surfaces, probe origin near the reflecting surface's height.

## 8. Quest: fog, budget, shaders

- **Quest evaluates fog per vertex.** A large flat surface with few vertices (e.g. one quad) is fully fog-coloured except when viewed straight down. Subdivide large flat surfaces so there are vertices near the player.
- **Measured budget:** a 175 m garden at ~1.5–3 M tris, 20 materials, 79 mesh objects runs well on Quest 2 because its triangles are cheap (impostors, shared meshes, merged chunks, baked lighting). Profile before building a separate decimated Quest version.

Cost drivers:
- **Subdivision:** Subsurf level 2 = 16× faces (a 3.5 k-tri cushion becomes 56 k). Track triangle counts after every subdivision.
- **Impostors for trees:** 3 crossed quads = 6 tris (12 double-sided). Bake once per archetype.
- **Transparent overdraw** (particle streams, layered water, large alpha planes) costs fill rate; limit count and screen size.
- **Largest wins on open sightlines:** chunk merging (batching), baked lighting, realtime shadows off after baking. Occlusion culling helps only in enclosed areas.
- **Shaders:** VRChat Mobile shaders (`VRChat/Mobile/...`) on Quest.

## 9. VRChat components, Udon, particles

- **Seating:** VRC Station on seats. Marker empties import as transforms; an editor script can place stations from them by index, with facings from the build data.
- **Pickups:** VRC_Pickup + collider, pivot at the island centre in Blender. Probe-lit, out of the lightmap.
- **Scene descriptor:** spawn point and orientation, respawn height below the world, signage out of the spawn sightline.
- **Plain MonoBehaviours do not run in an uploaded world;** runtime behaviour must be Udon/UdonSharp. Use `MaterialPropertyBlock` so objects sharing a material can animate independently.
- **The Built-in Standard shader cannot scroll texture offset over time;** scrolling UVs (water) need a custom shader or an Udon script.
- **Audio:** footsteps on path colliders; ambient sources per area.

Particle streams (smoke, steam, incense):
- **Spacing** ≈ `startSpeed / rateOverTime`. Particle size ≫ spacing gives a continuous ribbon; otherwise separate puffs. The Trails module gives a continuous ribbon with minimal overdraw.
- **Noise Quality Low is 1D noise:** the whole column moves together. Use High (3D). Raise Frequency (~1) and add Scroll Speed; low frequency reads as constant wind.
- **Noise Separate Axes:** small X/Z, Y = 0; ramp strength 0 → full over lifetime so the base stays a thin thread.
- **Limit Velocity over Lifetime damps total speed, vertical included;** a limit below Start Speed stops the rise. Use Separate Axes: tight X/Z, high Y.
- **Gravity Modifier −0.02 to −0.05** reads as buoyancy.
- **Height ≈ vertical speed × Start Lifetime.** When raising lifetime, keep Max Particles ≥ rate × lifetime.
- **Prewarm on;** fade alpha in at birth and out before death so particles do not pop.

## 10. Editor-scripting meshes

- **`RaycastHit.triangleIndex` indexes the collider mesh's full triangle list.** `mesh.triangles` concatenates all submeshes; `mesh.GetTriangles(i)` returns submesh *i* alone. Map a hit to its submesh with `mesh.GetSubMesh(i).indexStart` and `indexCount` before editing a submesh's triangles.
- **`Physics.Raycast` ignores back faces by default,** so an inverted face cannot be picked. Set `Physics.queriesHitBackfaces = true` around the query.
- **`MeshCollider` cooking (cleaning, welding) can renumber triangles** relative to the render mesh. Set `cookingOptions = MeshColliderCookingOptions.None` when relying on the index.
- **Shaded Wireframe hides back-facing wires,** so an inverted face draws nothing. Use plain Wireframe to see inverted or missing geometry.
