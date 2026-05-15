---
name: "image-transparency"
description: "Use when the user asks to remove a white/grey background from an image, logo, or signature to make it transparent, using NumPy and Pillow."
---

# Image Transparency Skill (Background Removal)

Removes solid backgrounds (like white paper from a scanned signature or white backgrounds from logos) and converts them to a transparent PNG.

## When to use
- The user provides an image with a solid or grey/white background and needs it transparent.
- Adapting signatures or logos for documents (PDFs, watermarks) where the background interferes with the layout.

## Workflow
1. Use Python with `Pillow` and `NumPy` to evaluate image threshold.
2. Mask pixels above the light threshold (background) and set their Alpha channel to 0.
3. Normalize ink/foreground pixels to a solid color if needed (e.g. ink blue `#1a1a2e` or pure black `#000000`).
4. Save as a new `_transparent.png` file or overwrite if requested.

## Code Example (Python)
```python
from PIL import Image
import numpy as np

def make_transparent(input_path, output_path, threshold=180, fg_color=None):
    img = Image.open(input_path).convert('RGBA')
    arr = np.array(img)
    
    # Convert to grayscale to find dark vs light
    gray = Image.open(input_path).convert('L')
    gray_arr = np.array(gray)
    
    # Background mask (light areas)
    bg_mask = gray_arr >= threshold
    arr[bg_mask, 3] = 0 # Set alpha to 0 completely transparent
    
    # Foreground mask (dark areas)
    if fg_color:
        ink_mask = gray_arr < threshold
        arr[ink_mask, 0] = fg_color[0]
        arr[ink_mask, 1] = fg_color[1]
        arr[ink_mask, 2] = fg_color[2]
        
    out_img = Image.fromarray(arr)
    out_img.save(output_path)
    print(f"Saved transparent image to {output_path}")

# make_transparent('firma.png', 'firma_trans.png', fg_color=(26, 26, 46))
```

*Note on "nano banana": Historically triggered by dictation typos for "una nueva [skill]". This skill embodies that rule for simple scripted transparency!*
