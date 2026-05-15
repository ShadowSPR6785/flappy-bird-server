"""
Flappy Bird – Servidor com MongoDB (dados persistentes)
"""
import os, hashlib, datetime
from functools import wraps
from flask import Flask, request, jsonify, session, send_from_directory

BASE   = os.path.dirname(os.path.abspath(__file__))
app    = Flask(__name__, static_folder=os.path.join(BASE,"static"))
app.secret_key = "flappy_bird_secret_2024_xk9"

# ── MONGODB ───────────────────────────────────────────────────
# Railway usa MONGO_URL, Atlas usa MONGO_URI
MONGO_URI = (os.environ.get("MONGO_URI") or
             os.environ.get("MONGO_URL") or
             os.environ.get("MONGODB_URL") or "")

_client = None
_db     = None

def get_db():
    global _client, _db
    if _db is None:
        from pymongo import MongoClient
        from urllib.parse import quote_plus, urlparse, urlunparse
        uri = MONGO_URI
        try:
            # corrigir caracteres especiais na password automaticamente
            p = urlparse(uri)
            if p.username and p.password:
                user = quote_plus(p.username)
                pw   = quote_plus(p.password)
                host = p.hostname
                port = f":{p.port}" if p.port else ""
                uri  = f"{p.scheme}://{user}:{pw}@{host}{port}{p.path}"
                if p.query: uri += f"?{p.query}"
        except: pass
        _client = MongoClient(uri,
                              serverSelectionTimeoutMS=8000,
                              connectTimeoutMS=8000,
                              socketTimeoutMS=8000)
        _db = _client["flappy_bird"]
    return _db

def users():    return get_db()["utilizadores"]
def partidas(): return get_db()["partidas"]
def amizades(): return get_db()["amizades"]

def hash_pw(p): return hashlib.sha256(p.encode()).hexdigest()

def login_required(f):
    @wraps(f)
    def dec(*a,**k):
        if "username" not in session:
            return jsonify({"erro":"Não autenticado"}),401
        return f(*a,**k)
    return dec

# ── ESTÁTICOS ─────────────────────────────────────────────────
@app.route("/api/health")
def health():
    try:
        get_db().command("ping")
        return jsonify({"ok": True, "db": "connected"})
    except Exception as e:
        return jsonify({"ok": False, "erro": str(e)}), 500
@app.route("/")
def index():
    return send_from_directory(os.path.join(BASE,"static"),"index.html")

@app.route("/static/<path:p>")
def static_files(p):
    return send_from_directory(os.path.join(BASE,"static"),p)

# ── AUTH ──────────────────────────────────────────────────────
@app.route("/api/registar", methods=["POST"])
def registar():
    d  = request.get_json(force=True)
    u  = (d.get("username") or "").strip().lower()
    pw = d.get("password") or ""
    dn = (d.get("display") or u).strip()
    if len(u)<3:    return jsonify({"erro":"Username precisa de pelo menos 3 caracteres"}),400
    if len(pw)<4:   return jsonify({"erro":"Password precisa de pelo menos 4 caracteres"}),400
    if not u.isalnum(): return jsonify({"erro":"Username só pode ter letras e números"}),400
    if users().find_one({"username":u}): return jsonify({"erro":"Username já existe"}),409
    users().insert_one({
        "username":u,"password_hash":hash_pw(pw),"display":dn,
        "criado_em":datetime.datetime.utcnow().isoformat(),
        "melhor_placar":0,"total_partidas":0,"total_mortes":0,
        "total_canos":0,"moedas":0,"nivel":1
    })
    session["username"]=u; session["display"]=dn
    return jsonify({"ok":True,"display":dn})

@app.route("/api/login", methods=["POST"])
def login():
    d  = request.get_json(force=True)
    u  = (d.get("username") or "").strip().lower()
    pw = d.get("password") or ""
    ut = users().find_one({"username":u})
    if not ut or ut["password_hash"]!=hash_pw(pw):
        return jsonify({"erro":"Username ou password incorretos"}),401
    session["username"]=u; session["display"]=ut["display"]
    return jsonify({"ok":True,"display":ut["display"],
                    "melhor_placar":ut["melhor_placar"],
                    "nivel":ut["nivel"],"moedas":ut["moedas"]})

@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear(); return jsonify({"ok":True})

