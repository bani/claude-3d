"""Whole-scene face-normals sweep, using the correct test for each topology.

Run headless:
    blender -b world.blend -P normals_audit.py
    blender -b world.blend -P normals_audit.py -- --interior TERRAIN_tunnel_ --closed TOWER_shell

--interior / --closed / --tube / --skip take an exact name or name prefix and
may repeat. Unlisted meshes are closed if every edge has two faces, else open.

Tests (a test applied to the wrong topology returns a plausible number):
  closed solid    -> signed volume per island > 0, about each island's own
                     centroid in Python floats (float32 vert.co loses
                     precision beyond ~100 m from the origin)
  open shell      -> area-weighted fraction of faces with world normal.z > 0.
                     Never signed volume: on an open mesh it depends on the
                     world origin.
  interior void   -> normals face the player, so negative volume is correct.
                     Tests dot(n, centroid - face_centre) > 0; on a strongly
                     curved void the inside of the bend reads inverted.
  horizontal tube -> frac_up reads 0.48-0.52 either way; uses a ray test
                     from outside the bounding sphere instead.

Before the sweep, the closed and open tests run on a correct and a flipped
primitive; the script aborts if either control disagrees. The interior and
tube tests have no control.

Exit status: 0 if nothing is inverted, 1 otherwise, so it can gate a bake.
"""
import bpy, bmesh, sys, math
from mathutils import Vector

# ---------------------------------------------------------------- arguments
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def _collect(flag):
    out = []
    i = 0
    while i < len(argv):
        if argv[i] == flag and i + 1 < len(argv):
            out.append(argv[i + 1])
            i += 2
        else:
            i += 1
    return out


# Name prefixes (or exact names) whose topology the generic tests get wrong.
INTERIOR = _collect("--interior")    # tunnels, caves, dome interiors
FORCE_CLOSED = _collect("--closed")  # hollow shells whose enclosed volume is the wall
TUBE = _collect("--tube")            # logs, branches, pipes: ray test
SKIP = _collect("--skip")            # anything deliberately excluded
QUIET = "--quiet" in argv


def _match(name, prefixes):
    return any(name == p or name.startswith(p) for p in prefixes)


# ------------------------------------------------------------------- tests
def islands_signed_volume(me, mw):
    """Signed volume per connected island, each about its own centroid."""
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    bm.verts.ensure_lookup_table()
    seen, out = set(), []
    for v0 in bm.verts:
        if v0.index in seen:
            continue
        stack, isl = [v0], [v0]
        seen.add(v0.index)
        while stack:
            v = stack.pop()
            for e in v.link_edges:
                o = e.other_vert(v)
                if o.index not in seen:
                    seen.add(o.index)
                    stack.append(o)
                    isl.append(o)
        idx = {v.index for v in isl}
        pts = {}
        for v in isl:
            w = mw @ v.co
            pts[v.index] = (float(w.x), float(w.y), float(w.z))
        n = len(pts)
        cx = sum(p[0] for p in pts.values()) / n
        cy = sum(p[1] for p in pts.values()) / n
        cz = sum(p[2] for p in pts.values()) / n
        tot = 0.0
        for f in bm.faces:
            if f.verts[0].index not in idx:
                continue
            a, b, d = [(pts[v.index][0] - cx, pts[v.index][1] - cy,
                        pts[v.index][2] - cz) for v in f.verts]
            cr = (b[1] * d[2] - b[2] * d[1],
                  b[2] * d[0] - b[0] * d[2],
                  b[0] * d[1] - b[1] * d[0])
            tot += (a[0] * cr[0] + a[1] * cr[1] + a[2] * cr[2]) / 6.0
        out.append(tot)
    bm.free()
    return out


def frac_up(me, mw):
    """Area-weighted fraction of faces whose world normal points up."""
    nm = mw.to_3x3().inverted_safe().transposed()
    up = tot = 0.0
    for p in me.polygons:
        n = (nm @ p.normal).normalized()
        tot += p.area
        if n.z > 0:
            up += p.area
    return 0.0 if tot <= 0 else up / tot


