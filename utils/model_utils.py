import torch
from torchvision import transforms
from PIL import Image, ImageEnhance
import json
import os

MODEL_PATH = os.path.join(os.path.dirname(__file__), '..', 'models', 'feed_count_model.pth')
CONFIG_PATH = os.path.join(os.path.dirname(__file__), '..', 'config.json')

_model = None

# Preprocessing to reduce undercounting: mild contrast helps faint pellets stand out from feeder.
# Tune in config.json: "contrast_factor" (default 1.15), "sharpness_factor" (default 1.0).
# If the model still undercounts: try contrast_factor 1.2–1.3; add more training images that
# match your feeder/camera and fine-tune; ensure pellets are in focus and well lit.
DEFAULT_CONTRAST_FACTOR = 1.15
DEFAULT_SHARPNESS_FACTOR = 1.0

# Default crop margins (fractions of width/height) to remove hardware/borders so that
# only the feed area (white background) is used. These can be overridden in config.json
# via crop_top_pct, crop_bottom_pct, crop_left_pct, crop_right_pct.
# Top/bottom are a bit larger to trim the tray and upper bar.
DEFAULT_CROP_TOP_PCT = 0.06
DEFAULT_CROP_BOTTOM_PCT = 0.16
DEFAULT_CROP_LEFT_PCT = 0.04
DEFAULT_CROP_RIGHT_PCT = 0.04


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


def _get_preprocess_factors():
    """Read optional contrast/sharpen factors from config to reduce undercounting."""
    try:
        cfg = get_feed_ratio()
        contrast = float(cfg.get('contrast_factor', DEFAULT_CONTRAST_FACTOR))
        sharpness = float(cfg.get('sharpness_factor', DEFAULT_SHARPNESS_FACTOR))
        return contrast, sharpness
    except Exception:
        return DEFAULT_CONTRAST_FACTOR, DEFAULT_SHARPNESS_FACTOR


def _get_crop_margins():
    """
    Read optional crop percentages from config so we can restrict the model and
    annotated images to the main white background area (hiding tray/edges).
    """
    try:
        cfg = get_feed_ratio()
        top = float(cfg.get('crop_top_pct', DEFAULT_CROP_TOP_PCT))
        bottom = float(cfg.get('crop_bottom_pct', DEFAULT_CROP_BOTTOM_PCT))
        left = float(cfg.get('crop_left_pct', DEFAULT_CROP_LEFT_PCT))
        right = float(cfg.get('crop_right_pct', DEFAULT_CROP_RIGHT_PCT))
    except Exception:
        top = DEFAULT_CROP_TOP_PCT
        bottom = DEFAULT_CROP_BOTTOM_PCT
        left = DEFAULT_CROP_LEFT_PCT
        right = DEFAULT_CROP_RIGHT_PCT

    # Clamp to reasonable range and ensure we don't crop everything
    top = max(0.0, min(0.4, top))
    bottom = max(0.0, min(0.4, bottom))
    left = max(0.0, min(0.4, left))
    right = max(0.0, min(0.4, right))
    if top + bottom >= 0.9 or left + right >= 0.9:
        # Fallback to safe defaults
        top, bottom, left, right = (
            DEFAULT_CROP_TOP_PCT,
            DEFAULT_CROP_BOTTOM_PCT,
            DEFAULT_CROP_LEFT_PCT,
            DEFAULT_CROP_RIGHT_PCT,
        )
    return top, bottom, left, right


def _crop_to_feed_region(image: Image.Image) -> Image.Image:
    """
    Crop the image so that mainly the feed area (white background) is visible,
    trimming away the tray at the bottom and hardware at the top.
    """
    top_pct, bottom_pct, left_pct, right_pct = _get_crop_margins()
    w, h = image.size
    left = int(w * left_pct)
    right = int(w * (1.0 - right_pct))
    top = int(h * top_pct)
    bottom = int(h * (1.0 - bottom_pct))
    # Ensure valid box
    if right <= left or bottom <= top:
        return image
    return image.crop((left, top, right, bottom))


def _prepare_image_for_model(image_file):
    """
    Load image and apply optional enhancement to improve detection of faint or
    low-contrast pellets (reduces undercounting). Returns PIL Image in RGB.
    """
    image = Image.open(image_file).convert('RGB')
    contrast_factor, sharpness_factor = _get_preprocess_factors()
    if contrast_factor != 1.0:
        image = ImageEnhance.Contrast(image).enhance(contrast_factor)
    if sharpness_factor != 1.0:
        image = ImageEnhance.Sharpness(image).enhance(sharpness_factor)
    image = _crop_to_feed_region(image)
    return image


# Predict pellet count using the actual model output (sum of density map)
def predict_pellets(model, image_file, device=None):
    from PIL import Image
    import numpy as np
    import torch
    if device is None:
        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    image = _prepare_image_for_model(image_file)
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


def _find_top_k_density_positions(density_map, k, min_distance=3, border_margin=0.05):
    """
    Select up to k positions with highest density value, enforcing minimum distance
    between them (non-maximum suppression). If that yields fewer than k peaks,
    we fill the remainder without the distance constraint so that the number of
    dots matches the reported pellet count. Returns list of (y, x, value) in
    density map coords.
    """
    import numpy as np
    if hasattr(density_map, 'cpu'):
        arr = density_map.squeeze().cpu().numpy()
    else:
        arr = np.asarray(density_map).squeeze()
    if arr.ndim > 2:
        arr = arr[0]
    h, w = arr.shape
    if arr.size == 0 or k <= 0:
        return []

    margin_h = max(0, int(h * border_margin))
    margin_w = max(0, int(w * border_margin))
    y_lo, y_hi = margin_h, h - margin_h
    x_lo, x_hi = margin_w, w - margin_w
    if y_hi <= y_lo or x_hi <= x_lo:
        return []

    positions_with_val = []
    for i in range(y_lo, y_hi):
        for j in range(x_lo, x_hi):
            v = float(arr[i, j])
            if v > 0:
                positions_with_val.append((i, j, v))
    positions_with_val.sort(key=lambda p: p[2], reverse=True)

    chosen = []
    md_sq = min_distance * min_distance

    # First pass: enforce minimum distance so dots are not too crowded.
    for (oy, ox, v) in positions_with_val:
        if len(chosen) >= k:
            break
        too_close = False
        for (cy, cx, _) in chosen:
            if (oy - cy) ** 2 + (ox - cx) ** 2 < md_sq:
                too_close = True
                break
        if not too_close:
            chosen.append((oy, ox, v))

    # Second pass: if we still have fewer than k, allow closer points so that
    # the number of dots matches the pellet count reported by the density sum.
    if len(chosen) < k:
        for (oy, ox, v) in positions_with_val:
            if len(chosen) >= k:
                break
            # Skip if this exact coordinate is already chosen.
            if any((oy == cy and ox == cx) for (cy, cx, _) in chosen):
                continue
            chosen.append((oy, ox, v))

    return chosen


def predict_pellets_with_positions(model, image_file, device=None):
    """
    Returns (count, positions) where positions is list of (x, y) in original image coords.
    """
    from PIL import Image
    import numpy as np
    import torch
    if device is None:
        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    image = _prepare_image_for_model(image_file)
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
    peaks = _find_top_k_density_positions(
        output,
        k=expected_count,
        min_distance=2,
        border_margin=0.05,
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
    # Apply the same crop used during model prediction so that only the
    # white feed area is shown and pellet positions line up.
    img = _crop_to_feed_region(img)
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
