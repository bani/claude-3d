#!/usr/bin/env python3
"""Verify written FBX files against the Blender->Unity transform rules.

    python3 verify_fbx.py path/to/*.fbx        # files, or a directory of .fbx
    python3 verify_fbx.py --legacy path/to/vrchat/*.fbx   # expect the OLD convention

Checks the written file, not the exporter flags. Both faults below render
correctly, then surface later as 100x child offsets, outline widths or
PhysBone radii, or a model facing down once an Animator binds the hierarchy.

  1. UnitScaleFactor must be 100 and UpAxis 1 (Y). With FBX_SCALE_NONE
     ("All Local") the file has UnitScaleFactor 1.0 and Lcl Scaling
     [100,100,100], and the object imports at Transform scale 100.
     Fix: apply_scale_options = 'FBX_SCALE_ALL'
  2. No model node may carry the signature Lcl Scaling ~(100,100,100) or
     Lcl Rotation ~(-90,0,0). With bake_space_transform=False the Z-up to
     Y-up conversion is written as a rotation, and the vertices stay Z-up
     under a Y-up header.
     Fix: bake_space_transform = True
  3. The vertex bounding box is printed for inspection (not checked): its Y
     extent must be the model's height.

Only the two signatures are tested, not every non-identity transform, because
placed instances legitimately carry per-object rotation and scale. To validate
this script, export one object with Blender's defaults and confirm it FAILS.

--legacy inverts checks 1 (scale only) and 2, for a project deliberately kept
on the old convention (references/unity-vrchat.md section 4). It is not a way
to silence a failure on a new export.

Exit status: 0 if every file passes, 1 on any failure, 2 if no files given.
"""
import struct, zlib, sys, os, math

def read_fbx(path):
    d=open(path,'rb').read()
    if d[:20]!=b'Kaydara FBX Binary  ': raise ValueError("not a binary FBX")
    ver=struct.unpack('<I',d[23:27])[0]
    off=27
    is64 = ver>=7500
    def node(off):
        if is64:
            end,nprop,plen=struct.unpack('<QQQ',d[off:off+24]); off+=24
        else:
            end,nprop,plen=struct.unpack('<III',d[off:off+12]); off+=12
        nlen=d[off]; off+=1
        name=d[off:off+nlen].decode('utf-8','replace'); off+=nlen
        if end==0: return None,off
        props=[]
        pend=off+plen
        for _ in range(nprop):
            if off>=pend: break
            t=chr(d[off]); off+=1
            if t=='Y': props.append(struct.unpack('<h',d[off:off+2])[0]); off+=2
            elif t=='C': props.append(bool(d[off])); off+=1
            elif t=='I': props.append(struct.unpack('<i',d[off:off+4])[0]); off+=4
            elif t=='F': props.append(struct.unpack('<f',d[off:off+4])[0]); off+=4
            elif t=='D': props.append(struct.unpack('<d',d[off:off+8])[0]); off+=8
            elif t=='L': props.append(struct.unpack('<q',d[off:off+8])[0]); off+=8
            elif t in 'fdlic b':
                al,enc,cl=struct.unpack('<III',d[off:off+12]); off+=12
                raw=d[off:off+cl]; off+=cl
                if enc==1: raw=zlib.decompress(raw)
                fmt={'f':'f','d':'d','l':'q','i':'i','b':'b','c':'B'}[t]
                props.append(list(struct.unpack('<%d%s'%(al,fmt),raw)) if al else [])
            elif t=='S' or t=='R':
                l=struct.unpack('<I',d[off:off+4])[0]; off+=4
                v=d[off:off+l]; off+=l
                props.append(v.decode('utf-8','replace') if t=='S' else v)
            else:
                raise ValueError("bad prop type %r at %d"%(t,off))
        off=pend
        kids=[]
        while off < end:
            k,off2 = node(off)
            if k is None:
                off=off2
                if off>=end: break
                continue
            kids.append(k); off=off2
            if off>=end: break
        return {"name":name,"props":props,"children":kids}, end
    roots=[]
    while off < len(d)-160:
        n,off = node(off)
        if n is None: break
        roots.append(n)
    return ver, roots

def walk(n, name=None):
    if name is None or n["name"]==name: yield n
    for c in n["children"]:
        yield from walk(c,name)

