"""
# ASDC Utility and convenience functions

## Australian Scalable Drone Cloud API module

"""

import logging
logger = logging.getLogger('app.logger')
import re
import os
from PIL import Image
import piexif
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

