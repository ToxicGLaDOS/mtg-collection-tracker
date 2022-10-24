#!/usr/bin/env python

#               all | foil | collector number | signed | prerelease | alter
# ---------------------------------------------------------------------------
# text        |  x  |  x   |                  |    x   |            |
# multiverse  |     |      |   not directly   |        |            |
# csv         |  x  |  x   |     wrong???     |    x   |     x      |
# printable   |  x  |  x   |        x         |    ?   |     x      |

import re, sys, os, json, time

# Use local scryfall database for this
def get_default_collectors_number(name, set_abbr):
    # Tappedout does Turn / Burn
    # Scryfall  does Turn // Burn
    if '/' in name and '//' not in name:
        name = name.replace('/', '//')
    # Tappedout uses an inconsistent number of _
    # Scryfall always uses _____
    name = re.sub('___+', '_____', name)
    # Tappedout has a typo
    if name == 'Psuedodragon Familiar':
        name = 'Pseudodragon Familiar'
    # Tappedout doesn't care about ñ
    if name == 'Robo-Pinata':
        name = 'Robo-Piñata'
    set_ = sets[set_abbr]
    cards = [card for card in set_ if card['name'].lower() == name.lower()]
    # Cards with multiple faces, adventure cards, split cards, etc. will have a combined name
    # so we have to check the faces
    if len(cards) == 0:
        cards_with_faces = [card for card in set_ if card.get('card_faces') != None]
        cards = [card for card in cards_with_faces if card['card_faces'][0]['name'].lower() == name.lower()]

    # If any collector_numbers are numeric
    if any([card['collector_number'].isnumeric() for card in cards]):
        # Filter out the cards with non-numeric collector numbers
        cards = [card for card in cards if card['collector_number'].isnumeric()]
        # Sort by collector number as int (sorting by str results in '125' < '64')
        default = min(cards, key=lambda card: int(card['collector_number']))['collector_number']
    # ex. Unfinity attractions have all non-numeric collector numbers
    else:
        card = min(cards, key=lambda card: card['collector_number'])
        default = card['collector_number']

        if len(cards) > 1:
            # Tappedout doesn't seem to differentiate these so print a warning that we've defaulted to
            # the first variation
            print(f"WARNING: Tappedout might not differentiate between the versions of {card['name']} ({card['set']}), defaulting to collector number {default}.")

    if len(cards) == 0:
        print(cards)
        print(name, set_abbr)

    assert type(default) == str
    assert default != ''
    return default

if len(sys.argv) != 3:
    print("Expected exactly 2 argurments. The path to the ALL json bulk data and the path to the DEFAULT json bulk data.")
    exit(1)

with open(sys.argv[1], 'r') as f:
    all_data = json.load(f)

with open(sys.argv[2], 'r') as f:
    default_data = json.load(f)

# Maps collector_number:set -> <default language>
default_language_map = {}

# Maps set -> [<card_objs>]
# Splitting the big list into sets is a good way to reduce iteration
# and for every card we _always_ have the set from tappedout's data
sets = {}

for card in default_data:
    key = f"{card['collector_number']}:{card['set']}"
    default_language_map[key] = card['lang']

for card in all_data:
    if not sets.get(card['set']):
        sets[card['set']] = []

    sets[card['set']].append(card)

with open('printable.txt', 'r') as f:
    with open('output.csv', 'w') as out:
        out.write(f"Quantity|Name|Set|Collector Number|Variation|List|Foil|Promo Pack|Prerelease|Language|Scryfall ID\n")
        # We skip the first line because it's a title
        for line in list(f)[1:]:
            # Skip the blank lines
            if line == '\n':
                continue
            pattern = r'^([0-9]+)x ([^(]+) \(([A-Z0-9]{3,4})(:([A-Za-z0-9]+))?\)( \*(f|list|pp|f-pp|f-pre|[A-Z]{2})\*)?$'
            matches = re.match(pattern, line)
            if matches == None:
                raise Exception(f"Input is in wrong format. Expected to match '{pattern}' but couldn't. Input was {line}")

            quantity = matches.group(1)
            name = matches.group(2)
            set_abbr = matches.group(3).lower()
            if set_abbr == '000':
                if name == 'Arbor Elf':
                    set_abbr = 'pw21'
                elif name == 'Archfiend of Ifnir':
                    set_abbr = 'pakh'
                elif name == 'Ember Swallower':
                    set_abbr = 'pths'
                elif name == 'Mind Stone':
                    set_abbr = 'pw21'
                elif name == 'Goblin Guide':
                    set_abbr = 'plg21'
                elif name == 'Swiftfoot Boots':
                    set_abbr = 'pw22'
                else:
                    raise Exception(f"Unhandled 000 set. {name}")
            # tappedout and scryfall use different codes
            if set_abbr == 'mys1':
                set_abbr = 'mb1'
            elif set_abbr == 'eo2':
                set_abbr = 'e02'
            elif set_abbr == 'pfl':
                set_abbr = 'pd2'
            # these appear to be just wrong in tappedout?
            elif set_abbr == 'tsb':
                if name in ['Swamp', 'Aarakocra Sneak']:
                    set_abbr = 'clb'
            # 3 is a wrapper to make the varaition optional
            variation = matches.group(5)
            collector_number = None
            promo_pack = False
            prerelease = False
            # Collector numbers can have non-numbers in them
            if variation:
                if variation.isnumeric():
                    collector_number = variation
                    variation = None
                elif variation == 'PromoPack':
                    collector_number = get_default_collectors_number(name, set_abbr)
                    promo_pack = True
                    variation = None
                else:
                    raise Exception(f"Unhandled variation type. Variation was {variation}. Card was {name} {set_abbr}")
            else:
                collector_number = get_default_collectors_number(name, set_abbr)
            # 6 wraps around the *'s
            foil_or_language = matches.group(7)
            foil = False
            key = f"{collector_number}:{set_abbr.lower()}"
            language = default_language_map[key]
            the_list = False
            if foil_or_language:
                if foil_or_language == 'f':
                    foil = True
                elif foil_or_language == 'list':
                    the_list = True
                elif foil_or_language == 'pp':
                    promo_pack = True
                elif foil_or_language == 'f-pp':
                    foil = True
                    promo_pack = True
                elif foil_or_language == 'f-pre':
                    foil = True
                    prerelease = True
                else:
                    language = foil_or_language.lower()
            if language == 'zh':
                print(f"WARNING: Tappedout doesn't have Chinese Traditional as a language option. Verify this card is actually Chinese Simplified. {name} ({set_abbr}:{collector_number})")
                language = 'zhs'

            set_ = sets[set_abbr]
            card = [card for card in set_ if card['collector_number'] == collector_number and card['lang'].lower() == language.lower()]
            if len(card) != 1:
                import pdb; pdb.set_trace()
                raise ValueError(f"Expected only one card with collector number {collector_number} in set {set_abbr}. Cards: {card}")
            card = card[0]
            scryfall_id = card['id']
            out.write(f"{quantity}|{name}|{set_abbr}|{collector_number}|{variation}|{the_list}|{foil}|{promo_pack}|{prerelease}|{language}|{scryfall_id}\n")

# Sanity checks
import csv
with open('output.csv', 'r') as out:
    output_reader = csv.DictReader(out, delimiter='|')
    total_cards = 0
    for row in output_reader:
        total_cards += int(row["Quantity"])
        assert(len(row.keys()) == 11)

assert total_cards == 6890



