from __future__ import annotations

import base64
import io
import logging
from typing import Any, Dict, List, Optional, Tuple
import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


def load_image_cv(image_path: str) -> np.ndarray:
    """Load image from disk into OpenCV BGR numpy array."""
    img = cv2.imread(image_path, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"Could not read image file at {image_path}")
    return img


def run_otsu_threshold(
    image_path: str,
    roi_bbox: Optional[List[int]] = None,
    invert: bool = True,
    blur_kernel: int = 3,
    morphology_close: int = 2,
    remove_small_speckles: int = 15,
) -> Dict[str, Any]:
    """
    Run Otsu thresholding on a micrograph (or ROI) specifically designed
    for dark hydride platelets in metallic microstructures.
    """
    img = load_image_cv(image_path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape

    # Apply ROI if specified
    x0, y0, rw, rh = 0, 0, w, h
    if roi_bbox and len(roi_bbox) == 4:
        bx, by, bw, bh = roi_bbox
        x0 = max(0, min(bx, w - 1))
        y0 = max(0, min(by, h - 1))
        rw = max(1, min(bw, w - x0))
        rh = max(1, min(bh, h - y0))
        roi_gray = gray[y0 : y0 + rh, x0 : x0 + rw]
    else:
        roi_gray = gray

    # Optional blur
    if blur_kernel > 1:
        k = blur_kernel if blur_kernel % 2 == 1 else blur_kernel + 1
        roi_blurred = cv2.GaussianBlur(roi_gray, (k, k), 0)
    else:
        roi_blurred = roi_gray

    # Otsu thresholding
    thresh_type = cv2.THRESH_BINARY_INV if invert else cv2.THRESH_BINARY
    thresh_val, bin_roi = cv2.threshold(roi_blurred, 0, 255, thresh_type + cv2.THRESH_OTSU)

    # Morphological closing
    if morphology_close > 0:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (morphology_close * 2 + 1, morphology_close * 2 + 1))
        bin_roi = cv2.morphologyEx(bin_roi, cv2.MORPH_CLOSE, kernel)

    # Remove small speckles using connected components
    if remove_small_speckles > 0:
        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(bin_roi, connectivity=8)
        cleaned_bin = np.zeros_like(bin_roi)
        for i in range(1, num_labels):
            if stats[i, cv2.CC_STAT_AREA] >= remove_small_speckles:
                cleaned_bin[labels == i] = 255
        bin_roi = cleaned_bin

    # Construct full canvas mask
    full_mask = np.zeros((h, w), dtype=np.uint8)
    full_mask[y0 : y0 + rh, x0 : x0 + rw] = bin_roi

    # Find contours
    contours, _ = cv2.findContours(full_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contour_list = []
    for c in contours:
        # Simplify contour to keep reasonable polygon point count
        epsilon = 0.003 * cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, epsilon, True)
        if len(approx) >= 3:
            pts = approx.reshape(-1, 2).tolist()
            contour_list.append(pts)

    feature_count = len(contour_list)
    area_fraction = float(np.count_nonzero(full_mask)) / float(h * w)

    # Encode mask to PNG base64
    success, buffer = cv2.imencode(".png", full_mask)
    mask_b64 = base64.b64encode(buffer).decode("utf-8") if success else ""

    return {
        "threshold_value": float(thresh_val),
        "contours": contour_list,
        "mask_png_base64": f"data:image/png;base64,{mask_b64}",
        "feature_count": feature_count,
        "area_fraction": round(area_fraction, 4),
    }


