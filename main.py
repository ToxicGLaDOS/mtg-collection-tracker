from flask import Flask, request, url_for, redirect, abort, render_template_string, flash
from urllib.parse import urlparse, urljoin
from flask_login import LoginManager, login_required, login_user, logout_user
import json, sqlite3, psycopg
import flask_login
from argon2 import PasswordHasher

login_manager = LoginManager()

app = Flask(__name__)
login_manager.init_app(app)

HASH_FUNCTION = 'SHA3-512'
app.config['SECRET_KEY'] = 'aed47c6a4cf84f7585ab2243a10c0e96'


con = psycopg.connect(user = "postgres", password = "password", host = "127.0.0.1", port = "5432")
cur = con.cursor()


cur.execute('''CREATE TABLE IF NOT EXISTS Users
            (
            ID           INTEGER PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
            Username     VARCHAR NOT NULL,
            PasswordHash VARCHAR NOT NULL,
            UNIQUE(Username)
            )
            ''')

res = cur.execute("""
            SELECT *
              FROM pg_type typ
                   INNER JOIN pg_namespace nsp
                              ON nsp.oid = typ.typnamespace
              WHERE nsp.nspname = current_schema()
                    AND typ.typname = 'condition'""")

# Create condition type if it doesn't exist
condition_type = res.fetchone()
if condition_type == None:
    cur.execute("""CREATE TYPE condition AS ENUM
                ('Damaged', 'Heavily Played', 'Moderately Played', 'Lightly Played', 'Near Mint')""")


cur.execute('''CREATE TABLE IF NOT EXISTS Collections
            (
            ID           INTEGER   PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
            UserID       INTEGER   REFERENCES Users(ID)       DEFERRABLE INITIALLY DEFERRED NOT NULL,
            FinishCardID INTEGER   REFERENCES FinishCards(ID) DEFERRABLE INITIALLY DEFERRED NOT NULL,
            Condition    condition NOT NULL,
            Signed       BOOLEAN   NOT NULL,
            Altered      BOOLEAN   NOT NULL,
            Notes        VARCHAR   NOT NULL,
            Quantity     INTEGER   NOT NULL,
            UNIQUE(UserID, FinishCardID, Condition, Signed, Altered, Notes)
            )
            ''')

ph = PasswordHasher()
password_hash = ph.hash('foo')

cur.execute('''INSERT INTO Users(Username, PasswordHash) VALUES(%s, %s) ON CONFLICT DO NOTHING''', ('me', password_hash))

con.commit()

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

def get_database_connection():
    con = psycopg.connect(user = "postgres", password = "password", host = "127.0.0.1", port = "5432")
    return con



def api_collection_search(search_text: str, page: int):
    con = get_database_connection()
    cur = con.cursor()

    cards = []
    username = flask_login.current_user.id

    res = cur.execute('SELECT ID FROM Users WHERE Username = %s', (username,))
    user_id = res.fetchone()

    if user_id == None:
        return json.dumps({'successful': False, 'error': "Couldn't find user ID in database."})

    user_id = user_id[0]

    res = cur.execute('''SELECT colls.ID, cards.ID, cards.Name, finishes.Finish, colls.Condition, langs.Lang, colls.Signed, colls.Altered, colls.Notes, colls.Quantity FROM Collections colls
                      INNER JOIN FinishCards finishCards ON colls.FinishCardID = finishCards.ID
                      INNER JOIN Cards cards ON finishCards.CardID = cards.ID
                      INNER JOIN Finishes finishes ON finishCards.FinishID = finishes.ID
                      INNER JOIN Langs langs ON cards.langID = langs.ID
                      WHERE colls.UserID = %s
                      ORDER BY cards.Name, cards.ReleasedAt DESC
                      ''', (user_id,))
    results = res.fetchall()

    for collection_id, scryfall_id, name, finish, condition, language, signed, altered, notes, quantity in results:
        if search_text.lower() in name.lower():
            cards.append({'collection_id': collection_id, 'scryfall_id': str(scryfall_id), 'finish': finish, 'quantity': quantity,
                          'condition': condition, 'language': language, 'signed': signed,
                          'altered': altered, 'notes': notes})

    length = len(cards)

    start = PAGE_SIZE * page
    end = start + PAGE_SIZE
    cards = cards[start:end]

    return json.dumps({'cards': cards, 'length': length})