def is_closed(me):
    """Manifold-closed: every edge shared by exactly two faces."""
    use = {}
    for p in me.polygons:
        vs = list(p.vertices)
        for i in range(len(vs)):
            a, b = vs[i], vs[(i + 1) % len(vs)]
            k = (min(a, b), max(a, b))
            use[k] = use.get(k, 0) + 1
    return bool(use) and all(v == 2 for v in use.values())


def interior_ok(ob):
    """Fraction of faces pointing at the object's own axis (i.e. at the player)."""
    me, mw = ob.data, ob.matrix_world
    vs = [mw @ v.co for v in me.vertices]
    axis = sum(vs, Vector()) / len(vs)
    nm = mw.to_3x3().inverted_safe().transposed()
    good = tot = 0
    for p in me.polygons:
        c = mw @ p.center
        n = (nm @ p.normal).normalized()
        d = axis - c
        if d.length < 1e-9:
            continue
        tot += 1
        if n.dot(d.normalized()) > 0:
            good += 1
    return good / max(1, tot)


def frac_front_facing(ob, deps, n_rays=200):
    """Ray test for tubes: cast inward from outside the bounding sphere and
    count first hits that are front-facing. Needs the object in the active
    view layer. Single-sided foliage legitimately reads partly back-facing,
    so compare a variant with its source mesh, not with 1.0."""
    mw = ob.matrix_world
    vs = [mw @ v.co for v in ob.data.vertices]
    if not vs:
        return None
    c = sum(vs, Vector()) / len(vs)
    r = max((v - c).length for v in vs) * 1.6 + 1.0
    front = tot = 0
    ga = math.pi * (3.0 - math.sqrt(5.0))
    for i in range(n_rays):
        z = 1.0 - 2.0 * (i + 0.5) / n_rays
        rad = math.sqrt(max(0.0, 1.0 - z * z))
        th = ga * i
        d = Vector((math.cos(th) * rad, math.sin(th) * rad, z))
        origin = c + d * r
        hit, loc, nrm, _ = ob.ray_cast(
            mw.inverted() @ origin, (mw.inverted().to_3x3() @ (-d)).normalized())
        if not hit:
            continue
        tot += 1
        if (mw.to_3x3().inverted_safe().transposed() @ nrm).dot(-d) < 0:
            front += 1
    return None if tot == 0 else front / tot


# ------------------------------------------- validate before trusting anything
def _validate():
    """The closed and open tests each get a control of their own topology and
    a flipped twin. One shared control does not work: a cube reads frac_up
    0.167 flipped or not (one face in six points up either way), so it would
    pass a broken open-shell test. The interior and tube tests have no
    control yet."""
    val, made = {}, []

    def _mk(name, build):
        me = bpy.data.meshes.new(name)
        bm = bmesh.new()
        build(bm)
        # Far from the origin on purpose: that is where float32 cancels.
        bmesh.ops.translate(bm, vec=Vector((156.0, 0.0, 0.0)), verts=bm.verts)
        bm.to_mesh(me)
        bm.free()
        ob = bpy.data.objects.new(name, me)
        bpy.context.scene.collection.objects.link(ob)
        made.append(name)
        return ob

    def _cube(flip):
        def f(bm):
            bmesh.ops.create_cube(bm, size=2.0)
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
            if flip:
                bmesh.ops.reverse_faces(bm, faces=bm.faces)
        return f

    def _sheet(flip):
        def f(bm):
            bmesh.ops.create_grid(bm, x_segments=4, y_segments=4, size=2.0)
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
            if flip:
                bmesh.ops.reverse_faces(bm, faces=bm.faces)
        return f

    # closed control -> signed volume
    for tag, flip in (("good", False), ("flipped", True)):
        ob = _mk("_probe_cube_" + tag, _cube(flip))
        val["vol_" + tag] = round(islands_signed_volume(ob.data, ob.matrix_world)[0], 3)
    # open control -> area-weighted frac_up
    for tag, flip in (("good", False), ("flipped", True)):
        ob = _mk("_probe_sheet_" + tag, _sheet(flip))
        val["fracup_" + tag] = round(frac_up(ob.data, ob.matrix_world), 3)

    for n in made:
        bpy.data.objects.remove(bpy.data.objects[n], do_unlink=True)
    for m in list(bpy.data.meshes):
        if m.users == 0 and not m.use_fake_user:
            bpy.data.meshes.remove(m)

    assert val["vol_good"] > 0 > val["vol_flipped"], \
        "signed-volume test is sign-inverted: %s" % val
    assert val["fracup_good"] > 0.9 > 0.1 > val["fracup_flipped"], \
        "frac_up test is sign-inverted: %s" % val
    return val


