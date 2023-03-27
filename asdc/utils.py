"""
# ASDC Utility and convenience functions

## Australian Scalable Drone Cloud API module

"""

import logging
logger = logging.getLogger('app.logger')
import json
import re
import os
from PIL import Image
import piexif

import sys
class ExecutionPaused(Exception):
    """Pause Execution Exception for IPython.

    Stop execution but hides the traceback and exception details
    """
    def __init__(self, message=''):
        ipython = get_ipython()
        self.default_traceback = ipython.showtraceback

        def hide_traceback(*args, **kwargs):
            etype, value, tb = sys.exc_info()
            #If the exception type is ExecutionPaused, print minimal notification and no traceback
            #otherwise print the standard traceback output
            if etype == type(self):
                if message: print(message)
                value.__cause__ = None  # suppress chained exceptions
                return ipython._showtraceback(etype, value, ipython.InteractiveTB.get_exception_only(etype, value))
            else:
                return self.default_traceback(*args, **kwargs)

        ipython.showtraceback = hide_traceback

    def __del__(self):
        #Restore
        ipython.showtraceback = self.default_traceback


def is_notebook():
    """
    Detects if running within an interactive IPython notebook environment

    Returns
    -------
    boolean
        True if IPython detected and browser/notebook display capability detected
    """
    if 'IPython' not in sys.modules:
        # IPython hasn't been imported, definitely not
        return False
    try:
        from IPython import get_ipython
        from IPython.display import display,Image,HTML
    except:
        return False
    # check for `kernel` attribute on the IPython instance
    return getattr(get_ipython(), 'kernel', None) is not None

def resize_image(image_path, resize_to, done=None):
    """
    Provides the image_resize function from WebODM:
    https://github.com/OpenDroneMap/WebODM/blob/master/app/models/task.py
    https://github.com/OpenDroneMap/WebODM/blob/master/LICENSE.md

    :param image_path: path to the image
    :param resize_to: target size to resize this image to (largest side)
    :param done: optional callback
    :return: path and resize ratio
    """
    try:
        can_resize = False

        # Check if this image can be resized
        # There's no easy way to resize multispectral 16bit images
        # (Support should be added to PIL)
        is_jpeg = re.match(r'.*\.jpe?g$', image_path, re.IGNORECASE)

        if is_jpeg:
            # We can always resize these
            can_resize = True
        else:
            try:
                bps = piexif.load(image_path)['0th'][piexif.ImageIFD.BitsPerSample]
                if isinstance(bps, int):
                    # Always resize single band images
                    can_resize = True
                elif isinstance(bps, tuple) and len(bps) > 1:
                    # Only resize multiband images if depth is 8bit
                    can_resize = bps == (8, ) * len(bps)
                else:
                    logger.warning("Cannot determine if image %s can be resized, hoping for the best!" % image_path)
                    can_resize = True
            except KeyError:
                logger.warning("Cannot find BitsPerSample tag for %s" % image_path)

        if not can_resize:
            logger.warning("Cannot resize %s" % image_path)
            return {'path': image_path, 'resize_ratio': 1}

        im = Image.open(image_path)
        path, ext = os.path.splitext(image_path)
        resized_image_path = os.path.join(path + '.resized' + ext)

        width, height = im.size
        max_side = max(width, height)
        if max_side < resize_to:
            logger.warning('You asked to make {} bigger ({} --> {}), but we are not going to do that.'.format(image_path, max_side, resize_to))
            im.close()
            return {'path': image_path, 'resize_ratio': 1}

        ratio = float(resize_to) / float(max_side)
        resized_width = int(width * ratio)
        resized_height = int(height * ratio)

        im = im.resize((resized_width, resized_height), Image.Resampling.LANCZOS)
        params = {}
        if is_jpeg:
            params['quality'] = 100

        if 'exif' in im.info:
            exif_dict = piexif.load(im.info['exif'])
            #exif_dict['Exif'][piexif.ExifIFD.PixelXDimension] = resized_width
            #exif_dict['Exif'][piexif.ExifIFD.PixelYDimension] = resized_height
            im.save(resized_image_path, exif=piexif.dump(exif_dict), **params)
        else:
            im.save(resized_image_path, **params)

        im.close()

        # Delete original image, rename resized image to original
        os.remove(image_path)
        os.rename(resized_image_path, image_path)

        logger.info("Resized {} to {}x{}".format(image_path, resized_width, resized_height))
    except (IOError, ValueError) as e:
        logger.warning("Cannot resize {}: {}.".format(image_path, str(e)))
        if done is not None:
            done()
        return None

    retval = {'path': image_path, 'resize_ratio': ratio}

    if done is not None:
        done(retval)

    return retval


def default_inputs():
    #Get default inputs from env
    tasks = list(filter(None, re.split('[, ]+', os.getenv("ASDC_TASKS", ""))))
    projects = [int(p) for p in list(filter(None, re.split('\W+', os.getenv("ASDC_PROJECTS", ""))))]
    return {"projects" : projects, "tasks" : tasks, "port" : None}

def write_inputs(tasks=[], projects=[], port=None):
    #Write input data from env to inputs.json
    data = read_inputs()
    if len(tasks):
        data['tasks'] = tasks
    if len(projects):
        data['projects'] = projects
    if "ASDC_INPUT_FILE" in os.environ:
        path = os.path.dirname(os.environ["ASDC_INPUT_FILE"])
        if not os.path.exists(path):
            try:
                os.makedirs(path)
            except:
                print(f"Failed to make path: {path}")
                return data
        with open(os.environ["ASDC_INPUT_FILE"], 'w') as f:
            json.dump(data, f)
    return data

def write_port(port):
    #Write input data from env to inputs.json
    data = read_inputs()
    data["port"] = port
    if "ASDC_INPUT_FILE" in os.environ:
        with open(os.environ["ASDC_INPUT_FILE"], 'w') as f:
            json.dump(data, f)

def read_inputs():
    #Read the project and task json data for import
    inputs_dict = default_inputs()
    if "ASDC_INPUT_FILE" in os.environ:
        fn = os.environ["ASDC_INPUT_FILE"]
        #If file has not been written, return defaults
        if not os.path.exists(fn):
            return default_inputs()
        #Read json into dict and return
        with open(fn, 'r') as f:
            try:
                inputs_dict = json.load(f)
            except (json.decoder.JSONDecodeError) as e:
                pass

    return inputs_dict

def get_inputs(filename='input.json'):
    #Load locally saved inputs
    with open(filename, 'r') as f:
        inputs = json.load(f)
        project = inputs['project']
        task = inputs['task']
        asdc.set_selection(project, task)
        return inputs

