"""
Dataset Generator for Depth Estimation
Fetches SAR + DEM data from Google Earth Engine
"""

import ee
import numpy as np
from datetime import datetime, timedelta

# Support both relative and absolute imports
try:
    from core.synthetic_labels import SyntheticDepthGenerator
except ImportError:
    from ..core.synthetic_labels import SyntheticDepthGenerator

try:
    ee.Initialize(project='caramel-pulsar-475810-e7')
except:
    pass


class DepthDatasetGenerator:
    """Generate training dataset from GEE"""
    
    def __init__(self, aoi_coords, start_date, end_date):
        """
        Args:
            aoi_coords: [lon_min, lat_min, lon_max, lat_max]
            start_date: Start date string 'YYYY-MM-DD'
            end_date: End date string 'YYYY-MM-DD'
        """
        self.aoi = ee.Geometry.Rectangle(aoi_coords)
        self.start_date = start_date
        self.end_date = end_date
        self.label_gen = SyntheticDepthGenerator()
    
    def get_sentinel1(self, date):
        """Get Sentinel-1 SAR for date"""
        s1 = ee.ImageCollection('COPERNICUS/S1_GRD') \
            .filterBounds(self.aoi) \
            .filterDate(date, ee.Date(date).advance(1, 'day')) \
            .filter(ee.Filter.eq('instrumentMode', 'IW')) \
            .select(['VV', 'VH'])
        
        return s1.median()
    
    def simple_flood_detection(self, sar):
        """Simple threshold-based flood detection"""
        vv = sar.select('VV')
        
        threshold = vv.reduceRegion(
            reducer=ee.Reducer.percentile([20]),
            geometry=self.aoi,
            scale=10,
            maxPixels=1e9
        ).get('VV')
        
        return vv.lt(ee.Number(threshold))
    
    def create_sample(self, date_str):
        """Create one training sample (SAR + depth)"""
        # Get SAR
        sar = self.get_sentinel1(date_str)
        
        # Detect flood
        flood_mask = self.simple_flood_detection(sar)
        
        # Generate depth label
        depth = self.label_gen.generate(flood_mask, self.aoi, max_depth=5.0)
        
        # Combine
        sample = sar.addBands(depth)
        
        return sample
    
    def generate_dataset(self, n_samples=80, patch_size=128, seed=42):
        """
        Generate complete training dataset
        
        Args:
            n_samples: Number of patches to generate
            patch_size: Size of each patch
            seed: Random seed
            
        Returns:
            X: SAR data [n_samples, patch_size, patch_size, 2]
            y: Depth labels [n_samples, patch_size, patch_size, 1]
        """
        print(f"Generating {n_samples} training samples...")
        print(f"Region: {self.aoi.coordinates().getInfo()}")
        print(f"Date range: {self.start_date} to {self.end_date}")
        
        # Generate date range (weekly)
        start = datetime.strptime(self.start_date, '%Y-%m-%d')
        end = datetime.strptime(self.end_date, '%Y-%m-%d')
        dates = [start + timedelta(days=x*7) for x in range((end-start).days//7 + 1)]
        
        X_patches = []
        y_patches = []
        
        for i in range(n_samples):
            date = dates[i % len(dates)].strftime('%Y-%m-%d')
            
            try:
                # Create sample
                sample = self.create_sample(date)
                
                # Sample pixels
                pixels = sample.sample(
                    region=self.aoi,
                    scale=10,
                    numPixels=patch_size * patch_size,
                    seed=seed + i
                )
                
                features = pixels.getInfo()['features']
                
                if len(features) >= patch_size * patch_size:
                    # Extract values
                    vv = [f['properties'].get('VV', 0) for f in features[:patch_size*patch_size]]
                    vh = [f['properties'].get('VH', 0) for f in features[:patch_size*patch_size]]
                    depth = [f['properties'].get('depth', 0) for f in features[:patch_size*patch_size]]
                    
                    # Reshape
                    vv_img = np.array(vv).reshape(patch_size, patch_size)
                    vh_img = np.array(vh).reshape(patch_size, patch_size)
                    depth_img = np.array(depth).reshape(patch_size, patch_size, 1)
                    
                    sar_img = np.stack([vv_img, vh_img], axis=-1)
                    
                    X_patches.append(sar_img)
                    y_patches.append(depth_img)
                    
                    if (i + 1) % 10 == 0:
                        print(f"  Generated {i+1}/{n_samples} samples")
                        
            except Exception as e:
                print(f"  Skipped sample {i+1}: {e}")
                continue
        
        X = np.array(X_patches, dtype=np.float32)
        y = np.array(y_patches, dtype=np.float32)
        
        print(f"\n✓ Dataset generated: X={X.shape}, y={y.shape}")
        return X, y