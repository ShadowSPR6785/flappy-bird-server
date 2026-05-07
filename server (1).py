"""
Flappy Bird – Servidor Local COMPLETO
  - Contas + sessões
  - Leaderboard global + por modo
  - Torneios diários (seed fixa)
  - Sistema de amigos
  - Notificações de recorde
Executa com: python3 server.py
Acede em:   http://localhost:5000
"""

import json, os, hashlib, secrets, datetime
from functools import wraps
from flask import Flask, request, jsonify, session, send_from_directory

BASE = os.path.dirname(os.path.abspath(__file__))
DB   = os.path.join(BASE, "db.json")

app = Flask(__name__, static_folder=os.path.join(BASE, "static"))
app.secret_key = "flappy_bird_local_secret_2024_xk9"  # fixo para sessões persistirem

# ──────────────────────────── BASE DE DADOS ───────────────────
def ler_db():
    if not os.path.exists(DB):
        return {"utilizadores": {}, "partidas": [], "amizades": {}}
    with open(DB, "r", encoding="utf-8") as f:
        d = json.load(f)
    if "amizades" not in d: d["amizades"] = {}
    return d

def gravar_db(dados):
    with open(DB, "w", encoding="utf-8") as f:
        json.dump(dados, f, indent=2, ensure_ascii=False)

def hash_pw(p): return hashlib.sha256(p.encode()).hexdigest()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "username" not in session:
            return jsonify({"erro": "Não autenticado"}), 401
        return f(*args, **kwargs)
    return decorated

# ──────────────────────────── ESTÁTICOS ───────────────────────
@app.route("/")
def index():
    return send_from_directory(os.path.join(BASE, "static"), "index.html")

@app.route("/static/<path:path>")
def static_files(path):
    return send_from_directory(os.path.join(BASE, "static"), path)

# ──────────────────────────── AUTH ────────────────────────────
@app.route("/api/registar", methods=["POST"])
def registar():
    d  = request.get_json(force=True)
    u  = (d.get("username") or "").strip().lower()
    pw = d.get("password") or ""
    dn = (d.get("display") or u).strip()
    if len(u) < 3:  return jsonify({"erro": "Username precisa de pelo menos 3 caracteres"}), 400
    if len(pw) < 4: return jsonify({"erro": "Password precisa de pelo menos 4 caracteres"}), 400
    if not u.isalnum(): return jsonify({"erro": "Username só pode ter letras e números"}), 400
    db = ler_db()
    if u in db["utilizadores"]: return jsonify({"erro": "Username já existe"}), 409
    db["utilizadores"][u] = {
        "password_hash": hash_pw(pw), "display": dn,
        "criado_em": datetime.datetime.now().isoformat(),
        "melhor_placar": 0, "total_partidas": 0, "total_mortes": 0,
        "total_canos": 0, "moedas": 0, "nivel": 1, "conquistas": [],
    }
    gravar_db(db)
    session["username"] = u; session["display"] = dn
    return jsonify({"ok": True, "display": dn})

@app.route("/api/login", methods=["POST"])
def login():
    d  = request.get_json(force=True)
    u  = (d.get("username") or "").strip().lower()
    pw = d.get("password") or ""
    db = ler_db()
    ut = db["utilizadores"].get(u)
    if not ut or ut["password_hash"] != hash_pw(pw):
        return jsonify({"erro": "Username ou password incorretos"}), 401
    session["username"] = u; session["display"] = ut["display"]
    return jsonify({"ok": True, "display": ut["display"],
                    "melhor_placar": ut["melhor_placar"],
                    "nivel": ut["nivel"], "moedas": ut["moedas"]})

@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear(); return jsonify({"ok": True})

@app.route("/api/eu")
def eu():
    if "username" not in session: return jsonify({"autenticado": False})
    db = ler_db(); u = db["utilizadores"].get(session["username"], {})
    return jsonify({"autenticado": True, "username": session["username"],
                    "display": session["display"],
                    "melhor_placar": u.get("melhor_placar", 0),
                    "total_partidas": u.get("total_partidas", 0),
                    "moedas": u.get("moedas", 0), "nivel": u.get("nivel", 1)})

