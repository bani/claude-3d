# AltspaceVR / Banter: Unity 6 + URP

Target: Unity 6.x, URP, Linear colour space; the toolchain matches Banter's. Scripting is Banter-style, so build interactive objects as geometry in Blender and attach behaviour in Unity.

Bake strategy, lightmap density, shared-mesh and volume-shader rules are in SKILL.md (*Materials, baking, lighting*).

## Contents

1. Pipeline and run order
2. Lightmaps: rebind at runtime
3. Light linking: rendering layers
4. Recentring the world on the spawn
5. Skybox
6. URP settings that fail silently
7. Headless verification in Unity
8. Reserved layers

---

## 1. Pipeline and run order

Every stage runs on a copy of the master and selects objects by name prefix, so new geometry flows through without script changes.

```bash
B="$BLENDER"   # Blender executable on this machine
cp world.blend export/world_export.blend
"$B" -b export/world_export.blend -P export/scripts/build_tree_lods.py  -- --save
"$B" -b export/world_export.blend -P export/scripts/prep_geometry.py    -- --save  # UV0 + object splits
"$B" -b export/world_export.blend -P export/scripts/prep_lightmap_uv.py -- --save  # UV1 atlas
"$B" -b export/world_export.blend -P export/scripts/bake_lighting.py    -- --samples 192
"$B" -b export/world_export.blend -P export/scripts/export_fbx.py
python3 export/scripts/probe_materials.py     # Cycles EMIT/DIFFUSE bake per material
python3 export/scripts/make_urp_materials.py  # reads the probe output, not the node graph
python3 export/scripts/verify_fbx.py          # must exit 0
```

In Unity: a `Setup URP` menu item, then `Build All`, which assembles the scene from the FBX chunks and a manifest.

- **Export in chunks by collection** (terrain, paths, ruins, trees, …), not one file; a single file forces a full reimport on every change. Seven chunks totalling 14.8 M polys import without trouble.
- **Wrap the sequence in `run.sh`** and log wall-clock per stage together with the machine name. The bake dominates the run.

## 2. Lightmaps: rebind at runtime

`LightmapSettings.lightmaps` does not persist through a scene save. Unity serialises it through a LightingData asset that only its own lightmapper produces. An array set from an editor script reads back after save as `lightmaps.Length == 0` with every `lightmapIndex == -1`: an external bake is not applied.

- **Symptom:** the scene renders far darker than the Blender reference (median ≈ 2 against ≈ 27), which looks like a missing tonemapper.
- **Fix:** a component that rebinds the lightmap array and the per-renderer lightmap indices in `Awake`.
- **Check on the saved scene:** lightmap count after the binder runs, every lightmapped renderer's `lightmapIndex != -1`, and `mesh.uv2` present.

## 3. Light linking: rendering layers

Blender light linking (a light that excludes some objects) maps to URP `renderingLayerMask`.

- **`Light.cullingMask` had no effect in this URP setup**: with the mask excluding the world's layer, a frame difference showed fill lights still adding ~20 % luminance to the world. This behaviour is reported to vary by Unity version; after an upgrade, re-test with a frame difference.
- **Setup:** static world renderers alone on rendering-layer bit 1; avatar-fill and foliage lights set to `~WORLD_RENDER_MASK`; the sun at `-1`. Cameras do not cull by rendering layer and physics ignores it, so this changes neither visibility nor collision.
- **Types:** `Light.renderingLayerMask` is `int`, `Renderer.renderingLayerMask` is `uint`; mixing them up gives CS0266. Unity 6's URP asset has no `m_UseRenderingLayers`: rendering layers are always on and are named in Tags & Layers.
- **Do not move the world to its own GameObject layer instead.** The platform supplies the camera, and a camera whose culling mask excludes that layer renders no world.

Final light set for a 5.5 km² world: one directional sun, ~24 avatar fills, and realtime lights for the foliage that is not lightmapped.

## 4. Recentring the world on the spawn

The platform spawns the avatar's head at world origin; translate the world to match.

