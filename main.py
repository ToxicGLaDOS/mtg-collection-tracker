from flask import Flask, request, url_for, redirect, abort, render_template_string, flash
from urllib.parse import urlparse, urljoin
from flask_login import LoginManager, login_required, login_user, logout_user
import json, csv, sqlite3

login_manager = LoginManager()

app = Flask(__name__)
login_manager.init_app(app)

app.config['SECRET_KEY'] = 'aed47c6a4cf84f7585ab2243a10c0e96'

class User:
    def __init__(self, id, password):
        self.id = id
        self.password = password
        self.is_authenticated = True
        self.is_active = True
        self.is_anonymous = False

    def get_id(self):
        return self.id

# Matches the function name that you want to go to
login_manager.login_view = "login"

users = {}
users['me'] = User('me', 'foo')
PAGE_SIZE = 25

# Ensures the url isn't leaving our site
# Good for making sure redirects are safe
def is_safe_url(target):
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ('http', 'https') and \
           ref_url.netloc == test_url.netloc

@login_manager.user_loader
def load_user(user_id):
    return users.get(user_id)

@app.route("/")
def index():
    return '''
<style>
    .grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, 150px)
    }
</style>
<div class="grid"></div>'''

def api_collection_search(search_text: str, page: int):
    cards = []
    with open('output.csv', 'r') as f:
        cards_reader = csv.DictReader(f, delimiter='|')
        for card in cards_reader:
            name = card['Name'].lower()
            if search_text.lower() in name:
                cards.append({'scryfall_id': card['Scryfall ID'], 'quantity': card['Quantity']})

    length = len(cards)

    start = PAGE_SIZE * page
    end = start + PAGE_SIZE
    cards = cards[start:end]

    return json.dumps({'cards': cards, 'length': length})

@app.route("/api/all_cards/languages")
def api_all_cards_languages():
    con = sqlite3.connect('all.db')
    cur = con.cursor()

    args = request.args
    scryfall_id = args.get('scryfall_id')

    if not scryfall_id:
        error = {'successful': False, 'error': 'Expected query param "scryfall_id"'}
        return json.dumps(error)

    res = cur.execute('''SELECT A.ID, A.DefaultLang, Langs.Lang FROM Cards A
                INNER JOIN Cards B
                INNER JOIN Langs ON A.LangID=Langs.ID
                WHERE B.ID == ? AND A.CollectorNumber == B.CollectorNumber AND A.SetID == B.SetID''', (scryfall_id,))

    rows = res.fetchall()
    if len(rows) == 0:
        error = {'successful': False, 'error': f"Couldn't find a card with scryfall_id \"{scryfall_id}\""}
        return json.dumps(error)

    languages = []

    for row in rows:
        id_ = row[0]
        default = row[1]
        lang = row[2]
        obj = {
                'scryfall_id': id_,
                'default': bool(default),
                'lang': lang
                }

        languages.append(obj)

    return json.dumps(languages)

@app.route("/api/by_id")
def api_by_id():
    con = sqlite3.connect('all.db')
    cur = con.cursor()

    args = request.args
    scryfall_id = args.get('scryfall_id')

    if scryfall_id == None:
        error = {'successful': False, 'error': 'Expected query param "scryfall_id"'}
        return json.dumps(error)

    print(scryfall_id)
    res = cur.execute("""SELECT Cards.ID, Cards.NormalImageURI, Finishes.Finish FROM Cards
                      INNER JOIN FinishCards ON Cards.ID=FinishCards.CardID
                      INNER JOIN Finishes ON FinishCards.FinishID=Finishes.ID
                      WHERE Cards.ID == ?""", (scryfall_id,))
    entries = res.fetchall()

    if len(entries) == 0:
        error = {'successful': False, 'error': f"Couldn't find card with provided scryfall_id \"{scryfall_id}\""}
        return json.dumps(error)

    card = {'scryfall_id': scryfall_id, 'finishes': [], 'image_uri': entries[0][1]}
    for entry in entries:
        card['finishes'].append(entry[2])


    return json.dumps(card)