@app.route("/api/all_cards/languages")
def api_all_cards_languages():
    con = get_database_connection()
    cur = con.cursor()

    args = request.args
    scryfall_id = args.get('scryfall_id')

    if not scryfall_id:
        error = {'successful': False, 'error': 'Expected query param "scryfall_id"'}
        return json.dumps(error)

    res = cur.execute('''SELECT A.ID, A.DefaultLang, Langs.Lang FROM Cards A
                CROSS JOIN Cards B
                INNER JOIN Langs ON A.LangID = Langs.ID
                WHERE B.ID = %s AND A.CollectorNumber = B.CollectorNumber AND A.SetID = B.SetID''', (scryfall_id,))

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
                'scryfall_id': str(id_),
                'default': bool(default),
                'lang': lang
                }

        languages.append(obj)

    return json.dumps(languages)

@app.route("/api/by_id")
def api_by_id():
    con = get_database_connection()
    cur = con.cursor()

    args = request.args
    scryfall_id = args.get('scryfall_id')

    if scryfall_id == None:
        error = {'successful': False, 'error': 'Expected query param "scryfall_id"'}
        return json.dumps(error)

    res = cur.execute("""SELECT Cards.ID, Cards.NormalImageURI, Finishes.Finish, Langs.Lang FROM Cards
                      INNER JOIN FinishCards ON Cards.ID = FinishCards.CardID
                      INNER JOIN Finishes ON FinishCards.FinishID = Finishes.ID
                      INNER JOIN Langs ON Cards.LangID = Langs.ID
                      WHERE Cards.ID = %s""", (scryfall_id,))
    entries = res.fetchall()

    if len(entries) == 0:
        error = {'successful': False, 'error': f"Couldn't find card with provided scryfall_id \"{scryfall_id}\""}
        return json.dumps(error)

    card = {'scryfall_id': scryfall_id, 'finishes': [], 'image_uri': entries[0][1], 'lang': entries[0][3]}
    for entry in entries:
        card['finishes'].append(entry[2])


    return json.dumps(card)


def api_all_cards_search(search_text: str, page: int, default: bool):
    con = get_database_connection()
    cur = con.cursor()

    cards = []
    search_string = f'%{search_text}%'

    if default:
        res = cur.execute('''SELECT COUNT(*) FROM Cards
                          WHERE LOWER(Name) LIKE %s AND DefaultLang = true''',
                          (search_string,))
        length = res.fetchone()[0]

        res = cur.execute('''SELECT ID FROM Cards
                          WHERE LOWER(Name) LIKE %s AND DefaultLang = true
                          ORDER BY Name, ReleasedAt DESC
                          LIMIT %s OFFSET %s
                          ''',
                          (search_string, PAGE_SIZE, page * PAGE_SIZE))
    else:
        res = cur.execute('''SELECT COUNT(*) FROM Cards
                          WHERE LOWER(Name) LIKE %s
                          ''',
                          (search_string,))
        length = res.fetchone()[0]

        res = cur.execute('''SELECT ID FROM Cards
                          WHERE LOWER(Name) LIKE %s
                          ORDER BY Name, ReleasedAt DESC
                          LIMIT %s OFFSET %s
                          ''',
                          (search_string, PAGE_SIZE, page * PAGE_SIZE))

    card_results = res.fetchall()

    for card in card_results:
        cards.append({'scryfall_id': str(card[0])})

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

def get_other_language_id(scryfall_id: str, lang: str):
    res = cur.execute('''SELECT SetID, CollectorNumber FROM Cards
                      WHERE ID = %s''', (scryfall_id,))

    set_id, collector_number = res.fetchone()[0]

    res = cur.execute('''SELECT ID FROM Langs
                      WHERE Lang = %s
                      ''', (lang,))

    lang_id = res.fetchone()[0]

    res = cur.execute('''SELECT ID FROM Cards
                      WHERE SetID = %s
                      CollectorNumber = %s
                      LangID = %s
                      ''', (set_id, collector_number, lang_id))


def get_finish_card_id(finish: str, scryfall_id: str) -> tuple[None, int] | tuple[dict, None]:
    error = None
    res = cur.execute('''SELECT ID FROM Finishes
                         WHERE Finish = %s
                      ''', (finish,))
    finish_id = res.fetchone()

    if finish_id == None:
        error = {'successful': False, 'error': f"No such finish {finish}"}
        return (error, None)

    finish_id = finish_id[0]

    res = cur.execute('''SELECT ID FROM FinishCards
                      WHERE CardID = %s AND FinishID = %s
                      ''', (scryfall_id, finish_id))

    finish_card_id = res.fetchone()

    if finish_card_id == None:
        error = {'successful': False, 'error': f"That card doesn't come in the finish \"{finish}\""}
        return (error, None)
    finish_card_id = finish_card_id[0]

    return error, finish_card_id


