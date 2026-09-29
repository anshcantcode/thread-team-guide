"""Render an offline, explicitly edited participant-trace replay; never run an agent.

Pillow makes readable cards; FFmpeg encodes the cards and original input audio.
The private cut JSON supplies captions and exact JSON-pointer evidence excerpts.
See docs/submission-2026-09-23/PARTICIPANT_DEMO_RENDERER.md.
"""
import argparse
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import wave

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
WIDTH, HEIGHT, FPS, SAMPLE_RATE = 1600, 900, 10, 48000
PAPER, INK, MUTED = '#f4f7fb', '#101b2b', '#526179'
BLUE, GREEN = '#2456d8', '#166449'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def pointer(value, path):
    for part in path.lstrip('/').split('/') if path else []:
        key = part.replace('~1', '/').replace('~0', '~')
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def value_at(ref, sources):
    name, path = ref.split('#', 1)
    return pointer(sources[name], path)


def display(value):
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def run(argv, **kwargs):
    return subprocess.run(argv, check=True, **kwargs)


def probe(path):
    return json.loads(run(['ffprobe', '-v', 'error', '-show_format', '-show_streams',
                           '-of', 'json', str(path)], capture_output=True, text=True).stdout)


def checked_child(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f'Path leaves source directory: {relative}')
    return path


@lru_cache(maxsize=24)
def font(size, bold=False):
    f = ImageFont.truetype(str(ROOT / 'web/fonts/Manrope.ttf'), size)
    f.set_variation_by_axes([700 if bold else 450])
    return f


def lines(text, size, width, bold=False):
    result = []
    for paragraph in str(text).split('\n'):
        current = ''
        for word in paragraph.split(' '):
            proposed = (current + ' ' + word).strip()
            if font(size, bold).getlength(proposed) > width and current:
                result.append(current)
                current = word
            else:
                current = proposed
            if font(size, bold).getlength(current) > width:
                raise ValueError(f'Unbreakable line is too wide: {current}')
        result.append(current)
    return result


def text(draw, value, x, y, size, width, fill=INK, bold=False):
    for line in lines(value, size, width, bold):
        draw.text((x, y), line, font=font(size, bold), fill=fill)
        y += round(size * 1.36)
    return y


def render_card(card, identity, out):
    canvas = Image.new('RGB', (WIDTH, HEIGHT), PAPER)
    d = ImageDraw.Draw(canvas)
    d.rectangle((0, 0, WIDTH, 72), fill=INK)
    d.text((48, 20), 'THREAD  /  PARTICIPANT EVIDENCE', font=font(22, True), fill='white')
    d.text((1015, 20), 'RECORDED REPLAY  ·  MOCK TOOLS', font=font(22, True), fill='#aee4ce')
    d.text((48, 100), card['section'].upper(), font=font(21, True), fill=BLUE)
    title_end = text(d, card['title'], 48, 137, 45, 1504, bold=True)
    if title_end > 211:
        raise ValueError(f'Title overflows: {card["title"]}')
    width = 1456
    if card.get('image'):
        picture = Image.open(out / card['image']).convert('RGB')
        picture = ImageOps.contain(picture, (825, 460))
        canvas.paste(picture, (48, 227))
        x, width = 920, 600
    else:
        x = 64
        d.rounded_rectangle((48, 220, 1552, 690), radius=18, fill='white')
    y = 239
    for block in card['resolved_blocks']:
        label = block['label']
        if 't_ms' in block:
            label += f'   ·   TRACE {block["t_ms"]:.1f} ms'
        y = text(d, label, x, y, 19, width, BLUE, True) + 7
        y = text(d, block['text'], x, y, block.get('size', 29), width) + 20
    if y > (725 if card.get('image') else 684):
        raise ValueError(f'Content overflows ({y}px): {card["title"]}')
    if card.get('note'):
        y = text(d, 'EXPLANATION  ' + card['note'], 48, 715, 23, 1504, GREEN)
        if y > 810:
            raise ValueError(f'Explanation overflows: {card["title"]}')
    d.line((48, 820, 1552, 820), fill='#cbd4df', width=2)
    d.text((48, 833), 'Edited trace cards · explanation holds · film time is not response time',
           font=font(20), fill=MUTED)
    footer = f'Source {identity["source"][:12]}  ·  Archive {identity["archive"][:12]}  ·  23 Sep 2026'
    d.text((48, 865), footer, font=font(18), fill=MUTED)
    d.text((1290, 865), f'CARD {card["number"]:02d}  /  {card["duration_s"]:g}s hold',
           font=font(18), fill=MUTED)
    canvas.save(out / card['frame'])


