# + [markdown] inputHidden=false outputHidden=false
# # Loading a data set from ASDC WebODM
#
# This notebook / script will load a specific task dataset
#

# + inputHidden=false outputHidden=false
import asdc
import pathlib
import os
inputs = asdc.get_inputs()
# -

asdc.selected

# ### Select from available assets list

# +
task_j = asdc.call_api(f'/projects/{project}/tasks/{task}').json()
available_assets = task_j['available_assets']

import ipywidgets as widgets

options=[("Orthophoto", 'orthophoto.tif'),
         ("Surface Model", 'dsm.tif'),
         ("Point Cloud", 'georeferenced_model.laz'),
         ("Textured Model", 'textured_model.zip'),
         ("Textured Model (gLTF)", 'textured_model.glb'),
        ]
options = [o for o in options if o[1] in available_assets]

filesel = widgets.Dropdown(
    options=options,
    value=inputs['asset'],
    description='Asset:',
)
filesel
# -

# ### Download the asset into a subdirectory

filename = filesel.value
asdc.download_asset(filename)

# ### Display a thumbnail (for image assets)

# + inputHidden=false outputHidden=false
from IPython.display import display, HTML
if '.tif' in filename or '.png' in filename or '.jpg' in filename:
    from PIL import Image
    im = Image.open(filename)
    if im.mode != 'RGB':
        im = im.convert('RGB')
    im.thumbnail((350,350),Image.LANCZOS)
    display(im)
# -

# ### More examples of visualisation and processing...

if filename == 'dsm.tif':
    display(HTML('<a href="dsm.py">Load DSM</a>'))
elif filename == 'georeferenced_model.laz':
    display(HTML('<a href="points.py">Load Point Cloud</a>'))
elif filename == 'textured_model.zip' or filename == 'textured_model.glb':
    display(HTML('<a href="model.py">Load Textured Model</a>'))


