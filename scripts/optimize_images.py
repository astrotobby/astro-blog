"""
Optimize all oversized images in public/ to be under 500KB.
Uses PIL to resize and compress while maintaining aspect ratio.
"""
from PIL import Image
import os
import sys

BUDGET = 500 * 1024  # 500KB
PUBLIC_DIR = os.path.join(os.path.dirname(__file__), '..', 'public')
QUALITY_STEPS = [80, 70, 60, 50]
MAX_DIM = 2048  # max dimension for photos

def find_oversized(directory):
    """Find all images over the budget."""
    oversized = []
    for root, dirs, files in os.walk(directory):
        for f in files:
            if f.lower().endswith(('.png', '.jpg', '.jpeg')):
                path = os.path.join(root, f)
                size = os.path.getsize(path)
                if size > BUDGET:
                    oversized.append((path, size))
    return oversized

def optimize_image(path, original_size):
    """Try to get the image under budget by scaling down and compressing."""
    print(f"  {os.path.basename(path)}: {(original_size/1024):.0f}KB -> ", end='')
    
    img = Image.open(path)
    
    # For PNGs, convert to JPG (much smaller) unless it has alpha
    is_png = path.lower().endswith('.png')
    
    if is_png and img.mode == 'RGBA':
        # Keep as PNG but reduce size - resize first
        w, h = img.size
        max_side = max(w, h)
        if max_side > MAX_DIM:
            ratio = MAX_DIM / max_side
            img = img.resize((int(w*ratio), int(h*ratio)), Image.LANCZOS)
        img.save(path, "PNG", optimize=True)
    elif is_png:
        # PNG without alpha -> convert to JPG for massive savings
        img = img.convert('RGB')
        new_path = path[:-4] + '.jpg'
        # Save as JPG
        for q in QUALITY_STEPS:
            img.save(new_path, "JPEG", quality=q, optimize=True)
            if os.path.getsize(new_path) <= BUDGET:
                os.remove(path)  # remove old PNG
                size_kb = os.path.getsize(new_path) / 1024
                print(f"{size_kb:.0f}KB (converted PNG->JPG, q={q})")
                return True, new_path
        # Even at q=50 it's too big, resize further
        w, h = img.size
        while max(w, h) > 800 and os.path.getsize(new_path) > BUDGET:
            ratio = 0.8
            img = img.resize((int(w*ratio), int(h*ratio)), Image.LANCZOS)
            w, h = img.size
            img.save(new_path, "JPEG", quality=50, optimize=True)
        size_kb = os.path.getsize(new_path) / 1024
        os.remove(path)
        print(f"{size_kb:.0f}KB (converted PNG->JPG, resized)")
        return True, new_path
    else:
        # JPG - just compress and resize
        for q in QUALITY_STEPS:
            w, h = img.size
            max_side = max(w, h)
            if max_side > MAX_DIM:
                ratio = MAX_DIM / max_side
                img = img.resize((int(w*ratio), int(h*ratio)), Image.LANCZOS)
            img.save(path, "JPEG", quality=q, optimize=True)
            if os.path.getsize(path) <= BUDGET:
                size_kb = os.path.getsize(path) / 1024
                print(f"{size_kb:.0f}KB (q={q})")
                return True, path
        # Last resort: keep shrinking
        img = Image.open(path)
        w, h = img.size
        while os.path.getsize(path) > BUDGET and max(w, h) > 400:
            ratio = 0.75
            img = img.resize((int(w*ratio), int(h*ratio)), Image.LANCZOS)
            w, h = img.size
            img.save(path, "JPEG", quality=40, optimize=True)
        size_kb = os.path.getsize(path) / 1024
        print(f"{size_kb:.0f}KB (resized aggressively)")
        return True, path

def main():
    oversized = find_oversized(PUBLIC_DIR)
    if not oversized:
        print("All public/ images are within the 500KB budget.")
        return 0
    
    print(f"Found {len(oversized)} oversized images:")
    for path, size in oversized:
        print(f"  OVER: {path} ({size/1024:.0f}KB)")
    print()
    
    fixed = 0
    failed = 0
    for path, size in oversized:
        try:
            success, new_path = optimize_image(path, size)
            if success:
                fixed += 1
                # If we converted PNG->JPG, update any frontmatter references
                if new_path != path:
                    old_name = os.path.basename(path)
                    new_name = os.path.basename(new_path)
                    print(f"    NOTE: {old_name} -> {new_name}")
            else:
                failed += 1
        except Exception as e:
            print(f"ERROR: {e}")
            failed += 1
    
    print(f"\nDone: {fixed} fixed, {failed} failed")
    return 0 if failed == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