# ------------------------------------------------------------------- sweep
def main():
    val = _validate()
    deps = bpy.context.evaluated_depsgraph_get()

    # One entry per unique mesh datablock: a fix applied per object would
    # flip a shared mesh once per user.
    unique = {}
    for ob in bpy.data.objects:
        if ob.type != 'MESH' or ob.data is None or _match(ob.name, SKIP):
            continue
        unique.setdefault(ob.data.name, ob)

    bad, loose = [], []
    counts = {"closed": 0, "open": 0, "interior": 0, "tube": 0}

    for mname, ob in sorted(unique.items()):
        me = ob.data
        if len(me.polygons) == 0:
            continue
        if _match(ob.name, INTERIOR):
            counts["interior"] += 1
            f = interior_ok(ob)
            if f < 0.5:
                bad.append((ob.name, "interior", round(f, 3)))
        elif _match(ob.name, TUBE):
            counts["tube"] += 1
            f = frac_front_facing(ob, deps)
            if f is not None and f < 0.5:
                bad.append((ob.name, "tube ray", round(f, 3)))
        elif _match(ob.name, FORCE_CLOSED) or is_closed(me):
            counts["closed"] += 1
            vols = islands_signed_volume(me, ob.matrix_world)
            # A loose vertex is a one-vertex island of volume exactly 0.0, not
            # negative, so test v < 0, not v <= 0. convex_hull is the usual
            # source (it leaves interior points in the mesh); delete
            # geom_interior + geom_unused. Loose vertices are reported
            # separately so they cannot bury a real inversion.
            neg = [round(v, 2) for v in vols if v < -1e-9]
            zero = sum(1 for v in vols if abs(v) <= 1e-9)
            if neg:
                bad.append((ob.name, "closed", "%d/%d islands" % (len(neg), len(vols)), neg[:4]))
            if zero:
                loose.append((ob.name, zero, len(vols)))
        else:
            counts["open"] += 1
            f = frac_up(me, ob.matrix_world)
            if f <= 0.02:
                bad.append((ob.name, "open frac_up", round(f, 4)))

    print("=" * 74)
    print("normals audit")
    print("  controls        : volume %+0.3f / %+0.3f   frac_up %.3f / %.3f"
          % (val["vol_good"], val["vol_flipped"],
             val["fracup_good"], val["fracup_flipped"]))
    print("  unique meshes   : %d" % len(unique))
    print("  by test         : %s" % counts)
    print("  INVERTED        : %d" % len(bad))
    for b in bad:
        print("      ! %s" % (b,))
    print("  loose-vert meshes: %d  (not a normals fault -- see comment in source)"
          % len(loose))
    if not QUIET:
        for n, z, t in sorted(loose, key=lambda t: -t[1])[:12]:
            print("      . %s  %d of %d islands are loose verts" % (n, z, t))
    print("  RESULT: %s" % ("PASS" if not bad else "FAIL"))
    print("=" * 74)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