@app.route("/api/collection", methods = ['POST', 'GET', 'PATCH'])
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
        con = get_database_connection()
        cur = con.cursor()

        username = flask_login.current_user.id

        res = cur.execute('SELECT ID FROM Users WHERE Username = %s', (username,))
        user_id = res.fetchone()

        if user_id == None:
            return json.dumps({'successful': False, 'error': "Couldn't find user ID in database."})

        user_id = user_id[0]

        content_type = request.headers.get('Content-Type')
        if (content_type == 'application/json'):
            request_json = request.json
            if request_json == None or request_json == "":
                error = {'successful': False, 'error': f"Expected content, got empty POST body"}
                return json.dumps(error)

            scryfall_id = request_json.get('scryfall_id')
            quantity = request_json.get('quantity')
            finish = request_json.get('finish')
            condition = request_json.get('condition')
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
            if condition == None:
                error = {'successful': False, 'error': f'Expected key "condition" not found in POST body.'}
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
                error = {'successful': False, 'error': f'Expected key "finish" to be a str, got {str(type(finish).__name__)}'}
                return json.dumps(error)
            if type(condition) != str:
                error = {'successful': False, 'error': f'Expected key "condition" to be a str, got {str(type(condition).__name__)}'}
                return json.dumps(error)
            if type(language) != str:
                error = {'successful': False, 'error': f'Expected key "language" to be a str, got {str(type(language).__name__)}'}
                return json.dumps(error)
            if type(signed) != bool:
                error = {'successful': False, 'error': f'Expected key "signed" to be a bool, got {str(type(signed).__name__)}'}
                return json.dumps(error)
            if type(altered) != bool:
                error = {'successful': False, 'error': f'Expected key "altered" to be a bool, got {str(type(altered).__name__)}'}
                return json.dumps(error)
            if type(notes) != str:
                error = {'successful': False, 'error': f'Expected key "notes" to be a str, got {str(type(notes).__name__)}'}
                return json.dumps(error)

            # TODO: Check for unexpected keys

            res = cur.execute("""SELECT Cards.Name, Cards.CollectorNumber, Sets.Code FROM Cards
                              INNER JOIN Sets ON Cards.SetID = Sets.ID
                              WHERE Cards.ID = %s""", (scryfall_id,))
            row = res.fetchone()

            if row == None:
                error = {'successful': False, 'error': f'Couldn\'t find a card with that id "{scryfall_id}"'}
                return json.dumps(error)

            return_card = {
                    'name': row[0],
                    'collector_number': row[1],
                    'set_abbr': row[2]
                    }


            error, finish_card_id = get_finish_card_id(finish, scryfall_id)
            if error != None:
                return json.dumps(error)

            res = cur.execute('''SELECT Quantity FROM Collections
                              WHERE UserID = %s AND
                              FinishCardID = %s AND
                              Condition = %s AND
                              Signed = %s AND
                              Altered = %s AND
                              Notes = %s
                              ''', (user_id, finish_card_id, condition, signed, altered, notes))
            original_quantity = res.fetchone()
            card_in_collection = original_quantity != None

            if card_in_collection:
                original_quantity = original_quantity[0]
                res = cur.execute('''UPDATE collections SET Quantity = quantity + %s
                            WHERE UserID = %s AND
                            FinishCardID = %s AND
                            Condition = %s AND
                            Signed = %s AND
                            Altered = %s AND
                            Notes = %s
                            RETURNING Quantity
                            ''', (quantity, user_id, finish_card_id, condition, signed, altered, notes))
                updated_quantity = res.fetchone()[0]
            else:
                original_quantity = 0
                res = cur.execute('''INSERT INTO Collections(UserID, FinishCardID, Condition, Signed, Altered, Notes, Quantity)
                            VALUES(%s, %s, %s, %s, %s, %s, %s)
                            RETURNING Quantity
                            ''', (user_id, finish_card_id, condition, signed, altered, notes, quantity))
                updated_quantity = res.fetchone()[0]

            # If we get a request to have 0 or negative updated_quantity we delete the row
            # This can happen if the user clicks the - button
            # while having 0 in the collection
            if updated_quantity <= 0:
                cur.execute('''DELETE FROM collections
                        WHERE UserID = %s AND
                        FinishCardID = %s AND
                        Condition = %s AND
                        Signed = %s AND
                        Altered = %s AND
                        Notes = %s
                        ''', (user_id, finish_card_id, condition, signed, altered, notes))
                updated_quantity = 0

            delta = updated_quantity - original_quantity

            return_obj = {'successful': True, 'card': return_card, 'delta': delta, 'new_total': updated_quantity}
            con.commit()
            return json.dumps(return_obj)
        else:
            error = {'successful': False, 'error': f"Expected Content-Type: application/json, found {content_type}"}
            return json.dumps(error)
    elif request.method == "PATCH":
        con = get_database_connection()
        cur = con.cursor()

        username = flask_login.current_user.id

        res = cur.execute('SELECT ID FROM Users WHERE Username = %s', (username,))
        user_id = res.fetchone()

        if user_id == None:
            return json.dumps({'successful': False, 'error': "Couldn't find user ID in database."})

        user_id = user_id[0]

        request_json = request.json
        if request_json == None or request_json == "":
                error = {'successful': False, 'error': f"Expected content, got empty PATCH body"}
                return json.dumps(error)

        target_card = request_json.get('target')
        replacement_card = request_json.get('replacement')
        if target_card == None:
            error = {'successful': False, 'error': f"Didn't find expected key 'target' in PATCH body"}
            return json.dumps(error)
        if replacement_card == None:
            error = {'successful': False, 'error': f"Didn't find expected key 'replacement' in PATCH body"}
            return json.dumps(error)



        target_required_keys = {"scryfall_id": str,
                                "finish": str,
                                "condition": str,
                                "signed": bool,
                                "altered": bool,
                                "notes": str}

        for key_name, key_type in target_required_keys.items():
            if target_card.get(key_name) == None:
                error = {'successful': False, 'error': f"Didn't find expected key 'target.{key_name}' in PATCH body"}
                return json.dumps(error)

            value = target_card[key_name]
            if type(value) != key_type:
                error = {'successful': False, 'error': f"Expected key 'target.{key_name}' to be of type {key_type}, but got {type(value)}"}

        # Make sure to handle quantity

        error, target_finish_card_id = get_finish_card_id(target_card['finish'], target_card['scryfall_id'])
        if error != None:
            return json.dumps(error)

        res = cur.execute('''SELECT FinishCardID, Condition, Signed, Altered, Notes FROM Collections
                          WHERE
                            UserID = %s AND
                            FinishCardID = %s AND
                            Condition = %s AND
                            Signed = %s AND
                            Altered = %s AND
                            Notes = %s
                          ''', (user_id, target_finish_card_id, target_card['condition'], target_card['signed'], target_card['altered'], target_card['notes']))
        defaults = res.fetchone()
        if defaults == None:
            error = {'successful': False, 'error': f"Couldn't find target card in database"}
            return json.dumps(error)

        default_finish_card_id, default_condition, default_signed, default_altered, default_notes = defaults

        replacement_finish = replacement_card.get('finish', default_finish_card_id)
        error, replacement_finish_card_id = get_finish_card_id(replacement_finish, target_card['scryfall_id'])
        if error != None:
            return json.dumps(error)

        replacement_condition = replacement_card.get('condition', default_condition)
        replacement_signed = replacement_card.get('signed', default_signed)
        replacement_altered = replacement_card.get('altered', default_altered)
        replacement_notes = replacement_card.get('notes', default_notes)

        res = cur.execute(f'''UPDATE Collections
                    SET
                      FinishCardID = %s,
                      Condition = %s,
                      Signed = %s,
                      Altered = %s,
                      Notes = %s
                    WHERE
                      UserID = %s AND
                      FinishCardID = %s AND
                      Condition = %s AND
                      Signed = %s AND
                      Altered = %s AND
                      Notes = %s
                    ''', (replacement_finish_card_id, replacement_condition, replacement_signed, replacement_altered, replacement_notes) + (user_id, target_finish_card_id, target_card['condition'], target_card['signed'], target_card['altered'], target_card['notes']))

        con.commit()
        return_obj = {'successful': True}
        return json.dumps(return_obj)


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
