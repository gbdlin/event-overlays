import argparse
import logging
from functools import partial

import tqdm

from html2image import Html2Image
from PIL import Image
from pyatem.command import TimeRequestCommand
from pyatem.media import rgb_to_atem
from pyatem.protocol import AtemProtocol

# logging.basicConfig(level=logging.DEBUG)
atem_log = logging.getLogger('AtemProtocol')
# atem_log.level = logging.DEBUG

pbar = None


def prepare_image(scene_url, path, resolution):
    hti = Html2Image(
        size=resolution,
        browser_executable="/home/gwynbleidd/.local/bin/chromium",
        custom_flags=['--virtual-time-budget=5000', '--hide-scrollbars'],
    )

    hti.screenshot(url=scene_url, save_as=path)

    im = Image.open(path)
    frame = Image.new('RGBA', resolution)
    im.thumbnail(resolution, Image.Resampling.LANCZOS)
    frame.paste(im)
    pixels = frame.getdata()

    flat = [item for sublist in pixels for item in sublist]
    return bytes(flat)


def connected(*, connection, slot, scene_url, name):
    if not isinstance(connection, AtemProtocol):
        raise ValueError()

    product = connection.mixerstate['product-name']
    slots = connection.mixerstate['mediaplayer-slots']
    mode = connection.mixerstate['video-mode']
    resolution = mode.get_resolution()

    logging.info(f'Connected to {product.name} at {mode.get_label()}')

    if slot < 0 or slot >= slots.stills:
        logging.fatal(f'Slot index out of range, This hardware supports slot 1-{slots.stills}')
        exit(1)

    frame = prepare_image(scene_url, "schedule.png", resolution)
    connection.send_commands([TimeRequestCommand()])
    logging.basicConfig(level=logging.DEBUG)
    frame_atem = rgb_to_atem(frame, *mode.get_resolution())
    connection.upload(0, slot, frame_atem, name=name, compress=True)


def uploaded(store, slot):
    logging.info("Upload completed")
    exit(0)


def progress(store, slot, factor):
    print(factor * 100)


def upload_progress(store, slot, percent, done, size):
    global pbar
    if pbar is None:
        pbar = tqdm.tqdm(total=size, unit='B', unit_scale=True)
        pbar.last_done = 0
    block = done - pbar.last_done
    pbar.update(block)
    pbar.last_done = done
    if done == size:
        pbar.close()


def disconnected(*args, **kwargs):
    print("disconnected", args, kwargs)
    logging.fatal("disconnected")
    exit(1)


parser = argparse.ArgumentParser()
parser.add_argument('ip', help='ATEM IP address')
parser.add_argument('index', help='Media store slot number', type=int)
parser.add_argument('scene_url', help='Scene URL')
parser.add_argument('name', help='Still name')

args = parser.parse_args()


switcher = AtemProtocol(args.ip)

switcher.on(
    'connected',
    partial(connected, connection=switcher, slot=args.index - 1, scene_url=args.scene_url, name=args.name)
)
switcher.on('disconnected', disconnected)
switcher.on('upload-done', uploaded)
switcher.on('transfer-progress', progress)
switcher.on('upload-progress', upload_progress)

switcher.connect()
while True:
    switcher.loop()
