"""Core depth estimation components"""

try:
    from core.synthetic_labels import SyntheticDepthGenerator
    from core.depth_model import LightweightDepthCNN
    from core.depth_predictor import DepthPredictor
except ImportError:
    from .synthetic_labels import SyntheticDepthGenerator
    from .depth_model import LightweightDepthCNN
    from .depth_predictor import DepthPredictor

__all__ = ['SyntheticDepthGenerator', 'LightweightDepthCNN', 'DepthPredictor']