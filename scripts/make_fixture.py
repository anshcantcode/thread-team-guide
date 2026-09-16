"""Render a clearly labelled, code-defined device diagram for the multimodal demo."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

root = Path(__file__).resolve().parent.parent
im = Image.new('RGB', (1040, 640), '#e8eee3')
d = ImageDraw.Draw(im)
font_path = 'C:/Windows/Fonts/segoeui.ttf'
font = lambda size: ImageFont.truetype(font_path, size)
d.text((60, 35), 'THREAD / DEVICE LAB', font=font(24), fill='#46604a')
d.text((60, 77), 'Fictional demonstration fixture — not a real manufacturer device', font=font(19), fill='#687a65')
d.rounded_rectangle((110, 190, 930, 485), radius=38, fill='#fbfcf8', outline='#adbaa7', width=3)
d.rounded_rectangle((220, 462, 360, 500), radius=8, fill='#62715e')
d.rounded_rectangle((680, 462, 820, 500), radius=8, fill='#62715e')
d.text((159, 220), 'THREAD R1', font=font(32), fill='#2e4836')
d.text((160, 270), 'DEMO ROUTER', font=font(17), fill='#83917b')
for x in range(165, 405, 15):
    d.line((x, 371, x, 419), fill='#dce3d5', width=5)
d.text((490, 252), 'NETWORK', font=font(23), fill='#3e5942')
d.ellipse((534, 318, 572, 356), fill='#d8a847', outline='#b78934', width=3)
d.text((513, 388), 'indicator', font=font(17), fill='#819274')
d.ellipse((757, 291, 839, 373), fill='#e4eada', outline='#778e6a', width=2)
d.text((780, 304), '⏻', font=font(38), fill='#4f6f46')
d.ellipse((696, 316, 734, 354), fill='#d8a847', outline='#b78934', width=3)
d.text((709, 391), 'POWER', font=font(21), fill='#3e5942')
d.text((60, 560), 'One still frame. Amber indicators are visible; blinking is not established.', font=font(20), fill='#687a65')
im.save(root / 'web' / 'device-fixture.png')
print('Created web/device-fixture.png (fictional fixture).')