@app.route("/api/eu")
def eu():
    if "username" not in session: return jsonify({"autenticado":False})
    u = users().find_one({"username":session["username"]},{"_id":0})
    if not u: return jsonify({"autenticado":False})
    return jsonify({"autenticado":True,"username":session["username"],
                    "display":session["display"],
                    "melhor_placar":u.get("melhor_placar",0),
                    "total_partidas":u.get("total_partidas",0),
                    "moedas":u.get("moedas",0),"nivel":u.get("nivel",1)})

# ── PARTIDAS ──────────────────────────────────────────────────
@app.route("/api/partida", methods=["POST"])
@login_required
def guardar_partida():
    d      = request.get_json(force=True)
    placar = int(d.get("placar",0)); modo=d.get("modo","Normal")
    canos  = int(d.get("canos",0)); combo=int(d.get("combo_max",0))
    nivel  = int(d.get("nivel",1)); moedas=int(d.get("moedas",0))
    uname  = session["username"]
    u      = users().find_one({"username":uname})
    novo_recorde = placar > u.get("melhor_placar",0)
    users().update_one({"username":uname},{"$inc":{
        "total_partidas":1,"total_canos":canos,"total_mortes":1,"moedas":moedas},
        "$max":{"melhor_placar":placar,"nivel":nivel}})
    partidas().insert_one({
        "username":uname,"display":session["display"],
        "placar":placar,"modo":modo,"canos":canos,
        "combo_max":combo,"moedas":moedas,
        "data":datetime.datetime.utcnow().isoformat()
    })
    return jsonify({"ok":True,"novo_recorde":novo_recorde})

# ── LEADERBOARD ───────────────────────────────────────────────
@app.route("/api/leaderboard")
def leaderboard():
    modo  = request.args.get("modo","todos")
    lim   = min(int(request.args.get("limite",20)),100)
    amigos_de = request.args.get("amigos_de")

    if modo=="todos":
        pipeline=[
            {"$sort":{"melhor_placar":-1}},
            {"$limit":lim},
            {"$project":{"_id":0,"username":1,"display":1,
                         "melhor_placar":1,"total_partidas":1,"nivel":1}}
        ]
        ranking=list(users().aggregate(pipeline))
    else:
        pipeline=[
            {"$match":{"modo":modo}},
            {"$group":{"_id":"$username","display":{"$first":"$display"},
                       "melhor_placar":{"$max":"$placar"}}},
            {"$sort":{"melhor_placar":-1}},{"$limit":lim},
            {"$project":{"_id":0,"username":"$_id","display":1,"melhor_placar":1}}
        ]
        ranking=list(partidas().aggregate(pipeline))

    if amigos_de:
        am=amizades().find_one({"username":amigos_de})
        lista=([amigos_de]+am.get("amigos",[])) if am else [amigos_de]
        ranking=[e for e in ranking if e.get("username") in lista]

    minha_pos=None
    for i,e in enumerate(ranking):
        e["posicao"]=i+1
        if "username" in session and e.get("username")==session["username"]:
            minha_pos=i+1

    return jsonify({"ranking":ranking,"minha_pos":minha_pos,"total":len(ranking)})

@app.route("/api/historico")
@login_required
def historico():
    lim = min(int(request.args.get("limite",10)),50)
    ps  = list(partidas().find(
        {"username":session["username"]},{"_id":0}
    ).sort("data",-1).limit(lim))
    return jsonify({"partidas":ps})

@app.route("/api/estatisticas")
@login_required
def estatisticas():
    u  = users().find_one({"username":session["username"]},{"_id":0})
    ps = list(partidas().find({"username":session["username"]},{"_id":0}))
    modos_c={}
    for p in ps: modos_c[p["modo"]]=modos_c.get(p["modo"],0)+1
    media=round(sum(p["placar"] for p in ps)/len(ps),1) if ps else 0
    return jsonify({"melhor_placar":u.get("melhor_placar",0),
                    "total_partidas":u.get("total_partidas",0),
                    "total_canos":u.get("total_canos",0),
                    "moedas":u.get("moedas",0),"nivel":u.get("nivel",1),
                    "media_placar":media,"modos_jogados":modos_c})

# ── AMIGOS ────────────────────────────────────────────────────
def pedidos_col(): return get_db()["pedidos_amizade"]