- **Anchor on the measured ground under the spawn marker, not the marker** (markers float above the floor). Raycast down at export time and record the hit in the manifest.
- **Head point = ground + eye height (1.5 m);** translate the world by its negation. Verify: a ray cast down from above the origin hits at exactly `−eye_height`.
- **Compensate anything that reads world position.** A shader sampling noise at world position slides across the geometry after the move. Publish the translation as a shader global (e.g. `_AlienWorldOffset`) and subtract it in the shader. Verify with a control: compensated frames match the pre-move baseline exactly, and frames with the global zeroed differ.
- **Offset cameras placed from Blender coordinates** by the same translation, read from the scene, not from a constant.
- **On every re-export, confirm the spawn ground has not moved.** The whole world is positioned relative to it.

## 5. Skybox

Bake the far horizon to a mono equirectangular EXR and use `Skybox/Panoramic`.

- **Ship EXR, not an AgX PNG** (SKILL.md: the PNG is graded twice).
- **Set the importer's `maxTextureSize` to 8192**; otherwise a 6144-wide equirect is resampled to 2048.
- **Keep the lower hemisphere.** At DXT1 with mips a full 6144 equirect is 12.6 MB; cropping saves 6.3 MB and adds a seam.
- **Assign `RenderSettings.skybox` and read it back.** If the import step is skipped (e.g. a hard-coded filename the copy step no longer produces), `LoadAssetAtPath` returns null and the scene keeps the previous build's skybox with no visible error.
- **Keywords:** `Skybox/Panoramic` has one `shader_feature` whose off state is latitude-longitude, so `_Mapping = 1` with no keyword enabled is correct. `_MAPPING_LATITUDE_LONGITUDE_LAYOUT` does not exist. Dump a shader's real keywords before asserting on them.

## 6. URP settings that fail silently

None of these logs an error. Read every setting back from the asset after writing it.

- **`postProcessData == null`** on a script-created `UniversalRendererData` disables the whole post stack. Assign the package default (`Runtime/Data/PostProcessData.asset`) through `SerializedObject`.
- **`colorGradingMode` defaults to `LowDynamicRange`,** which ignores `postExposure` (the LUT operates on already-tonemapped 0–1 values). Use HDR grading.
- **Editor writes to a ScriptableObject** need `EditorUtility.SetDirty` or they are not saved.
- **`VolumeProfile` components** must be added as sub-assets with `AssetDatabase.AddObjectToAsset`; `profile.Add<T>()` alone exists only in memory, and the profile reloads empty.

Starting look: Neutral tonemap, HDR colour grading, LUT size 64, post-exposure EV +1. EV 0 matches the Blender reference on a monitor; headsets display dimmer.

## 7. Headless verification in Unity

Run editor checks against the saved scene: `Unity -batchmode -quit -executeMethod Foo.Run`.

Check: skybox assigned, linear, 2:1 and not downsampled; ambient mode and colours; fog; exactly one directional light; realtime lights by category, not only their total; the world's rendering-layer bit; a collider under the spawn column; the lightmap binder rebinding after a reload; the tonemapper in the profile that actually loaded.

Walkability: `Physics.Raycast` down each corridor in the built scene and count stations that hit a collider. This is the check that a floor fix reached the game.

Headless rendering:
- **URP post-processing does not run under `-batchmode`** (a pure-red `colorFilter` leaves the frame unchanged). For headless look checks, apply URP's `NeutralTonemap` math offline; judge the real result in the editor.
- **Under `-nographics`, `Camera.Render()` writes nothing and `ReadPixels` returns uninitialised memory.** Assert the buffer holds real data; otherwise report "not run".
- **The first render into a new RenderTexture, and the first after a scene load, are unreliable.** Render twice and keep the second; run A/B comparisons in both orders.
- **When two instruments disagree, find the setup difference before trusting either** (e.g. a camera without `renderPostProcessing` measures the raw linear buffer).

## 8. Reserved layers

Read `ProjectSettings/TagManager.asset` before using a layer. In Banter projects:

| Layers | Use |
|---|---|
| 17–23 | NetworkPlayer, RPMAvatarHead, RPMAvatarBody, Grabbable, HandColliders, Menu, PhysicsPlayer |
| 24–31 | `BanterInternal1..8_DONTUSE` |

Assign colliders by prefix in one place (e.g. `PATH_`, `TERRAIN_`, `RUIN_`, `SCAT_`) and derive the Blender walkability audit from the same list.