def api_all_cards_search(search_text: str, page: int, default: bool):
    con = sqlite3.connect('all.db')
    cur = con.cursor()

    cards = []
    search_string = f'%{search_text}%'

    res = cur.execute("SELECT COUNT(*) FROM Cards WHERE LOWER(Name) LIKE ? AND DefaultLang == ?", (search_string, default))
    length = res.fetchone()

    res = cur.execute("SELECT ID FROM Cards WHERE LOWER(Name) LIKE ? AND DefaultLang == ? LIMIT ?, ?", (search_string, default, page * PAGE_SIZE, PAGE_SIZE))
    card_results = res.fetchall()

    for card in card_results:
        cards.append({'scryfall_id': card[0]})

    return json.dumps({'cards': cards, 'length': length})


@app.route("/api/all_cards")
def api_all_cards():
    args = request.args
    page = args.get('page')
    query = args.get('query')
    default = args.get('default')

    if page:
        page = int(page)
    else:
        page = 0

    if default:
        default = default == 'true'
    else:
        default = False

    if query:
        if query == 'search':
            # TODO: Check this exists and is valid
            search_text = args.get('text')
            return api_all_cards_search(search_text, page, default)
        else:
            # Return an error
            pass
    else:
        return api_all_cards_search('', page, default)


@app.route("/api/collection", methods = ['POST', 'GET'])
def api_collection():
    if request.method == 'GET':
        args = request.args
        page = args.get('page')
        query = args.get('query')

        if page:
            page = int(page)
        else:
            page = 0

        if query:
            if query == 'search':
                # TODO: Check this exists and is valid
                search_text = args.get('text')
                return api_collection_search(search_text, page)
            else:
                error = {'successful': False, 'error': f'Unsupported value for query parameter "query". Expected "search". Got {query}'}
                return json.dumps(error)
        else:
            return api_collection_search('', page)

    # This is where we add cards to the database
    # We need to do as much error checking as possible here
    # to ensure we don't accidently mess up the database
    # or say we're adding a card when in reality we aren't
    elif request.method == 'POST':
        con = sqlite3.connect('all.db')
        cur = con.cursor()

        content_type = request.headers.get('Content-Type')
        if (content_type == 'application/json'):
            request_json = request.json
            if request_json == None or request_json == "":
                error = {'successful': False, 'error': f"Expected content, got empty POST body"}
                return json.dumps(error)

            scryfall_id = request_json.get('scryfall_id')
            quantity = request_json.get('quantity')
            finish = request_json.get('finish')
            language = request_json.get('language')
            signed = request_json.get('signed')
            altered = request_json.get('altered')
            notes = request_json.get('notes')

            if scryfall_id == None:
                error = {'successful': False, 'error': f'Expected key "scryfall_id" not found in POST body.'}
                return json.dumps(error)
            if quantity == None:
                error = {'successful': False, 'error': f'Expected key "quantity" not found in POST body.'}
                return json.dumps(error)
            if finish == None:
                error = {'successful': False, 'error': f'Expected key "finish" not found in POST body.'}
                return json.dumps(error)

            if language == None:
                error = {'successful': False, 'error': f'Expected key "language" not found in POST body.'}
                return json.dumps(error)
            if signed == None:
                error = {'successful': False, 'error': f'Expected key "signed" not found in POST body.'}
                return json.dumps(error)
            if altered == None:
                error = {'successful': False, 'error': f'Expected key "altered" not found in POST body.'}
                return json.dumps(error)
            if notes == None:
                error = {'successful': False, 'error': f'Expected key "notes" not found in POST body.'}
                return json.dumps(error)

            if type(scryfall_id) != str:
                error = {'successful': False, 'error': f'Expected key "scryfall_id" to be a string, got {str(type(scryfall_id).__name__)}'}
                return json.dumps(error)
            if type(quantity) != int:
                error = {'successful': False, 'error': f'Expected key "quantity" to be an int, got {str(type(quantity).__name__)}'}
            if type(finish) != str:
                error = {'successful': False, 'error': f'Expected key "finish" to be a str, got {str(type(language).__name__)}'}
                return json.dumps(error)
            if type(language) != str:
                error = {'successful': False, 'error': f'Expected key "language" to be a str, got {str(type(language).__name__)}'}
                return json.dumps(error)
            if type(signed) != bool:
                error = {'successful': False, 'error': f'Expected key "quantity" to be a bool, got {str(type(signed).__name__)}'}
                return json.dumps(error)
            if type(altered) != bool:
                error = {'successful': False, 'error': f'Expected key "quantity" to be a bool, got {str(type(altered).__name__)}'}
                return json.dumps(error)
            if type(notes) != str:
                error = {'successful': False, 'error': f'Expected key "quantity" to be a str, got {str(type(notes).__name__)}'}
                return json.dumps(error)

            # TODO: Check for unexpected keys

            res = cur.execute("""SELECT Cards.Name, Cards.CollectorNumber, Sets.Abbreviation FROM Cards
                              INNER JOIN Sets ON Cards.SetID=Sets.ID
                              WHERE Cards.ID == ?""", (scryfall_id,))
            row = res.fetchone()

            if row == None:
                error = {'successful': False, 'error': f'Couldn\'t find a card with that id "{scryfall_id}"'}
                return json.dumps(error)

            return_card = {
                    'name': row[0],
                    'collector_number': row[1],
                    'set_abbr': row[2]
                    }

            with open('output.csv', 'r') as f:
                cards = list(csv.DictReader(f, delimiter='|'))
            for card in cards:
                if card['Scryfall ID'] == scryfall_id:
                    card['Quantity'] = str(int(card['Quantity']) + quantity)
                    with open('output.csv', 'w') as f:
                        fieldnames = ["Quantity", "Name", "Set", "Collector Number", "Variation", "List", "Foil", "Promo Pack", "Prerelease", "Language", "Scryfall ID"]
                        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter='|')
                        writer.writeheader()
                        writer.writerows(cards)
                    return_obj = {'successful': True, 'card': return_card}
                    return json.dumps(return_obj)

            cards.append({
                'Quantity': str(quantity),
                'Name': return_card['name'],
                'Set': return_card['set_abbr'],
                'Collector Number': return_card['collector_number'],
                'Variation': str(None),
                'List': str(False),
                'Foil': str(False),
                'Promo Pack': str(False),
                'Prerelease': str(False),
                'Language': language,
                'Scryfall ID': scryfall_id
                            })

            with open('output.csv', 'w') as f:
                fieldnames = ["Quantity", "Name", "Set", "Collector Number", "Variation", "List", "Foil", "Promo Pack", "Prerelease", "Language", "Scryfall ID"]
                writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter='|')
                writer.writeheader()
                writer.writerows(cards)

            return_obj = {'successful': True, 'card': return_card}
            return json.dumps(return_obj)
        else:
            error = {'successful': False, 'error': f"Expected Content-Type: application/json, found {content_type}"}
            return json.dumps(error)


