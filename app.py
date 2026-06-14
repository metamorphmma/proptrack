from flask import Flask, request, jsonify, send_from_directory
import sqlite3, os
from datetime import datetime

app = Flask(__name__, static_folder='static')
DB = os.path.join(os.path.dirname(__file__), 'leads.db')

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_name TEXT NOT NULL,
            property_type TEXT NOT NULL,
            property_address TEXT,
            transaction_type TEXT NOT NULL DEFAULT 'sell',
            projected_value REAL,
            commission_pct REAL,
            linked_lead_id INTEGER,
            stage TEXT DEFAULT 'prospecting',
            win_probability TEXT,
            accepted_offer_id INTEGER,
            final_accepted_price REAL,
            accepted_at TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS stage_remarks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id INTEGER NOT NULL,
            stage TEXT NOT NULL,
            remark TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (lead_id) REFERENCES leads(id)
        );
        CREATE TABLE IF NOT EXISTS viewings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id INTEGER NOT NULL,
            buyer_name TEXT,
            viewing_date TEXT NOT NULL,
            notes TEXT,
            counterpart_name TEXT,
            counterpart_number TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (lead_id) REFERENCES leads(id)
        );
        CREATE TABLE IF NOT EXISTS offers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id INTEGER NOT NULL,
            viewing_id INTEGER,
            buyer_name TEXT,
            offer_price REAL NOT NULL,
            notes TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (lead_id) REFERENCES leads(id)
        );
        CREATE TABLE IF NOT EXISTS counter_offers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id INTEGER NOT NULL,
            offer_id INTEGER,
            buyer_name TEXT,
            counter_price REAL NOT NULL,
            notes TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (lead_id) REFERENCES leads(id),
            FOREIGN KEY (offer_id) REFERENCES offers(id)
        );
    ''')
    conn.commit()
    # migrations for existing databases
    for sql in [
        'ALTER TABLE leads ADD COLUMN win_probability TEXT',
        'ALTER TABLE leads ADD COLUMN accepted_offer_id INTEGER',
        'ALTER TABLE leads ADD COLUMN final_accepted_price REAL',
        'ALTER TABLE leads ADD COLUMN property_address TEXT',
        'ALTER TABLE leads ADD COLUMN accepted_at TEXT',
        'ALTER TABLE viewings ADD COLUMN counterpart_name TEXT',
        'ALTER TABLE viewings ADD COLUMN counterpart_number TEXT',
        'ALTER TABLE viewings ADD COLUMN win_probability TEXT',
        'ALTER TABLE leads ADD COLUMN net_commission_pct REAL',
    ]:
        try:
            conn.execute(sql); conn.commit()
        except Exception:
            pass
    conn.close()

init_db()

def load_lead(conn, lead_id):
    lead = conn.execute('SELECT * FROM leads WHERE id=?', (lead_id,)).fetchone()
    if not lead:
        return None
    d = dict(lead)
    d['viewings'] = [dict(v) for v in conn.execute(
        'SELECT * FROM viewings WHERE lead_id=? ORDER BY viewing_date', (lead_id,)).fetchall()]
    d['remarks'] = [dict(r) for r in conn.execute(
        'SELECT * FROM stage_remarks WHERE lead_id=? ORDER BY created_at', (lead_id,)).fetchall()]
    d['offers'] = [dict(o) for o in conn.execute(
        'SELECT * FROM offers WHERE lead_id=? ORDER BY created_at', (lead_id,)).fetchall()]
    d['counter_offers'] = [dict(c) for c in conn.execute(
        'SELECT * FROM counter_offers WHERE lead_id=? ORDER BY created_at', (lead_id,)).fetchall()]
    return d

# --- Leads ---

@app.route('/api/leads', methods=['GET'])
def list_leads():
    conn = get_db()
    ids = [r['id'] for r in conn.execute('SELECT id FROM leads ORDER BY updated_at DESC').fetchall()]
    result = [load_lead(conn, i) for i in ids]
    conn.close()
    return jsonify([r for r in result if r])

@app.route('/api/leads', methods=['POST'])
def create_lead():
    data = request.json
    conn = get_db()
    cur = conn.execute(
        '''INSERT INTO leads (client_name, property_type, property_address, transaction_type,
           projected_value, commission_pct, linked_lead_id, stage) VALUES (?,?,?,?,?,?,?,?)''',
        (data['client_name'], data['property_type'], data.get('property_address'), 'sell',
         data.get('projected_value'), data.get('commission_pct'),
         data.get('linked_lead_id'), data.get('stage', 'prospecting'))
    )
    conn.commit()
    lead_id = cur.lastrowid
    conn.close()
    return jsonify({'id': lead_id}), 201

@app.route('/api/leads/<int:lead_id>', methods=['GET'])
def get_lead(lead_id):
    conn = get_db()
    d = load_lead(conn, lead_id)
    conn.close()
    return jsonify(d) if d else (jsonify({'error': 'not found'}), 404)

@app.route('/api/leads/<int:lead_id>', methods=['PUT'])
def update_lead(lead_id):
    data = request.json
    conn = get_db()
    conn.execute(
        '''UPDATE leads SET client_name=?, property_type=?, property_address=?,
           transaction_type=?, projected_value=?, commission_pct=?, linked_lead_id=?,
           stage=?, updated_at=datetime('now') WHERE id=?''',
        (data['client_name'], data['property_type'], data.get('property_address'), 'sell',
         data.get('projected_value'), data.get('commission_pct'),
         data.get('linked_lead_id'), data['stage'], lead_id)
    )
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/leads/<int:lead_id>', methods=['DELETE'])
def delete_lead(lead_id):
    conn = get_db()
    for tbl in ['stage_remarks', 'viewings', 'counter_offers', 'offers']:
        conn.execute(f'DELETE FROM {tbl} WHERE lead_id=?', (lead_id,))
    conn.execute('DELETE FROM leads WHERE id=?', (lead_id,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

# --- Stage & probability ---

@app.route('/api/leads/<int:lead_id>/stage', methods=['PUT'])
def update_stage(lead_id):
    data = request.json
    conn = get_db()
    if data['stage'] == 'accepted':
        conn.execute(
            "UPDATE leads SET stage=?, accepted_at=datetime('now'), updated_at=datetime('now') WHERE id=?",
            (data['stage'], lead_id)
        )
    else:
        conn.execute("UPDATE leads SET stage=?, updated_at=datetime('now') WHERE id=?",
                     (data['stage'], lead_id))
    if data.get('remark'):
        conn.execute('INSERT INTO stage_remarks (lead_id, stage, remark) VALUES (?,?,?)',
                     (lead_id, data['stage'], data['remark']))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

# --- Settings ---

@app.route('/api/settings', methods=['GET'])
def get_settings():
    conn = get_db()
    rows = conn.execute('SELECT key, value FROM settings').fetchall()
    conn.close()
    result = {r['key']: r['value'] for r in rows}
    if 'agent_split_pct' not in result:
        result['agent_split_pct'] = '70'
    return jsonify(result)

@app.route('/api/settings', methods=['PUT'])
def update_settings():
    data = request.json
    conn = get_db()
    for key, value in data.items():
        conn.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)', (key, str(value)))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

# --- Commission ---

def add_months(dt, n):
    m = dt.month - 1 + n
    year = dt.year + m // 12
    month = m % 12 + 1
    import calendar
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)

@app.route('/api/commission', methods=['GET'])
def get_commission():
    conn = get_db()
    setting = conn.execute("SELECT value FROM settings WHERE key='agent_split_pct'").fetchone()
    agent_split_pct = float(setting['value']) if setting else 70.0

    leads = conn.execute(
        "SELECT * FROM leads WHERE stage IN ('accepted','completed') AND accepted_at IS NOT NULL"
    ).fetchall()
    conn.close()

    today = datetime.now()
    # Build the 6-month window starting this month
    months_data = {}
    for i in range(6):
        m = today.month - 1 + i
        y = today.year + m // 12
        m = m % 12 + 1
        months_data[f'{y}-{m:02d}'] = {'gross_total': 0, 'net_total': 0, 'deals': []}

    for lead in leads:
        try:
            acc_date = datetime.fromisoformat(lead['accepted_at'][:10])
        except Exception:
            continue
        payout = add_months(acc_date, 4)
        key = f'{payout.year}-{payout.month:02d}'
        if key not in months_data:
            continue
        price       = lead['final_accepted_price'] or lead['projected_value'] or 0
        comm_pct    = lead['commission_pct'] or 0
        gross_comm  = price * comm_pct / 100
        net_pct     = lead['net_commission_pct']
        net_comm    = gross_comm * net_pct / 100 if net_pct is not None else None
        months_data[key]['gross_total'] += gross_comm
        if net_comm is not None:
            months_data[key]['net_total'] += net_comm
        months_data[key]['deals'].append({
            'client_name':       lead['client_name'],
            'gross_comm':        round(gross_comm, 2),
            'net_comm':          round(net_comm, 2) if net_comm is not None else None,
            'net_commission_pct': lead['net_commission_pct'],
            'accepted_at':       lead['accepted_at'],
            'property_type':     lead['property_type'],
        })

    return jsonify({
        'months': months_data,
    })

@app.route('/api/leads/<int:lead_id>/viewings/<int:viewing_id>/probability', methods=['PUT'])
def update_viewing_probability(lead_id, viewing_id):
    data = request.json
    conn = get_db()
    conn.execute('UPDATE viewings SET win_probability=? WHERE id=? AND lead_id=?',
                 (data.get('win_probability'), viewing_id, lead_id))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/leads/<int:lead_id>/remarks', methods=['POST'])
def add_remark(lead_id):
    data = request.json
    conn = get_db()
    conn.execute('INSERT INTO stage_remarks (lead_id, stage, remark) VALUES (?,?,?)',
                 (lead_id, data['stage'], data['remark']))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

# --- Viewings ---

@app.route('/api/leads/<int:lead_id>/viewings', methods=['POST'])
def add_viewing(lead_id):
    data = request.json
    conn = get_db()
    conn.execute(
        'INSERT INTO viewings (lead_id, buyer_name, viewing_date, notes, counterpart_name, counterpart_number) VALUES (?,?,?,?,?,?)',
        (lead_id, data.get('buyer_name'), data['viewing_date'], data.get('notes'),
         data.get('counterpart_name'), data.get('counterpart_number'))
    )
    conn.execute("UPDATE leads SET updated_at=datetime('now') WHERE id=?", (lead_id,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/leads/<int:lead_id>/viewings/<int:viewing_id>', methods=['PUT'])
def update_viewing(lead_id, viewing_id):
    data = request.json
    conn = get_db()
    conn.execute('UPDATE viewings SET notes=? WHERE id=? AND lead_id=?',
                 (data.get('notes'), viewing_id, lead_id))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/leads/<int:lead_id>/viewings/<int:viewing_id>', methods=['DELETE'])
def delete_viewing(lead_id, viewing_id):
    conn = get_db()
    conn.execute('DELETE FROM viewings WHERE id=? AND lead_id=?', (viewing_id, lead_id))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

# --- Offers ---

@app.route('/api/leads/<int:lead_id>/offers', methods=['POST'])
def add_offer(lead_id):
    data = request.json
    conn = get_db()
    conn.execute(
        'INSERT INTO offers (lead_id, viewing_id, buyer_name, offer_price, notes) VALUES (?,?,?,?,?)',
        (lead_id, data.get('viewing_id'), data.get('buyer_name'),
         data['offer_price'], data.get('notes'))
    )
    conn.execute("UPDATE leads SET updated_at=datetime('now') WHERE id=?", (lead_id,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/leads/<int:lead_id>/offers/<int:offer_id>', methods=['DELETE'])
def delete_offer(lead_id, offer_id):
    conn = get_db()
    conn.execute('DELETE FROM offers WHERE id=? AND lead_id=?', (offer_id, lead_id))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

# --- Counter offers ---

@app.route('/api/leads/<int:lead_id>/counter_offers', methods=['POST'])
def add_counter_offer(lead_id):
    data = request.json
    conn = get_db()
    offer = conn.execute('SELECT buyer_name FROM offers WHERE id=?', (data.get('offer_id'),)).fetchone()
    buyer_name = offer['buyer_name'] if offer else None
    conn.execute(
        'INSERT INTO counter_offers (lead_id, offer_id, buyer_name, counter_price, notes) VALUES (?,?,?,?,?)',
        (lead_id, data.get('offer_id'), buyer_name, data['counter_price'], data.get('notes'))
    )
    conn.execute("UPDATE leads SET updated_at=datetime('now') WHERE id=?", (lead_id,))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/api/leads/<int:lead_id>/counter_offers/<int:co_id>', methods=['DELETE'])
def delete_counter_offer(lead_id, co_id):
    conn = get_db()
    conn.execute('DELETE FROM counter_offers WHERE id=? AND lead_id=?', (co_id, lead_id))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

# --- Accepted offer ---

@app.route('/api/leads/<int:lead_id>/accepted_offer', methods=['PUT'])
def set_accepted_offer(lead_id):
    data = request.json
    conn = get_db()
    conn.execute(
        "UPDATE leads SET accepted_offer_id=?, final_accepted_price=?, net_commission_pct=?, updated_at=datetime('now') WHERE id=?",
        (data.get('offer_id'), data.get('final_price'), data.get('net_commission_pct'), lead_id)
    )
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

# --- Static ---

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(debug=True, port=port)
