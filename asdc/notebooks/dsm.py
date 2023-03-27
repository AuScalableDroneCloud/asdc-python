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
    gt = dataset.GetGeoTransform()
    print(gt)

    cols = dataset.RasterXSize
    rows = dataset.RasterYSize
    bands = dataset.RasterCount
    driver = dataset.GetDriver().LongName
    print(cols,rows,bands,driver)

    width = dataset.RasterXSize
    height = dataset.RasterYSize
    minc = [gt[0], gt[3] + width*gt[4] + height*gt[5]]
    maxc = [gt[0] + width*gt[1] + height*gt[2], gt[3]]
    print("Corners:", minc,maxc)

    #Calc subsampling
    SS = 1
    lim = 10000000
    if cols*rows > lim:
        SS = cols*rows // lim
        print(f"Subsampling by a factor of {SS}")

    def createvertexarray(raster, invalid):
        #Read height
        zz = raster.ReadAsArray()
        #Subsample
        print(zz.shape)
        zz = zz[::SS,::SS]
        print(zz.shape)
        #Clear zeros/nulls
        zz[zz <= -9000] = None
        zz[zz == 0] = None

        zrange = [numpy.nanmin(zz),numpy.nanmax(zz)]
        print("Zmin/max",zrange)

        transform = raster.GetGeoTransform()
        width = zz.shape[1]
        height = zz.shape[0]
        x = numpy.arange(0, width) * SS * transform[1] + transform[0] - minc[0]
        y = numpy.arange(0, height) * SS * transform[5] + transform[3] - minc[1]
        xx, yy = numpy.meshgrid(x, y)
        xx = xx.astype('float32')
        yy = yy.astype('float32')

        vertices = numpy.vstack((xx,yy,zz)).reshape([3, -1]).transpose().reshape((zz.shape[1], zz.shape[0], 3))
        print(vertices.shape)
        return vertices, zrange

    vertices, zrange = createvertexarray(dataset, invalid=0)

    #Post-process data into float range and remove invalid values
    print("Plotting...")
    grid = lv.triangles(colour="white") #vertexnormals=False,
    grid["dims"]= [vertices.shape[0], vertices.shape[1]] #[cols,rows] #dims #[cols/subsample., rows/subsample]
    grid.vertices(vertices)
    #Load z coord height as scalar field
    height = vertices[:,:, 2]
    grid.values(height, "height")

    #Calculate range from height values
    h = max(abs(zrange[0]), abs(zrange[1]))
    grid.colourmap("geo", range=[-h,h])
    grid.colourbar()

    return grid

dem = loadDEM(filename)
# -

lv.display()

lv.window()