@app.route("/collection")
@login_required
def collection():
    with open('./html/collection.html', 'r') as collection_html:
        return render_template_string(collection_html.read())

@app.route("/collection/add")
def collection_add():
    with open('./html/collection_add.html', 'r') as collection_add_html:
        return render_template_string(collection_add_html.read())

@app.route("/deckbuilder")
@login_required
def deckbuilder():
    return render_template_string('''
<style>
  .column {
    position: relative;
    top: 0;
    left: 0px;
  }
  .card-image {
    width: 150px;
    height: auto;
    position: absolute;
    border-radius: 10px;
  }
</style>
<script>
</script>
<div class=column>
{% for i in range(10000) %}
<img class="card-image" src=https://c1.scryfall.com/file/scryfall-cards/normal/front/b/4/b4ea262c-ea32-4aca-b96b-58f556a8dffc.jpg loading="lazy" style="top: {{ 20 * i }}px"></img>
{% endfor %}
</div>''')

@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route("/login", methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template_string('''
              {% with messages = get_flashed_messages() %}
              <form method="POST">
              <label for="username">Username:</label>
              <input type="text" name="username" id="username"></input>
              <label for="password">Password:</label>
              <input type="text" name= "password" id="password"></input>
              <input type="submit" value="Submit"></input>
              {% if messages %}
                <ul class=flashes>
                {% for message in messages %}
                  <li>{{ message }}</li>
                {% endfor %}
                </ul>
              {% endif %}
              {% endwith %}''')
    elif request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = users[username]
        if password == user.password:
            user.is_authenticated = True
            login_user(user)

            next = request.args.get('next')
            if not is_safe_url(next):
                return abort(400)

            return redirect(next or url_for('index'))
        else:
            user.is_authenticated = False
            flash("Incorrect username or password")
            return redirect(request.url)
