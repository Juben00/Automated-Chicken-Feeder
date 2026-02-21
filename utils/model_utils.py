import torch
from torchvision import transforms
from PIL import Image
import json
import os

MODEL_PATH = os.path.join(os.path.dirname(__file__), '..', 'models', 'feed_count_model.pth')
CONFIG_PATH = os.path.join(os.path.dirname(__file__), '..', 'config.json')

_model = None


# Load the correct model architecture and weights
def get_model(model_path=None, device=None):
    import sys
    sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'model'))
    if device is None:
        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    if model_path is None:
        # Default path (update as needed)
        model_path = os.path.join(os.path.dirname(__file__), '..', 'checkpoint', 'best_optimized_epoch_79.pth')
    # Try to import enhanced model first
    try:
        from enhanced_mcnn_model import EnhancedMCNNForPellets
        model = EnhancedMCNNForPellets().to(device)
    except ImportError:
        from mcnn_model import ImprovedMCNN
        model = ImprovedMCNN().to(device)
    checkpoint = torch.load(model_path, map_location=device)
    if isinstance(checkpoint, dict) and 'model_state_dict' in checkpoint:
        model.load_state_dict(checkpoint['model_state_dict'])
    else:
        model.load_state_dict(checkpoint)
    model.eval()
    return model


# Predict pellet count using the actual model output (sum of density map)
def predict_pellets(model, image_file, device=None):
    from PIL import Image
    import numpy as np
    import torch
    if device is None:
        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    image = Image.open(image_file).convert('RGB')
    # Model expects 512x512 input, normalized to [0,1]
    preprocess = transforms.Compose([
        transforms.Resize((512, 512)),
        transforms.ToTensor(),
    ])
    input_tensor = preprocess(image).unsqueeze(0).to(device)
    with torch.no_grad():
        output = model(input_tensor)
        # Output is a density map, sum to get count
        pellet_count = float(output.sum().item())
    return pellet_count


def _find_density_peaks(density_map, min_distance=3, threshold_factor=0.3):
    """
    Find local maxima in density map as pellet centers.
    Returns list of (y, x) in density map coordinates.
    """
    import numpy as np
    if hasattr(density_map, 'cpu'):
        arr = density_map.squeeze().cpu().numpy()
    else:
        arr = np.asarray(density_map).squeeze()
    if arr.ndim > 2:
        arr = arr[0]
    h, w = arr.shape
    total = arr.sum()
    if total <= 0:
        return []
    threshold = max(arr.min(), float(total) / (h * w) * threshold_factor)
    # Local maxima: pixel is max in (2*md+1)x(2*md+1) window
    md = min_distance
    pad = np.pad(arr, md, mode='constant', constant_values=-np.inf)
    peaks = []
    for i in range(md, h + md):
        for j in range(md, w + md):
            v = pad[i, j]
            if v < threshold:
                continue
            window = pad[i - md:i + md + 1, j - md:j + md + 1]
            if v >= window.max():
                peaks.append((i - md, j - md))
    return peaks


def predict_pellets_with_positions(model, image_file, device=None):
    """
    Returns (count, positions) where positions is list of (x, y) in original image coords.
    """
    from PIL import Image
    import numpy as np
    import torch
    if device is None:
        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    image = Image.open(image_file).convert('RGB')
    orig_w, orig_h = image.size
    preprocess = transforms.Compose([
        transforms.Resize((512, 512)),
        transforms.ToTensor(),
    ])
    input_tensor = preprocess(image).unsqueeze(0).to(device)
    with torch.no_grad():
        output = model(input_tensor)
    pellet_count = float(output.sum().item())
    peaks = _find_density_peaks(output, min_distance=2, threshold_factor=0.5)
    # Scale from density map (e.g. 64x64) to 512x512 then to original size
    dm_h, dm_w = output.shape[2], output.shape[3]
    scale_x = orig_w / dm_w
    scale_y = orig_h / dm_h
    positions = []
    for py, px in peaks:
        x = int(px * scale_x)
        y = int(py * scale_y)
        positions.append((x, y))
    return pellet_count, positions


def annotate_image_with_pellets(image_path, positions, dot_radius=4, dot_color=(255, 0, 0)):
    """
    Draw red dots at pellet positions on the image. Returns PIL Image.
    """
    from PIL import Image, ImageDraw
    img = Image.open(image_path).convert('RGB')
    draw = ImageDraw.Draw(img)
    for x, y in positions:
        r = dot_radius
        draw.ellipse([x - r, y - r, x + r, y + r], fill=dot_color, outline=dot_color)
    return img

def get_feed_ratio():
    if not os.path.exists(CONFIG_PATH):
        return {'pellets': 150, 'grams': 6.0, 'grams_per_second': 2.0}
    with open(CONFIG_PATH, 'r') as f:
        data = json.load(f)
    if 'grams_per_second' not in data:
        data['grams_per_second'] = 2.0
    return data

def set_feed_ratio(pellets, grams, grams_per_second=None):
    existing = get_feed_ratio()
    if grams_per_second is None:
        grams_per_second = existing.get('grams_per_second', 2.0)
    with open(CONFIG_PATH, 'w') as f:
        json.dump({
            'pellets': pellets,
            'grams': grams,
            'grams_per_second': grams_per_second
        }, f)
