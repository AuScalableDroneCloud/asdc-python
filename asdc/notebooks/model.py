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
# # Load and view a Surface Model
#
# Requires trimesh, lavavu : `pip install trimesh lavavu-osmesa`)
#
# trimesh contains many tools for extracting data from and analysing mesh data as well as conversions between formats
#
# lavavu provides interactive visualisation on the server for inspecting the mesh data visually

# + inputHidden=false outputHidden=false
import asdc
import pathlib
import os

inputs = asdc.get_inputs()
task_name = inputs['task_name']
#filename = 'textured_model.glb'
filename = 'textured_model.zip'

asdc.download_asset(filename)
# -
# ### Extract .zip file
# ... if necessary

if '.zip' in filename:
    obj_filename = 'odm_textured_model_geo.obj'
    if not os.path.exists(obj_filename):
        os.system(f'unzip "{filename}"')
    filename = obj_filename

# ## 3d interactive render
# (Requires lavavu renderer - s/w rendering version: `pip install lavavu-osmesa`)

import lavavu
lv = lavavu.Viewer(border=0)

# ### Load mesh
#
# Load using trimesh, supports GLTF etc
#
# See: https://trimsh.org/trimesh.exchange.html
# Requires "trimesh" module
#
# Currently the glb loader doesn't seem to support meshes output by OpenDroneMap (glTF extension KHR_draco_mesh_compression is required in this model)

# +
import trimesh
import numpy
scene = trimesh.load(filename)
mesh = lv.triangles(task_name)
def load_mesh(geometry):
    global mesh, lv
    mesh.append()
    mesh.vertices(geometry.vertices)
    mesh.normals(geometry.vertex_normals)
    mesh.indices(geometry.faces)

    #Load vertex colours if available
    if hasattr(geometry.visual, "vertex_colors"):
        mesh.colours(geometry.visual.vertex_colors)
    #Load single colour material or texture
    elif hasattr(geometry.visual, "material"):
        if hasattr(geometry.visual.material, "image"):
            image = numpy.asarray(geometry.visual.material.image)
            mesh.texture(image)
            mesh.texcoords(geometry.visual.uv)
        elif hasattr(geometry.visual.material, "baseColorFactor"):
            if idx == 0:
                #Can set as prop, but only works for single el
                mesh["colour"] = geometry.visual.material.baseColorFactor
            else:
                mesh.colours(geometry.visual.material.baseColorFactor)

for idx,name in enumerate(scene.geometry.keys()):
    geometry = scene.geometry[name]
    if idx == 0:
        #Until renderer bug fixed, load a dummy first textured element and hide it
        if hasattr(geometry.visual, "material") and hasattr(geometry.visual.material, "image"):
            mesh.vertices(geometry.vertices[0])
            mesh.normals(geometry.vertex_normals[0])
            image = numpy.asarray(geometry.visual.material.image)
            mesh.texture(image)
            lv.hide('triangles', 0)
    load_mesh(geometry)

# -

lv.rotate([-60,0,0])
lv.display()

lv.window()


