import base64
import binascii
from io import BytesIO
import time
from PIL import Image, ImageDraw, UnidentifiedImageError


def validate_image(encoded):
    if encoded is None:
        return None
    try:
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) > 2_000_000:
            raise ValueError('image exceeds 2 MB')
        with Image.open(BytesIO(raw)) as image:
            if image.format != 'JPEG' or max(image.size) > 2048 or image.width * image.height > 3_000_000:
                raise ValueError('require JPEG <=2048px and <=3 million pixels')
            image.verify()
        return raw
    except (binascii.Error, UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise ValueError('invalid JPEG image') from error


def compress(image, width=640, quality=75):
    if not 64 <= width <= 2048 or not 10 <= quality <= 95:
        raise ValueError('invalid compression settings')
    image = image.copy().convert('RGB')
    image.thumbnail((width, width))
    buffer = BytesIO()
    image.save(buffer, format='JPEG', quality=quality)
    return buffer.getvalue()


def synthetic_frame():
    """Clearly labelled drawing; used for protocol/compression tests only."""
    image = Image.new('RGB', (960, 540), '#b6d0dd')
    drawing = ImageDraw.Draw(image)
    drawing.rectangle((0, 300, 960, 540), fill='#555c66')
    for x in range(0, 960, 140):
        drawing.rectangle((x, 430, x + 70, 439), fill='white')
    drawing.rectangle((280, 320, 530, 410), fill='#df8051')
    drawing.ellipse((310, 390, 355, 435), fill='black')
    drawing.ellipse((455, 390, 500, 435), fill='black')
    drawing.text((25, 25), 'SYNTHETIC FIXTURE - NOT REAL ROAD DATA', fill='black')
    return image


def scene_rules(detections):
    people = sum(x.label.lower() == 'person' and x.confidence >= .65 for x in detections)
    vehicles = sum(x.label.lower() in {'car', 'truck', 'bus', 'motorcycle'} and x.confidence >= .5 for x in detections)
    return {'people': people, 'vehicles': vehicles,
            'priority': 'review' if people else 'normal',
            'suggested_tool': 'request_human_review' if people else 'record_scene',
            'interpretation': 'metadata rule only; no collision prediction or vehicle control'}
