# claude-3d

A [Claude Code](https://claude.com/claude-code) skill for building walkable social-VR worlds in Blender and exporting them to Unity, plus the slides from the talk about it.

- **Slides:** [building-vr-worlds-with-claude-code.pdf](building-vr-worlds-with-claude-code.pdf)
- **Skill:** [`skills/vr-world-building`](skills/vr-world-building)

## What the skill does

It gives Claude working rules for Blender-to-Unity world pipelines targeting **VRChat** (Unity, Built-in RP) and **AltspaceVR / Banter** (Unity 6, URP):

- Surveying terrain and checking plan numbers before building
- Re-runnable build scripts (delete by prefix, then rebuild)
- Face-normal audits with the correct test per mesh topology
- Walkability checks: slope, step height, headroom, deck width
- Baking procedural Cycles materials and lighting for URP / Built-in
- FBX export settings, plus verification of the written file
- Unity-side setup and checks on the saved scene

## Contents

| Path | Purpose |
|---|---|
| `skills/vr-world-building/SKILL.md` | Entry point: verification rules, normals, walkability, baking, export, pre-flight checklist |
| `references/normals.md` | Normals failure modes and fixes |
| `references/blender-authoring.md` | Raycasting, terrain, scatter, water, cameras, `bpy` pitfalls |
| `references/unity-vrchat.md` | VRChat / Built-in RP specifics |
| `references/unity-altspace.md` | AltspaceVR / Banter / URP specifics |
| `scripts/normals_audit.py` | Headless normals sweep; exits 1 on any inversion |
| `scripts/verify_fbx.py` | Parses written binary FBX files; exits 1 on transform faults |

## Install

Copy the skill into your Claude Code skills directory:

```bash
cp -R skills/vr-world-building ~/.claude/skills/
```

Claude loads it when a task involves a Blender scene headed for a game engine, a Blender-to-Unity FBX export, or VRChat / Altspace / Banter world work.

## Using the scripts directly

```bash
# Normals audit (Blender in background mode)
blender -b world.blend -P skills/vr-world-building/scripts/normals_audit.py -- --interior TERRAIN_tunnel_

# FBX transform check (Python 3, no dependencies)
python3 skills/vr-world-building/scripts/verify_fbx.py export/fbx/
```

## Requirements

- Blender (the scripts use `bpy` and `bmesh`)
- Python 3
- Unity: 2022.3 for VRChat, Unity 6 for Banter / URP

## License

[MIT](LICENSE)