def check(path, legacy=False):
    ver,roots=read_fbx(path)
    print("="*78)
    print("%s  (FBX version %d)" % (os.path.basename(path),ver))
    fails=[]

    # ---- 1. UnitScaleFactor
    usf=None; upaxis=None
    for r in roots:
        for n in walk(r,"P"):
            if n["props"] and n["props"][0]=="UnitScaleFactor":
                usf=n["props"][-1]
            if n["props"] and n["props"][0]=="UpAxis":
                upaxis=n["props"][-1]
    print("  UnitScaleFactor : %s" % usf)
    print("  UpAxis          : %s  (1 = Y)" % upaxis)
    want_usf = 1.0 if legacy else 100.0
    if usf is None or abs(usf-want_usf)>1e-6:
        fails.append("UnitScaleFactor is %s, expected %g%s" % (
            usf, want_usf,
            " (legacy convention)" if legacy
            else " -- objects will land in Unity at scale 100"))
    if upaxis!=1:
        fails.append("UpAxis is %s, expected 1 (Y)" % upaxis)

    # ---- 2. Lcl Scaling / Lcl Rotation fault signatures on model nodes
    # Test the two signatures, not any non-identity transform: placed
    # instances legitimately carry per-object rotation and scale.
    #   scale ~ (100,100,100)  -> FBX_SCALE_NONE wrote m->cm into the local xform
    #   rot   ~ (-90, 0, 0)    -> Z-up->Y-up written as a rotation, not into verts
    bad_scale=[]; bad_rot=[]; n_scale=0; n_rot=0
    smin=[1e30]*3; smax=[-1e30]*3
    for r in roots:
        for m in walk(r,"Model"):
            mname = m["props"][1] if len(m["props"])>1 else "?"
            for p in walk(m,"P"):
                if not p["props"]: continue
                k=p["props"][0]
                if k=="Lcl Scaling":
                    v=[float(x) for x in p["props"][-3:]]
                    n_scale+=1
                    for i in range(3):
                        smin[i]=min(smin[i],v[i]); smax[i]=max(smax[i],v[i])
                    if all(abs(x-100.0)<1.0 for x in v): bad_scale.append((mname,v))
                if k=="Lcl Rotation":
                    v=[float(x) for x in p["props"][-3:]]
                    n_rot+=1
                    if abs(v[0]+90.0)<0.01 and abs(v[1])<0.01 and abs(v[2])<0.01:
                        bad_rot.append((mname,v))
    print("  Lcl Scaling nodes  : %d present" % n_scale, end="")
    if n_scale: print("  range %.3f..%.3f (per-instance scale is legitimate)"
                      % (min(smin),max(smax)))
    else: print()
    print("  Lcl Rotation nodes : %d present (per-instance rotation is legitimate)" % n_rot)
    print("  scale ~100 signature   : %d   <- FBX_SCALE_NONE fault" % len(bad_scale))
    print("  rot (-90,0,0) signature: %d   <- bake_space_transform fault" % len(bad_rot))
    for n,v in bad_scale[:3]: print("      scale  %s %s" % (n,[round(x,3) for x in v]))
    for n,v in bad_rot[:3]:   print("      rot    %s %s" % (n,[round(x,3) for x in v]))
    if legacy:
        # The old convention is expected here ON PURPOSE, so its ABSENCE is
        # the fault -- a file silently upgraded to the correct convention
        # breaks every child transform tuned against the 100x/-90 parents.
        if not bad_scale: fails.append("no Lcl Scaling ~100 found, but --legacy expects the old convention")
        if not bad_rot:   fails.append("no Lcl Rotation (-90,0,0) found, but --legacy expects the old convention")
    else:
        if bad_scale: fails.append("%d nodes have Lcl Scaling ~100 -- metres/cm baked into the local transform" % len(bad_scale))
        if bad_rot:   fails.append("%d nodes have Lcl Rotation (-90,0,0) -- Z-up not baked into vertices" % len(bad_rot))

    # ---- 3. vertex bounding box: height must be on Y
    mnx=mny=mnz=1e30; mxx=mxy=mxz=-1e30; nv=0
    for r in roots:
        for g in walk(r,"Geometry"):
            for v in walk(g,"Vertices"):
                arr=v["props"][0] if v["props"] else []
                for i in range(0,len(arr),3):
                    x,y,z=arr[i],arr[i+1],arr[i+2]
                    mnx=min(mnx,x); mxx=max(mxx,x)
                    mny=min(mny,y); mxy=max(mxy,y)
                    mnz=min(mnz,z); mxz=max(mxz,z)
                    nv+=1
    if nv:
        dx,dy,dz=mxx-mnx,mxy-mny,mxz-mnz
        print("  vertices        : %d" % nv)
        print("  bbox X %10.2f .. %10.2f  (%.2f)" % (mnx,mxx,dx))
        print("  bbox Y %10.2f .. %10.2f  (%.2f)   <- height axis for Unity" % (mny,mxy,dy))
        print("  bbox Z %10.2f .. %10.2f  (%.2f)" % (mnz,mxz,dz))
        if legacy:
            print("      (legacy convention: the vertices are Z-up ON PURPOSE, so the")
            print("       height belongs on Z here -- see references/unity-vrchat.md)")
        else:
            print("      the model's HEIGHT must be the Y extent. If it is on Z,")
            print("      the vertices are still Z-up: bake_space_transform was off.")
    else:
        print("  no vertices found")
    print("  RESULT: %s" % ("PASS" if not fails else "FAIL"))
    for f in fails: print("     ! "+f)
    return fails, (mnx,mxx,mny,mxy,mnz,mxz,nv) if nv else None

if __name__=="__main__":
    args=sys.argv[1:]
    legacy="--legacy" in args
    paths=[a for a in args if not a.startswith("--")]
    # A bare directory is expanded, so a whole export folder can be checked.
    expanded=[]
    for p in paths:
        if os.path.isdir(p):
            expanded+=[os.path.join(p,f) for f in sorted(os.listdir(p))
                       if f.lower().endswith(".fbx")]
        else:
            expanded.append(p)
    paths=expanded
    if not paths:
        print(__doc__)
        sys.exit(2)
    allf=[]
    for p in paths:
        try:
            f,_=check(p, legacy=legacy); allf+=[(p,x) for x in f]
        except Exception as e:
            print("ERROR on %s: %s"%(p,e)); allf.append((p,str(e)))
    print("="*78)
    print("%d file(s), %d failure(s)" % (len(paths),len(allf)))
    for p,f in allf: print("  %s: %s" % (os.path.basename(p),f))
    sys.exit(1 if allf else 0)
