"""
Synthetic Depth Label Generator
Uses DEM to create training labels without ground truth
"""

import ee
import numpy as np

try:
    ee.Initialize()
except:
    pass


class SyntheticDepthGenerator:
    """Generate synthetic depth labels from DEM"""
    
    def __init__(self, dem_asset='USGS/SRTMGL1_003'):
        self.dem = ee.Image(dem_asset).select('elevation')
    
    def generate(self, flood_mask, aoi, max_depth=5.0):
        """
        Generate synthetic depth from topography
        
        Args:
            flood_mask: ee.Image with flood detection (1=flooded, 0=dry)
            aoi: ee.Geometry for area of interest
            max_depth: Maximum depth in meters
            
        Returns:
            ee.Image with depth values in meters
        """
        # Get elevation only in flooded areas
        flooded_elevation = self.dem.updateMask(flood_mask.eq(1))
        
        # Calculate flood water level (90th percentile)
        water_level = flooded_elevation.reduceRegion(
            reducer=ee.Reducer.percentile([90]),
            geometry=aoi,
            scale=30,
            maxPixels=1e9
        ).get('elevation')
        
        # Depth = water_level - ground_elevation
        depth = ee.Image(water_level).subtract(self.dem)
        depth = depth.updateMask(flood_mask.eq(1))
        
        # Clip to realistic range
        depth = depth.clamp(0, max_depth)
        
        # Add noise for realism (±10%)
        noise = ee.Image.random(0).multiply(0.2).subtract(0.1)
        depth = depth.multiply(ee.Image(1).add(noise))
        
        return depth.clamp(0, max_depth).rename('depth')