@app.route("/api/amigos")
@login_required
def listar_amigos():
    uname = session["username"]
    doc   = amizades().find_one({"username":uname}) or {}
    lista_u = doc.get("amigos",[])
    lista=[]
    for a in lista_u:
        u=users().find_one({"username":a},{"_id":0,"username":1,"display":1,"melhor_placar":1,"nivel":1})
        if u: lista.append(u)
    lista.sort(key=lambda x:x.get("melhor_placar",0),reverse=True)
    return jsonify({"amigos":lista})

@app.route("/api/amigos/pedidos")
@login_required
def listar_pedidos():
    uname = session["username"]
    # pedidos recebidos (outros enviaram para mim)
    recebidos_docs = list(pedidos_col().find({"para":uname,"estado":"pendente"},{"_id":0}))
    recebidos = []
    for p in recebidos_docs:
        u = users().find_one({"username":p["de"]},{"_id":0,"display":1,"nivel":1,"melhor_placar":1})
        recebidos.append({
            "de": p["de"],
            "display": u.get("display",p["de"]) if u else p["de"],
            "nivel": u.get("nivel",1) if u else 1,
            "melhor_placar": u.get("melhor_placar",0) if u else 0,
            "data": p.get("data","")
        })
    # pedidos enviados por mim
    enviados_docs = list(pedidos_col().find({"de":uname,"estado":"pendente"},{"_id":0}))
    enviados = [{"para": p["para"]} for p in enviados_docs]
    return jsonify({"recebidos":recebidos,"enviados":enviados})

@app.route("/api/amigos/pedir", methods=["POST"])
@login_required
def pedir_amigo():
    alvo  = (request.get_json(force=True).get("username") or "").strip().lower()
    uname = session["username"]
    if alvo==uname: return jsonify({"erro":"Não podes adicionar-te a ti próprio"}),400
    alvo_doc = users().find_one({"username":alvo})
    if not alvo_doc: return jsonify({"erro":"Utilizador não encontrado"}),404
    # verificar se já são amigos
    am_doc = amizades().find_one({"username":uname}) or {}
    if alvo in am_doc.get("amigos",[]):
        return jsonify({"erro":"Já são amigos"}),400
    # verificar se o alvo já nos enviou pedido → aceite automático
    pedido_inverso = pedidos_col().find_one({"de":alvo,"para":uname,"estado":"pendente"})
    if pedido_inverso:
        pedidos_col().update_one({"_id":pedido_inverso["_id"]},{"$set":{"estado":"aceite"}})
        amizades().update_one({"username":uname},{"$addToSet":{"amigos":alvo}},upsert=True)
        amizades().update_one({"username":alvo},{"$addToSet":{"amigos":uname}},upsert=True)
        return jsonify({"ok":True,"aceite_automatico":True,"display":alvo_doc.get("display",alvo)})
    # verificar se já existe pedido pendente nosso
    existente = pedidos_col().find_one({"de":uname,"para":alvo,"estado":"pendente"})
    if existente: return jsonify({"erro":"Pedido já enviado"}),400
    pedidos_col().insert_one({
        "de":uname,"para":alvo,"estado":"pendente",
        "data":datetime.datetime.utcnow().isoformat()
    })
    return jsonify({"ok":True,"aceite_automatico":False,"display":alvo_doc.get("display",alvo)})

@app.route("/api/amigos/responder", methods=["POST"])
@login_required
def responder_pedido():
    d     = request.get_json(force=True)
    de    = (d.get("de") or "").strip().lower()
    aceite= bool(d.get("aceite",False))
    uname = session["username"]
    pedido = pedidos_col().find_one({"de":de,"para":uname,"estado":"pendente"})
    if not pedido: return jsonify({"erro":"Pedido não encontrado"}),404
    novo_estado = "aceite" if aceite else "recusado"
    pedidos_col().update_one({"_id":pedido["_id"]},{"$set":{"estado":novo_estado}})
    if aceite:
        amizades().update_one({"username":uname},{"$addToSet":{"amigos":de}},upsert=True)
        amizades().update_one({"username":de},  {"$addToSet":{"amigos":uname}},upsert=True)
    return jsonify({"ok":True,"aceite":aceite})

@app.route("/api/amigos/remover", methods=["POST"])
@login_required
def remover_amigo():
    alvo  = (request.get_json(force=True).get("username") or "").strip().lower()
    uname = session["username"]
    amizades().update_one({"username":uname},{"$pull":{"amigos":alvo}})
    amizades().update_one({"username":alvo}, {"$pull":{"amigos":uname}})
    return jsonify({"ok":True})