def prepare(cut_path, evidence, kit, out):
    cut = read(cut_path)
    out.mkdir(parents=True, exist_ok=False)
    (out / 'sources').mkdir()
    (out / 'media').mkdir()
    (out / 'cards').mkdir()
    review = read(evidence / 'REVIEW.json')
    manifest = read(evidence / 'batch/run/manifest.json')
    index = read(evidence / 'batch/run/evidence-sha256.json')
    if not review['verified'] or sha(evidence / 'REVIEW.json') != cut['review_sha256']:
        raise ValueError('Unverified or changed review receipt')
    if sha(evidence / 'FACTUAL_REVIEW.md') != cut['factual_sha256']:
        raise ValueError('Factual review changed')
    if sha(evidence / 'batch/run/evidence-sha256.json') != review['evidence_index_sha256']:
        raise ValueError('Evidence hash index changed')
    if sha(evidence / 'batch/run/manifest.json') != index['manifest.json']:
        raise ValueError('Run manifest changed')
    identity = {'source': review['participant_source_revision'], 'archive': review['archive_sha256']}
    sources = {'review': review}
    source_files = {}
    for name, relative in {'review': 'REVIEW.json', 'factual': 'FACTUAL_REVIEW.md',
                           'run_manifest': 'batch/run/manifest.json', **cut['sources']}.items():
        path = checked_child(evidence, relative)
        if name not in ('review', 'factual', 'run_manifest') and sha(path) != index[path.name]:
            raise ValueError(f'Changed attempt: {relative}')
        dest = out / 'sources' / path.name
        shutil.copyfile(path, dest)
        source_files[name] = {'path': str(dest.relative_to(out)), 'sha256': sha(path)}
        if path.suffix == '.json':
            sources[name] = read(path)
    for extra in cut.get('related_reviews', []):
        path = Path(extra['path'])
        if sha(path) != extra['sha256']:
            raise ValueError('Related review changed')
        dest = out / 'sources' / (extra['name'] + path.suffix)
        shutil.copyfile(path, dest)
        source_files[extra['name']] = {'path': str(dest.relative_to(out)), 'sha256': sha(path)}
    for name in ('Manrope.ttf', 'Manrope-OFL.txt'):
        path = ROOT / 'web/fonts' / name
        shutil.copyfile(path, out / 'sources' / name)
        source_files[name] = {'path': 'sources/' + name, 'sha256': sha(path)}
    media_files = {}
    def media(relative, source):
        if relative not in media_files:
            path = checked_child(kit, relative)
            digest = sha(path)
            if digest != manifest['fingerprints_before']['submission'][relative]:
                raise ValueError(f'Media does not match the frozen run: {relative}')
            consumed = [item['sha256'] for m in sources[source]['model_evidence']
                        for item in m.get('input_media', [])]
            if digest not in consumed:
                raise ValueError(f'No retained model-input evidence for {relative}')
            dest = out / 'media' / path.name
            shutil.copyfile(path, dest)
            media_files[relative] = {'path': str(dest.relative_to(out)), 'sha256': digest,
                                     'bytes': path.stat().st_size, 'model_input_matched': True}
        return media_files[relative]
    cursor, cards, audio_clips = 0.0, [], []
    for number, raw in enumerate(cut['cards'], 1):
        card = dict(raw, number=number, start_s=cursor, frame=f'cards/{number:02d}.png')
        duration = float(card['duration_s'])
        if duration <= 0 or abs(duration * FPS - round(duration * FPS)) > 1e-6:
            raise ValueError('Card duration must be positive and align with the video frame rate')
        card['resolved_blocks'] = []
        for block in card.get('blocks', []):
            resolved = dict(block)
            resolved['text'] = display(value_at(block['ref'], sources)) if 'ref' in block else block['text']
            if 'time_ref' in block:
                resolved['t_ms'] = float(value_at(block['time_ref'], sources))
            card['resolved_blocks'].append(resolved)
        if card.get('image'):
            card['image'] = media(card['image'], card['media_source'])['path']
        if card.get('audio'):
            asset = media(card['audio'], card['media_source'])
            info = probe(out / asset['path'])
            length = float(info['format']['duration'])
            offset = float(card.get('audio_offset_s', 1))
            if offset < 0 or offset + length > duration:
                raise ValueError('Full original audio must fit inside its card')
            audio_clips.append(dict(asset, start_s=cursor + offset, encoded_duration_s=length,
                                    card=number, speed=1, full_input=True))
        cards.append(card)
        cursor = round(cursor + duration, 3)
        render_card(card, identity, out)
        card['frame_sha256'] = sha(out / card['frame'])
    if not 0 < cursor < 300:
        raise ValueError(f'Film must be below five minutes, got {cursor}')
    result = {'format': 'participant-demo-v1', 'status': 'prepared; not encoded', 'identity': identity,
              'renderer_sha256': sha(__file__), 'cut_sha256': sha(cut_path), 'duration_s': cursor,
              'width': WIDTH, 'height': HEIGHT, 'fps': FPS, 'source_files': source_files,
              'media': media_files, 'audio': audio_clips, 'cards': cards,
              'editing': 'Separate examples; explanation holds; original t_ms retained. Only full input audio at 1x.',
              'audio_provenance': 'Original supplied public-kit recordings; human/synthetic origin unverified.',
              'assistant_audio': False, 'app_screen_capture': False}
    shutil.copyfile(cut_path, out / 'cut.json')
    write(out / 'source-cut-manifest.json', result)
    thumbs = Image.new('RGB', (800, 225 * ((len(cards) + 1) // 2)), 'white')
    for i, card in enumerate(cards):
        with Image.open(out / card['frame']) as frame:
            thumbs.paste(frame.resize((400, 225)), ((i % 2) * 400, (i // 2) * 225))
    thumbs.save(out / 'contact-sheet.jpg')
    print(json.dumps({'prepared': str(out), 'cards': len(cards), 'duration_s': cursor,
                      'audio_clips': len(audio_clips)}, indent=2))


def encode(out):
    manifest = read(out / 'source-cut-manifest.json')
    if sha(__file__) != manifest['renderer_sha256'] or sha(out / 'cut.json') != manifest['cut_sha256']:
        raise ValueError('Renderer or cut changed; prepare a new output directory')
    for asset in [*manifest['source_files'].values(), *manifest['media'].values()]:
        if sha(out / asset['path']) != asset['sha256']:
            raise ValueError('Prepared source or media changed')
    for card in manifest['cards']:
        if sha(out / card['frame']) != card['frame_sha256']:
            raise ValueError('Prepared card changed')
    pcm = bytearray(round(manifest['duration_s'] * SAMPLE_RATE) * 2)
    audio_qa, occupied = [], []
    for clip in manifest['audio']:
        decoded = run(['ffmpeg', '-v', 'error', '-nostdin', '-i', str(out / clip['path']),
                       '-ac', '1', '-ar', str(SAMPLE_RATE), '-f', 's16le', '-'], capture_output=True).stdout
        start = round(clip['start_s'] * SAMPLE_RATE) * 2
        end = start + len(decoded)
        if end > len(pcm) or any(start < previous_end and end > previous_start
                                 for previous_start, previous_end in occupied):
            raise ValueError('Audio overlap or duration overflow')
        occupied.append((start, end))
        pcm[start:end] = decoded
        audio_qa.append({'path': clip['path'], 'start_s': clip['start_s'],
                         'decoded_samples': len(decoded) // 2,
                         'decoded_pcm_sha256': hashlib.sha256(decoded).hexdigest(),
                         'soundtrack_slice_sha256': hashlib.sha256(pcm[start:end]).hexdigest()})
    with wave.open(str(out / 'original-inputs.wav'), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
    concat = ['ffconcat version 1.0']
    for card in manifest['cards']:
        concat += [f"file '{card['frame']}'", f"duration {card['duration_s']}"]
    concat.append(f"file '{manifest['cards'][-1]['frame']}'")
    (out / 'frames.ffconcat').write_text('\n'.join(concat) + '\n', encoding='utf-8')
    command = ['ffmpeg', '-hide_banner', '-loglevel', 'warning', '-nostdin', '-n',
               '-f', 'concat', '-safe', '1', '-i', 'frames.ffconcat', '-i', 'original-inputs.wav',
               '-map', '0:v:0', '-map', '1:a:0', '-vf', f'fps={FPS}',
               '-c:v', 'libx264', '-preset', 'fast', '-tune', 'stillimage', '-crf', '19',
               '-threads', '2', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '128k',
               '-t', str(manifest['duration_s']), '-movflags', '+faststart', 'THREAD-participant-demo.mp4']
    with (out / 'encode.log').open('w', encoding='utf-8') as log:
        run(command, cwd=out, stdout=log, stderr=subprocess.STDOUT)
    video = out / 'THREAD-participant-demo.mp4'
    metadata = probe(video)
    if abs(float(metadata['format']['duration']) - manifest['duration_s']) > .11:
        raise ValueError('Encoded duration mismatch')
    with (out / 'decode-qa.log').open('w', encoding='utf-8') as log:
        run(['ffmpeg', '-v', 'error', '-nostdin', '-threads', '2', '-i', str(video),
             '-f', 'null', '-'], stdout=log, stderr=subprocess.STDOUT)
    write(out / 'media-qa.json', {'ffprobe': metadata, 'full_decode': 'passed',
                                 'input_audio_pcm': audio_qa, 'video_sha256': sha(video),
                                 'subjective_listening': 'not performed by this automated check'})
    manifest.update(status='encoded; visual review required', video_sha256=sha(video),
                    video='THREAD-participant-demo.mp4', encoder_command=command)
    write(out / 'source-cut-manifest.json', manifest)
    print(json.dumps({'video': str(video), 'duration_s': metadata['format']['duration'],
                      'sha256': sha(video)}, indent=2))


def self_test():
    fixture = {'case': {'trace': [{'t_ms': 12.3, 'payload': {'text': 'Original "text".'}}]}}
    assert value_at('case#/trace/0/payload/text', fixture) == 'Original "text".'
    assert value_at('case#/trace/0/t_ms', fixture) == 12.3
    assert pointer({'a/b': {'~x': 7}}, '/a~1b/~0x') == 7
    try:
        value_at('case#/trace/1', fixture)
    except IndexError:
        pass
    else:
        raise AssertionError('Missing trace evidence must fail')
    assert display({'city': 'New York'}) == '{"city": "New York"}'
    print('Self-check passed: exact evidence pointers and missing-evidence rejection.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cut', type=Path)
    parser.add_argument('--evidence', type=Path)
    parser.add_argument('--kit', type=Path)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--encode', action='store_true', help='Encode an already prepared output directory')
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        self_test()
    elif args.encode:
        if args.out is None:
            parser.error('--encode requires --out')
        encode(args.out.resolve())
    else:
        if any(v is None for v in (args.cut, args.evidence, args.kit, args.out)):
            parser.error('prepare requires --cut, --evidence, --kit and a new --out')
        prepare(args.cut.resolve(), args.evidence.resolve(), args.kit.resolve(), args.out.resolve())
