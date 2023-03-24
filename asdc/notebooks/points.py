# ---
# jupyter:
#   jupytext:
#     text_representation:
#       extension: .py
#       format_name: light
#       format_version: '1.5'
#       jupytext_version: 1.14.5
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# + [markdown] inputHidden=false outputHidden=false
# # Load and view a Point Cloud
#
# (Requires laspy with .laz support: `pip install "laspy[lazrs,laszip]`)

# + inputHidden=false outputHidden=false
import asdc
import pathlib
import os

project = 27 #{PID}
task = 'd3e1e518-cec3-4c1e-a07d-c03068a7f7be' #'{TID}'
asdc.set_selection(project, task)
task_name = 'unnamed'
filename = 'georeferenced_model.laz'

asdc.download_asset(filename)
# -
import laspy

las = laspy.read(filename)

las

len(las)

# ## 3d interactive render
# Subsample the point cloud first to improve render speed if over 1M points  
# (Requires lavavu renderer - s/w rendering version: `pip install lavavu-osmesa`)

subsample = 1
plim = 1000000
if len(las) > plim:
    subsample = len(las) // plim
subsample

# +
#Convert colours from short to uchar
import numpy
def get_data(infile):
    ss = subsample
    if ss > 1:
        V = numpy.array([infile.x[::ss], infile.y[::ss], infile.z[::ss]])
        C = numpy.dstack([las.red[::ss], las.green[::ss], las.blue[::ss]])
        return (V, C)
    else:
        V = numpy.array([infile.x, infile.y, infile.z])
        #C = numpy.array([las.red,las.green,las.blue], dtype=numpy.uint8)
        C = numpy.dstack([las.red, las.green, las.blue])
        return (V, C)
    
V,C = get_data(las)

# -

V

C

import lavavu
lv = lavavu.Viewer(border=0)
p = lv.points(vertices=V, pointsize=3)
p.rgb(C)
lv.rotate([-60,0,0])
lv.bounds() #fix bound calc
lv.display()

lv.window()


