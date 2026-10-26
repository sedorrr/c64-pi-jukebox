#!/usr/bin/env python3
"""
STEP files of the case for Autodesk Fusion, FreeCAD, Onshape ...: every part is exported from pi_case.scad by
OpenSCAD in its assembly position, read as a mesh, sewn to a solid and its coplanar triangles are merged into
plane faces (so flat faces are one face each; round edges stay facetted). The STEP files always match the .scad.
Writes pi_base.step, pi_hood.step, monitor_front.step, monitor_back.step and pi_case.step (all together).

Needs: OpenSCAD and CadQuery (pip install cadquery), e.g. ../../tools/cadquery-venv/bin/python pi_case_to_step.py
"""
import os
import shutil
import subprocess
import sys
import tempfile

import cadquery as cq
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid, BRepBuilderAPI_Sewing
from OCP.ShapeUpgrade import ShapeUpgrade_UnifySameDomain
from OCP.StlAPI import StlAPI_Reader
from OCP.TopAbs import TopAbs_SHELL
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS, TopoDS_Shape

HERE = os.path.dirname(os.path.abspath(__file__))
PARTS = [("base", "pi_base"), ("hood", "pi_hood"), ("monitor_front_placed", "monitor_front"),
         ("monitor_back_placed", "monitor_back")]


def openscad():
    for p in ("openscad", "/Applications/OpenSCAD.app/Contents/MacOS/OpenSCAD"):
        if shutil.which(p) or os.path.exists(p):
            return p
    sys.exit("OpenSCAD not found")


def stl_to_solid(path):
    mesh = TopoDS_Shape()
    StlAPI_Reader().Read(mesh, path)
    sew = BRepBuilderAPI_Sewing(1e-4)
    sew.Add(mesh)
    sew.Perform()
    maker = BRepBuilderAPI_MakeSolid()
    ex = TopExp_Explorer(sew.SewedShape(), TopAbs_SHELL)
    while ex.More():
        maker.Add(TopoDS.Shell_s(ex.Current()))
        ex.Next()
    unify = ShapeUpgrade_UnifySameDomain(maker.Solid(), True, True, True)
    unify.Build()
    return cq.Shape.cast(unify.Shape())


def main():
    tmp = tempfile.mkdtemp()
    shapes = []
    for part, name in PARTS:
        stl = os.path.join(tmp, name + ".stl")
        subprocess.run([openscad(), "-D", f'part="{part}"', "-o", stl, os.path.join(HERE, "pi_case.scad")],
                       check=True, capture_output=True)
        solid = stl_to_solid(stl)
        print(f"{name}: valid={solid.isValid()} volume={solid.Volume():.0f} mm3 faces={len(solid.Faces())}")
        cq.exporters.export(solid, os.path.join(HERE, name + ".step"))
        shapes.append(solid)
    cq.exporters.export(cq.Compound.makeCompound(shapes), os.path.join(HERE, "pi_case.step"))
    shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