# ──────────────────────────── PARTIDAS ────────────────────────
@app.route("/api/partida", methods=["POST"])
@login_required
def guardar_partida():
    d     = request.get_json(force=True)
    placar = int(d.get("placar", 0)); modo = d.get("modo", "Normal")
    canos  = int(d.get("canos", 0)); combo = int(d.get("combo_max", 0))
    nivel  = int(d.get("nivel", 1)); moedas = int(d.get("moedas", 0))
    db = ler_db(); u = db["utilizadores"][session["username"]]
    u["total_partidas"] += 1; u["total_canos"] += canos
    u["total_mortes"]   += 1; u["moedas"] += moedas
    u["nivel"] = max(u.get("nivel", 1), nivel)
    novo_recorde = placar > u["melhor_placar"]
    if novo_recorde: u["melhor_placar"] = placar
    db["partidas"].append({
        "username": session["username"], "display": session["display"],
        "placar": placar, "modo": modo, "canos": canos,
        "combo_max": combo, "moedas": moedas,
        "data": datetime.datetime.now().isoformat(),
    })
    if len(db["partidas"]) > 5000: db["partidas"] = db["partidas"][-5000:]
    gravar_db(db)
    return jsonify({"ok": True, "novo_recorde": novo_recorde})

# ──────────────────────────── LEADERBOARD ─────────────────────
@app.route("/api/leaderboard")
def leaderboard():
    db    = ler_db()
    modo  = request.args.get("modo", "todos")
    lim   = min(int(request.args.get("limite", 20)), 100)
    amigos_de = request.args.get("amigos_de")  # filtra por amigos

    if modo == "todos":
        ranking = []
        for uname, u in db["utilizadores"].items():
            if u["melhor_placar"] > 0:
                ranking.append({"username": uname, "display": u["display"],
                                 "melhor_placar": u["melhor_placar"],
                                 "total_partidas": u["total_partidas"],
                                 "nivel": u.get("nivel", 1)})
        ranking.sort(key=lambda x: x["melhor_placar"], reverse=True)
    else:
        melhores = {}
        for p in db["partidas"]:
            if p["modo"] != modo: continue
            un = p["username"]
            if un not in melhores or p["placar"] > melhores[un]["melhor_placar"]:
                melhores[un] = {"username": un, "display": p["display"],
                                "melhor_placar": p["placar"], "modo": modo,
                                "nivel": db["utilizadores"].get(un, {}).get("nivel", 1),
                                "total_partidas": db["utilizadores"].get(un, {}).get("total_partidas", 0)}
        ranking = sorted(melhores.values(), key=lambda x: x["melhor_placar"], reverse=True)

    # filtro amigos
    if amigos_de:
        lista_amigos = db["amizades"].get(amigos_de, []) + [amigos_de]
        ranking = [e for e in ranking if e["username"] in lista_amigos]

    for i, e in enumerate(ranking[:lim]): e["posicao"] = i + 1

    minha_pos = None
    if "username" in session:
        for i, e in enumerate(ranking):
            if e["username"] == session["username"]: minha_pos = i + 1; break

    return jsonify({"ranking": ranking[:lim], "minha_pos": minha_pos, "total": len(ranking)})

@app.route("/api/historico")
@login_required
def historico():
    db = ler_db(); uname = session["username"]
    lim = min(int(request.args.get("limite", 10)), 50)
    ps  = sorted([p for p in db["partidas"] if p["username"] == uname],
                 key=lambda x: x["data"], reverse=True)
    return jsonify({"partidas": ps[:lim]})

@app.route("/api/estatisticas")
@login_required
def estatisticas():
    db = ler_db(); uname = session["username"]; u = db["utilizadores"].get(uname, {})
    ps = [p for p in db["partidas"] if p["username"] == uname]
    modos_c = {}
    for p in ps: modos_c[p["modo"]] = modos_c.get(p["modo"], 0) + 1
    media = round(sum(p["placar"] for p in ps) / len(ps), 1) if ps else 0
    return jsonify({"melhor_placar": u.get("melhor_placar", 0),
                    "total_partidas": u.get("total_partidas", 0),
                    "total_canos": u.get("total_canos", 0),
                    "moedas": u.get("moedas", 0), "nivel": u.get("nivel", 1),
                    "media_placar": media, "modos_jogados": modos_c})

# ──────────────────────────── AMIGOS ──────────────────────────
@app.route("/api/amigos", methods=["GET"])
@login_required
def listar_amigos():
    db = ler_db(); uname = session["username"]
    amigos = db["amizades"].get(uname, [])
    lista  = []
    for a in amigos:
        u = db["utilizadores"].get(a)
        if u: lista.append({"username": a, "display": u["display"],
                             "melhor_placar": u["melhor_placar"],
                             "nivel": u.get("nivel", 1)})
    lista.sort(key=lambda x: x["melhor_placar"], reverse=True)
    return jsonify({"amigos": lista})