def run_adaptive_threshold(
    image_path: str,
    roi_bbox: Optional[List[int]] = None,
    block_size: int = 15,
    c_constant: int = 5,
    invert: bool = True,
    morphology_close: int = 2,
    remove_small_speckles: int = 15,
) -> Dict[str, Any]:
    img = load_image_cv(image_path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape

    x0, y0, rw, rh = 0, 0, w, h
    if roi_bbox and len(roi_bbox) == 4:
        bx, by, bw, bh = roi_bbox
        x0 = max(0, min(bx, w - 1))
        y0 = max(0, min(by, h - 1))
        rw = max(1, min(bw, w - x0))
        rh = max(1, min(bh, h - y0))
        roi_gray = gray[y0 : y0 + rh, x0 : x0 + rw]
    else:
        roi_gray = gray

    bs = block_size if block_size % 2 == 1 else block_size + 1
    thresh_type = cv2.THRESH_BINARY_INV if invert else cv2.THRESH_BINARY
    bin_roi = cv2.adaptiveThreshold(
        roi_gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, thresh_type, bs, c_constant
    )

    if morphology_close > 0:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (morphology_close * 2 + 1, morphology_close * 2 + 1))
        bin_roi = cv2.morphologyEx(bin_roi, cv2.MORPH_CLOSE, kernel)

    if remove_small_speckles > 0:
        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(bin_roi, connectivity=8)
        cleaned_bin = np.zeros_like(bin_roi)
        for i in range(1, num_labels):
            if stats[i, cv2.CC_STAT_AREA] >= remove_small_speckles:
                cleaned_bin[labels == i] = 255
        bin_roi = cleaned_bin

    full_mask = np.zeros((h, w), dtype=np.uint8)
    full_mask[y0 : y0 + rh, x0 : x0 + rw] = bin_roi

    contours, _ = cv2.findContours(full_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contour_list = []
    for c in contours:
        epsilon = 0.003 * cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, epsilon, True)
        if len(approx) >= 3:
            contour_list.append(approx.reshape(-1, 2).tolist())

    feature_count = len(contour_list)
    area_fraction = float(np.count_nonzero(full_mask)) / float(h * w)

    success, buffer = cv2.imencode(".png", full_mask)
    mask_b64 = base64.b64encode(buffer).decode("utf-8") if success else ""

    return {
        "threshold_value": 0.0,
        "contours": contour_list,
        "mask_png_base64": f"data:image/png;base64,{mask_b64}",
        "feature_count": feature_count,
        "area_fraction": round(area_fraction, 4),
    }


def rasterize_shapes_to_mask(
    shapes: List[Dict[str, Any]],
    width: int,
    height: int,
    output_mode: str = "multiclass",
    target_class: int = 1,
) -> np.ndarray:
    """
    Rasterize vector shapes to an 8-bit numpy mask.
    output_mode:
      - 'multiclass': mask pixel values = shape['class_index'] (0 for background)
      - 'binary': mask pixel values = 255 if shape matches target_class else 0
      - 'rgb_red_dominant': 3-channel BGR where hydride is Red (B=0, G=0, R=255)
    """
    if output_mode == "rgb_red_dominant":
        mask = np.zeros((height, width, 3), dtype=np.uint8)
    else:
        mask = np.zeros((height, width), dtype=np.uint8)

    for shape in shapes:
        shape_type = shape.get("type", "polygon")
        class_idx = int(shape.get("class_index", 1))
        points = shape.get("points", [])
        if not points:
            continue

        pts_array = np.array(points, dtype=np.int32)

        # Determine fill value
        if output_mode == "binary":
            fill_val = 255 if class_idx == target_class else 0
        elif output_mode == "rgb_red_dominant":
            fill_val = (0, 0, 255) if class_idx == target_class else (0, 255, 0)
        else:  # multiclass
            fill_val = class_idx

        if shape_type == "polygon":
            if len(pts_array) >= 3:
                cv2.fillPoly(mask, [pts_array], fill_val)
        elif shape_type == "brush_stroke":
            radius = int(shape.get("brush_size", 10))
            for i in range(len(pts_array) - 1):
                p1 = tuple(pts_array[i])
                p2 = tuple(pts_array[i + 1])
                cv2.line(mask, p1, p2, fill_val, thickness=radius * 2)
                cv2.circle(mask, p1, radius, fill_val, -1)
            if len(pts_array) > 0:
                cv2.circle(mask, tuple(pts_array[-1]), radius, fill_val, -1)
        elif shape_type == "rectangle":
            if len(pts_array) >= 2:
                p1 = tuple(pts_array[0])
                p2 = tuple(pts_array[1])
                cv2.rectangle(mask, p1, p2, fill_val, -1)

    return mask


def save_b64_mask_to_file(b64_data: str, destination_path: str) -> None:
    """Decode base64 PNG data and write directly to image file."""
    if "," in b64_data:
        b64_data = b64_data.split(",", 1)[1]
    raw_bytes = base64.b64decode(b64_data)
    with open(destination_path, "wb") as f:
        f.write(raw_bytes)
