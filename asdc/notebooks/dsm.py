# + [markdown] inputHidden=false outputHidden=false
# # Load and view a Digital Surface Model
#
# Based on:
# https://www.earthdatascience.org/courses/use-data-open-source-python/intro-raster-data-python/fundamentals-raster-data/open-lidar-raster-python/
# + inputHidden=false outputHidden=false
import asdc
import pathlib
import os

inputs = asdc.get_inputs()
task_name = inputs['task_name']
filename = 'dsm.tif'

asdc.download_asset(filename)
# -

# !pip install earthpy

import earthpy as et
import earthpy.plot as ep

# +
# Import necessary packages
import os
import matplotlib.pyplot as plt
# Use geopandas for vector data and rasterio for raster data
import geopandas as gpd
import rasterio as rio
# Plotting extent is used to plot raster & vector data together
from rasterio.plot import plotting_extent

import earthpy as et
import earthpy.plot as ep

# +
# Define relative path to file
dem_pre_path = os.path.join("colorado-flood",
                            "spatial",
                            "boulder-leehill-rd",
                            "pre-flood",
                            "lidar",
                            "pre_DTM.tif")

dem_pre_path = filename

# Open the file using a context manager ("with rio.open" statement)
with rio.open(dem_pre_path) as dem_src:
    dtm_pre_arr = dem_src.read(1)

# +
# Plot your data using earthpy
ep.plot_bands(dtm_pre_arr,
              title=f"Lidar Digital Elevation Model (DEM) \n {task_name}",
              cmap="Greys")

plt.show()
# -

print("the minimum raster value is: ", dtm_pre_arr.min())
print("the maximum raster value is: ", dtm_pre_arr.max())


# A histogram can also be helpful to look at the range of values in your data
# What do you notice about the histogram below?
ep.hist(dtm_pre_arr,
        figsize=(10, 6))
plt.show()


# Read in your data and mask the no data values
with rio.open(dem_pre_path) as dem_src:
    # Masked=True will mask all no data values
    dtm_pre_arr = dem_src.read(1, masked=True)


print("the minimum raster value is: ", dtm_pre_arr.min())
print("the maximum raster value is: ", dtm_pre_arr.max())


# A histogram can also be helpful to look at the range of values in your data
ep.hist(dtm_pre_arr,
        figsize=(10, 6),
        title="Histogram of the Data with No Data Values Removed")
plt.show()

# +
# Plot data using earthpy
ep.plot_bands(dtm_pre_arr,
              title=f"Lidar Digital Elevation Model (DEM) \n {task_name}",
              cmap="Greys")

plt.show()
# -
# ## 3d interactive render
# (Requires lavavu renderer - s/w rendering version: `pip install lavavu-osmesa`)

# +
import numpy
import lavavu
lv = lavavu.Viewer(axis=False, border=0, port=8080)

def loadDEM(fn):
    import osgeo.gdal
    dataset = osgeo.gdal.Open(fn)
    print(dataset)
    gt = dataset.GetGeoTransform()
    print(gt)

    cols = dataset.RasterXSize
    rows = dataset.RasterYSize
    bands = dataset.RasterCount
    driver = dataset.GetDriver().LongName

    width = dataset.RasterXSize
    height = dataset.RasterYSize
    minc = [gt[0], gt[3] + width*gt[4] + height*gt[5]]
    maxc = [gt[0] + width*gt[1] + height*gt[2], gt[3]]
    print(minc)
    print(maxc)

    #myarray = dataset.GetRasterBand(1).ReadAsArray()
    zrange = [-1,1]
    def createvertexarray(raster, invalid):
        transform = raster.GetGeoTransform()
        width = raster.RasterXSize
        height = raster.RasterYSize
        x = numpy.arange(0, width) * transform[1] + transform[0] - minc[0]
        y = numpy.arange(0, height) * transform[5] + transform[3] - minc[1]
        xx, yy = numpy.meshgrid(x, y)
        xx = xx.astype('float32')
        yy = yy.astype('float32')
        zz = raster.ReadAsArray()
        #Clear zeros/nulls
        zz[zz <= -9000] = None
        zz[zz == 0] = None
        zrange = [numpy.nanmin(zz),numpy.nanmax(zz)]
        print("Zmin/max",zrange)
        vertices = numpy.vstack((xx,yy,zz)).reshape([3, -1]).transpose()
        return vertices, zrange

    vertices, zrange = createvertexarray(dataset, invalid=0)

    print("Plotting...")
    grid = lv.triangles(vertexnormals=False, colour="white", range=zrange)
    grid["dims"]=[cols,rows] #dims #[cols/subsample., rows/subsample]
    grid.vertices(vertices)
    
    #Plot height values with colourmap
    height = vertices[:, 2].ravel()
    grid.values(height, "height")
    cm = grid.colourmap("elevation", reverse=True)
    grid.colourbar()
    
dem = loadDEM(filename)

lv.rotation(-45,0,0)
# -

lv.display()

lv.window()


