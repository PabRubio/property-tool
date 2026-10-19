"""Photo roles, including compatibility with older records that stored upload order only."""
import io
from PIL import Image, ImageOps

MAX_IMAGE_BYTES = 10 * 1024 * 1024


def photo_groups(record):
    cover, gallery = None, []
    for index, photo in enumerate(record.get('photos', [])):
        role = photo.get('role', 'cover' if index == 0 else 'gallery')
        if role == 'cover' and cover is None:
            cover = photo
        else:
            gallery.append(photo)
    return cover, gallery


def prepare_image(file):
    raw = file.read(MAX_IMAGE_BYTES + 1)
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError('Each photo must be 10 MB or smaller')
    try:
        with Image.open(io.BytesIO(raw)) as original:
            if original.format not in ('JPEG', 'PNG', 'WEBP') or original.width * original.height > 25000000:
                raise ValueError('Invalid image format or dimensions')
            if getattr(original, 'is_animated', False):
                raise ValueError('Animated images are not supported')
            original.load()
            image = ImageOps.exif_transpose(original).convert('RGB')
            image.thumbnail((2000, 2000))
            output = io.BytesIO()
            image.save(output, 'JPEG', quality=90)
            return output.getvalue()
    except Exception:
        raise ValueError('Use a valid JPEG, PNG or WebP photo under 25 megapixels')
