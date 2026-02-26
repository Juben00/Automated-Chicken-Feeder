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


def _find_density_peaks(density_map, min_distance=3, threshold_factor=0.3, border_margin=0.05, max_peaks=None):
    """
    Find local maxima in density map as pellet centers.
    Returns list of (y, x, value) in density map coordinates, sorted by value descending.

    Args:
        density_map: The density map tensor/array from the model.
        min_distance: Minimum pixel distance between peaks.
        threshold_factor: Peaks below this fraction of the max density value are discarded.
        border_margin: Fraction of the map dimensions to exclude at each edge (0.05 = 5%).
        max_peaks: If set, only keep the top N peaks by density value.
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

    max_val = arr.max()
    if max_val <= 0:
        return []

    threshold = max_val * threshold_factor

    margin_h = int(h * border_margin)
    margin_w = int(w * border_margin)
    y_lo, y_hi = margin_h, h - margin_h
    x_lo, x_hi = margin_w, w - margin_w

    md = min_distance
    pad = np.pad(arr, md, mode='constant', constant_values=-np.inf)
    peaks = []
    for i in range(md, h + md):
        for j in range(md, w + md):
            oy, ox = i - md, j - md
            if oy < y_lo or oy >= y_hi or ox < x_lo or ox >= x_hi:
                continue
            v = pad[i, j]
            if v < threshold:
                continue
            window = pad[i - md:i + md + 1, j - md:j + md + 1]
            if v >= window.max():
                peaks.append((oy, ox, float(v)))

    peaks.sort(key=lambda p: p[2], reverse=True)
    if max_peaks is not None and len(peaks) > max_peaks:
        peaks = peaks[:max_peaks]
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

    expected_count = max(1, int(round(pellet_count)))
    peaks = _find_density_peaks(
        output,
        min_distance=3,
        threshold_factor=0.15,
        border_margin=0.05,
        max_peaks=expected_count,
    )

    dm_h, dm_w = output.shape[2], output.shape[3]
    scale_x = orig_w / dm_w
    scale_y = orig_h / dm_h
    positions = []
    for py, px, _val in peaks:
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
