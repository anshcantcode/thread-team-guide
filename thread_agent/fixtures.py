"""Declared, fictional task environments. No real prices, devices, or transactions."""
from copy import deepcopy

from .protocol import Manifest


def obj(properties, required=()):
    return {'type': 'object', 'properties': properties, 'required': list(required), 'additionalProperties': False}


def text(description, **kw):
    return {'type': 'string', 'description': description, **kw}


DATE = text('Explicit calendar date, YYYY-MM-DD. Resolve relative dates only using session date and timezone.', format='date')
TIME = text('24-hour time HH:MM. An evening nine means 21:00.', pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
NUMBER = {'type': 'integer', 'minimum': 1, 'maximum': 50}
BOOL = {'type': 'boolean'}


def pack(id, title, description, props, required, defaults, read_name, create_name, read_keys=None):
    read_props = {k: props[k] for k in (read_keys or props)}
    tools = [dict(name=read_name, description=f'Look up current sandbox {description} Returns items with stable IDs and evidence.',
                  purpose='lookup', effect='read', parameters=obj(read_props, required))]
    create_props = deepcopy(props)
    create_props['option_id'] = text('Exact ID of a currently applicable returned option, when the lookup offers selectable options.')
    objects = {'travel': ['flight', 'booking', 'reservation'], 'device': ['ticket', 'support ticket'], 'rooms': ['room', 'booking', 'reservation']}
    tools.append(dict(name=create_name, description=f'Create one sandbox {title.lower()} record with these exact details. This changes sandbox state.',
                      authorization_objects=objects.get(id, []),
                      purpose='create', effect='write', parameters=obj(create_props, list(required) + ['option_id'])))
    for purpose, effect in [('status', 'read'), ('cancel', 'write')]:
        tools.append(dict(name=f'{id}.{purpose}', description=f'{"Check the actual outcome of" if purpose == "status" else "Request cancellation of"} an existing sandbox operation. A request is not confirmation.',
                          purpose=purpose, effect=effect, parameters=obj({'operation_id': text('Original submitted call ID.')}, ['operation_id'])))
    return Manifest(id=id, title=title, description=description, slots=obj(props), defaults=defaults, tools=tools).check()


TRAVEL = pack('travel', 'Flights', 'flight availability and mock reservations. No real tickets or payments.', {
    'origin': text('Departure city; canonical name such as Chennai.'),
    'destination': text('Arrival city; preserve repairs and negation.'),
    'date': DATE, 'after': TIME, 'before': TIME,
    'passengers': NUMBER, 'nonstop': BOOL,
    'ranking': text('Ranking preference.', enum=['cheapest', 'earliest']),
    'seat': text('Soft seat preference; unrelated to flight search.', enum=['aisle', 'window', 'any']),
}, ['origin', 'destination', 'date'], {'passengers': 1, 'ranking': 'cheapest'},
    'flights.lookup', 'flights.reserve', ['origin', 'destination', 'date', 'after', 'before', 'passengers', 'nonstop', 'ranking'])

DEVICE = pack('device', 'Device support', 'manual evidence and support tickets for the fictional THREAD R1 demo router.', {
    'model': text('Actual model reported by the user or legible in the current image; only THREAD R1 has a supplied manual.'),
    'indicator': text('Explicitly selected target.', enum=['power', 'network']),
    'symptom': text('User-reported symptoms, e.g. blinking amber. A still image cannot establish blinking.'),
    'context': text('Additional user-reported circumstances; temporal association is not proven causation.'),
}, ['model', 'indicator'], {}, 'manual.retrieve', 'support.create_ticket', ['model', 'indicator'])

ROOMS = pack('rooms', 'Meeting rooms', 'meeting-room availability and mock room reservations.', {
    'date': DATE, 'after': TIME, 'before': TIME,
    'people': NUMBER, 'duration_minutes': {'type': 'integer', 'minimum': 15, 'maximum': 480},
    'projector': BOOL,
}, ['date', 'after', 'people', 'duration_minutes'], {}, 'spacefinder.availability', 'spacefinder.hold')

DEVICE.frame_slots = ['model', 'indicator']
PACKS = {m.id: m for m in [TRAVEL, DEVICE, ROOMS]}

MANUAL = {
    'title': 'THREAD R1 — fictional demonstration manual',
    'model': 'THREAD R1',
    'sections': {
        'power': {'section': '2.1 · Power indicator', 'page': 2,
                  'text': 'The power indicator is beside the round power button. Solid white means the demo unit is powered. A blinking amber power indicator is the demo startup state. If the user reports that this persists, record a support issue; do not infer a hardware fault from a still image.'},
        'network': {'section': '2.2 · Network indicator', 'page': 3,
                    'text': 'The network indicator is below the NETWORK label. Solid green means the demo network link is established. A blinking amber network indicator is the demo connection setup state. Ask whether the connection completes. A single still frame does not establish blinking or its duration.'}
    }
}


def lookup(domain, args):
    """Every answer derives from the actual current arguments and returned fixture data."""
    if domain == 'travel':
        if args['origin'].lower() == args['destination'].lower():
            return {'items': [], 'source': 'THREAD synthetic flight inventory', 'note': 'Origin and destination are the same.'}
        # Synthetic schedule, deliberately disclosed; no live airline data is consulted.
        schedule = [('18:20', 6200, True, 4), ('20:35', 4800, False, 6),
                    ('21:40', 5300, True, 3), ('22:15', 6100, True, 9)]
        items = []
        for index, (departure, price, nonstop, seats) in enumerate(schedule):
            if args.get('after') and departure <= args['after']: continue
            if args.get('before') and departure >= args['before']: continue
            if args.get('nonstop') and not nonstop: continue
            if args.get('passengers', 1) > seats: continue
            route = f"{args['origin']} → {args['destination']}"
            items.append({'id': f"SIM-{args['destination'][:3].upper()}-{index+1}-{args['date']}",
                          'kind': 'flight', 'airline': ['Aster Air', 'Sora', 'Aster Air', 'Kite Airways'][index],
                          'airline_code': ['AS', 'SO', 'AS', 'KA'][index], 'flight_number': f'TH {210 + index * 37}',
                          'title': f'{route} · {departure}', 'departure': departure,
                          'date': args['date'], 'origin': args['origin'], 'destination': args['destination'],
                          'price': price * args.get('passengers', 1), 'currency': 'INR',
                          'nonstop': nonstop, 'passengers': args.get('passengers', 1),
                          'detail': f'{"Non-stop" if nonstop else "1 stop"} · synthetic fare for {args.get("passengers", 1)} passenger(s)'})
        items.sort(key=lambda x: x['departure'] if args.get('ranking') == 'earliest' else x['price'])
        return {'items': items, 'source': 'THREAD synthetic flight inventory', 'summary': f'{len(items)} sandbox options match {args["origin"]} to {args["destination"]} on {args["date"]}.'}
    if domain == 'device':
        if args['model'].upper().replace('-', ' ') != 'THREAD R1':
            return {'items': [], 'source': MANUAL['title'], 'note': f'No matching supplied manual for {args["model"]}. Provide the correct manual or model.'}
        section = MANUAL['sections'][args['indicator']]
        return {'items': [{'id': f'R1-{args["indicator"]}', 'title': section['section'], 'detail': section['text']}],
                'source': MANUAL['title'], 'evidence': {'kind': 'supplied_manual', **section},
                'summary': section['text']}
    if domain == 'rooms':
        rooms = [('Cedar', 6, False, 500), ('Juniper', 8, True, 850), ('Atlas', 12, True, 1200)]
        items = [{'id': f'ROOM-{name.upper()}', 'title': name, 'capacity': capacity, 'projector': projector,
                  'date': args['date'], 'start': args['after'], 'duration_minutes': args['duration_minutes'],
                  'price': price, 'currency': 'INR', 'detail': f'{capacity} people · {"Projector" if projector else "Display only"} · {args["duration_minutes"]} min'}
                 for name, capacity, projector, price in rooms
                 if capacity >= args['people'] and (not args.get('projector') or projector)]
        start = sum(int(n) * m for n, m in zip(args['after'].split(':'), [60, 1]))
        finish = start + args['duration_minutes']
        if finish > 18 * 60 or start < 8 * 60:
            items = []
        if args.get('before') and finish > sum(int(n) * m for n, m in zip(args['before'].split(':'), [60, 1])):
            items = []
        return {'items': items, 'source': 'THREAD synthetic room inventory', 'summary': f'{len(items)} sandbox rooms match the capacity, equipment and time constraints. Opening hours: 08:00–18:00.'}
    raise ValueError('No sandbox executor for this manifest. Use the external event adapter.')