@app.route("/api/utilizadores/procurar")
@login_required
def procurar():
    q     = (request.args.get("q") or "").strip().lower()
    uname = session["username"]
    if len(q)<2: return jsonify({"resultados":[]})
    docs = list(users().find(
        {"username":{"$regex":q,"$options":"i"},"$expr":{"$ne":["$username",uname]}},
        {"_id":0,"username":1,"display":1,"melhor_placar":1}
    ).limit(10))
    am_doc = amizades().find_one({"username":uname}) or {}
    amigos_atuais = am_doc.get("amigos",[])
    # pedidos enviados por mim
    enviados_docs = list(pedidos_col().find({"de":uname,"estado":"pendente"},{"_id":0,"para":1}))
    enviados_set  = set(p["para"] for p in enviados_docs)
    for d in docs:
        d["ja_amigo"]     = d["username"] in amigos_atuais
        d["pedido_enviado"]= d["username"] in enviados_set
    docs.sort(key=lambda x:x.get("melhor_placar",0),reverse=True)
    return jsonify({"resultados":docs})

# ── TORNEIO ───────────────────────────────────────────────────
@app.route("/api/torneio/info")
def torneio_info():
    import hashlib as _h
    hoje  = datetime.date.today().isoformat()
    seed  = int(_h.md5(hoje.encode()).hexdigest(),16)%(2**31)
    amanha= datetime.datetime.combine(
        datetime.date.today()+datetime.timedelta(days=1),datetime.time.min)
    resto = amanha-datetime.datetime.utcnow()
    horas = resto.seconds//3600; mins=(resto.seconds%3600)//60
    return jsonify({"data":hoje,"seed":seed,"renova_em":f"{horas}h {mins}m"})

@app.route("/api/torneio/leaderboard")
def torneio_leaderboard():
    hoje = datetime.date.today().isoformat()
    pipeline=[
        {"$match":{"modo":"Torneio","data":{"$regex":f"^{hoje}"}}},
        {"$group":{"_id":"$username","display":{"$first":"$display"},
                   "melhor_placar":{"$max":"$placar"}}},
        {"$sort":{"melhor_placar":-1}},{"$limit":20},
        {"$project":{"_id":0,"username":"$_id","display":1,"melhor_placar":1}}
    ]
    ranking=list(partidas().aggregate(pipeline))
    minha_pos=None
    for i,e in enumerate(ranking):
        e["posicao"]=i+1
        if "username" in session and e.get("username")==session["username"]:
            minha_pos=i+1
    return jsonify({"ranking":ranking,"minha_pos":minha_pos,
                    "data":hoje,"total":len(ranking)})

# ── DELETAR CONTA ─────────────────────────────────────────────
@app.route("/api/deletar_conta", methods=["POST"])
@login_required
def deletar_conta():
    d     = request.get_json(force=True)
    pw    = d.get("password") or ""
    uname = session["username"]
    u     = users().find_one({"username": uname})
    if not u or u["password_hash"] != hash_pw(pw):
        return jsonify({"erro": "Password incorreta"}), 401
    users().delete_one({"username": uname})
    partidas().delete_many({"username": uname})
    amizades().delete_one({"username": uname})
    amizades().update_many({}, {"$pull": {"amigos": uname}})
    session.clear()
    return jsonify({"ok": True})

# ── SAVE / LOAD DE DADOS DO JOGO ─────────────────────────────
@app.route("/api/save", methods=["POST"])
@login_required
def save_dados():
    d     = request.get_json(force=True)
    uname = session["username"]
    # guardar todos os dados do jogo no perfil do utilizador
    users().update_one({"username": uname}, {"$set": {
        "save_dados": d,
        "save_atualizado": datetime.datetime.utcnow().isoformat()
    }})
    return jsonify({"ok": True})

@app.route("/api/load")
@login_required
def load_dados():
    uname = session["username"]
    u     = users().find_one({"username": uname}, {"_id": 0, "save_dados": 1})
    if not u or "save_dados" not in u:
        return jsonify({"ok": False, "dados": None})
    return jsonify({"ok": True, "dados": u["save_dados"]})

if __name__=="__main__":
    print("\n🐦 Flappy Bird Server (MongoDB)")
    print("   Acede em: http://localhost:5000\n")
    app.run(host="0.0.0.0",port=5000,debug=False)