@app.route("/api/amigos/adicionar", methods=["POST"])
@login_required
def adicionar_amigo():
    d = request.get_json(force=True)
    alvo = (d.get("username") or "").strip().lower()
    uname = session["username"]
    if alvo == uname: return jsonify({"erro": "Não podes adicionar-te a ti próprio"}), 400
    db = ler_db()
    if alvo not in db["utilizadores"]: return jsonify({"erro": "Utilizador não encontrado"}), 404
    if uname not in db["amizades"]: db["amizades"][uname] = []
    if alvo in db["amizades"][uname]: return jsonify({"erro": "Já é teu amigo"}), 409
    db["amizades"][uname].append(alvo)
    # amizade mútua
    if alvo not in db["amizades"]: db["amizades"][alvo] = []
    if uname not in db["amizades"][alvo]: db["amizades"][alvo].append(uname)
    gravar_db(db)
    disp = db["utilizadores"][alvo]["display"]
    return jsonify({"ok": True, "display": disp})

@app.route("/api/amigos/remover", methods=["POST"])
@login_required
def remover_amigo():
    d = request.get_json(force=True)
    alvo  = (d.get("username") or "").strip().lower()
    uname = session["username"]
    db    = ler_db()
    if uname in db["amizades"] and alvo in db["amizades"][uname]:
        db["amizades"][uname].remove(alvo)
    if alvo in db["amizades"] and uname in db["amizades"][alvo]:
        db["amizades"][alvo].remove(uname)
    gravar_db(db)
    return jsonify({"ok": True})

@app.route("/api/utilizadores/procurar")
@login_required
def procurar_utilizadores():
    q  = (request.args.get("q") or "").strip().lower()
    db = ler_db()
    if len(q) < 2: return jsonify({"resultados": []})
    res = []
    amigos_atuais = db["amizades"].get(session["username"], [])
    for uname, u in db["utilizadores"].items():
        if uname == session["username"]: continue
        if q in uname or q in u["display"].lower():
            res.append({"username": uname, "display": u["display"],
                        "melhor_placar": u["melhor_placar"],
                        "ja_amigo": uname in amigos_atuais})
    res.sort(key=lambda x: x["melhor_placar"], reverse=True)
    return jsonify({"resultados": res[:10]})

# ──────────────────────────── TORNEIO ─────────────────────────
@app.route("/api/torneio/info")
def torneio_info():
    import hashlib as _h
    hoje  = datetime.date.today().isoformat()
    seed  = int(_h.md5(hoje.encode()).hexdigest(), 16) % (2**31)
    amanha = datetime.datetime.combine(
        datetime.date.today() + datetime.timedelta(days=1), datetime.time.min)
    resto  = amanha - datetime.datetime.now()
    horas  = resto.seconds // 3600; mins = (resto.seconds % 3600) // 60
    return jsonify({"data": hoje, "seed": seed,
                    "renova_em": f"{horas}h {mins}m"})

@app.route("/api/torneio/leaderboard")
def torneio_leaderboard():
    db   = ler_db()
    hoje = datetime.date.today().isoformat()
    ps   = [p for p in db["partidas"]
            if p["modo"] == "Torneio" and p["data"].startswith(hoje)]
    melhores = {}
    for p in ps:
        un = p["username"]
        if un not in melhores or p["placar"] > melhores[un]["melhor_placar"]:
            melhores[un] = {"username": un, "display": p["display"],
                            "melhor_placar": p["placar"]}
    ranking = sorted(melhores.values(), key=lambda x: x["melhor_placar"], reverse=True)
    for i, e in enumerate(ranking): e["posicao"] = i + 1
    minha_pos = None
    if "username" in session:
        for i, e in enumerate(ranking):
            if e["username"] == session["username"]: minha_pos = i + 1; break
    return jsonify({"ranking": ranking[:20], "minha_pos": minha_pos,
                    "data": hoje, "total": len(ranking)})

if __name__ == "__main__":
    os.makedirs(os.path.join(BASE, "static"), exist_ok=True)
    print("\n🐦 Flappy Bird Server — Versão Completa")
    print("   Acede em: http://localhost:5000\n")
    app.run(host="0.0.0.0", port=5000, debug=False)
