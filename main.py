tfrom telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from datetime import datetime
import threading
import os
import requests
from flask import Flask, request
from threading import Thread

# ================= CONFIG =================
TOKEN = os.getenv("TELEGRAM_TOKEN")
ESTOQUE_DIR = "estoque"
RESERVA_DIR = "fila_reserva"
ADMINS = [8276989322]
GRUPO_TELEGRAM = -1003534782614

STATE_DEPOSITAR = "depositar_valor"
STATE_TICKET = "ticket_tipo"

bonus_ativo = False
bonus_percentual = 0
bonus_valor_minimo = 0

os.makedirs(ESTOQUE_DIR, exist_ok=True)
os.makedirs(RESERVA_DIR, exist_ok=True)
lock_estoque = threading.Lock()

udef get_saldo(user_id):
    cursor.execute("SELECT saldo FROM usuarios WHERE user_id=%s", (user_id,))
    r = cursor.fetchone()
    return float(r[0]) if r else 0.0

def add_saldo(user_id, valor):
    cursor.execute("""
        INSERT INTO usuarios (user_id, saldo)
        VALUES (%s,%s)
        ON CONFLICT (user_id)
        DO UPDATE SET saldo = usuarios.saldo + %s
    """, (user_id, valor, valor))

def sub_saldo(user_id, valor):
    cursor.execute(
        "UPDATE usuarios SET saldo = saldo - %s WHERE user_id=%s",
        (valor, user_id)
    )


produtos = {
    "produtos": ["mix_fisicos", "mais_10_fisicos", "pedidos_digitais"]
}

produtos_info = {
    "mix_fisicos": {"nome": "MIX PEDIDOS FÍSICOS 🎲", "preco": 125.0},
    "pedidos_digitais": {"nome": "PEDIDOS DIGITAIS (ASSINATURA) 🍿🎥", "preco": 75.0},
    "mais_10_fisicos": {"nome": "+10 PEDIDOS FÍSICOS 🥇💎", "preco": 155.0},
}


ASAAS_API_KEY = os.getenv("ASAAS_API_KEY")

def criar_cobranca_pix(valor, user_id):
    url = "https://api.asaas.com/v3/payments"
    headers = {
        "Content-Type": "application/json",
        "access_token": ASAAS_API_KEY
    }
    payload = {
        "billingType": "PIX",
        "value": valor,
        "description": "Deposito no bot",
        "externalReference": str(user_id)
    }
    r = requests.post(url, json=payload, headers=headers)
    data = r.json()
    pid = data["id"]
    pix = requests.get(f"https://api.asaas.com/v3/payments/{pid}/pixQrCode", headers=headers).json()
    return pix

# ================= UTIL =================

def is_admin(user_id):
    return user_id in ADMINS

def init_usuario(user):
    if user.id not in usuarios:
        usuarios[user.id] = {
            "nome": user.full_name,
            "username": user.username or "",
            "saldo": 0.0,
            "compras": [],
            "registro": datetime.now(),
        }

def contar_estoque(produto):
    caminho = f"{ESTOQUE_DIR}/{produto}.txt"
    if not os.path.exists(caminho):
        return 0
    with open(caminho, "r", encoding="utf-8") as f:
        return len([l for l in f if l.strip()])

def retirar_item_estoque(produto):
    caminho = f"{ESTOQUE_DIR}/{produto}.txt"
    if not os.path.exists(caminho):
        return None
    with lock_estoque:
        with open(caminho, "r", encoding="utf-8") as f:
            linhas = f.readlines()
        if not linhas:
            return None
        item = linhas.pop(0)
        with open(caminho, "w", encoding="utf-8") as f:
            f.writelines(linhas)
    return item.strip()

# ================= SAFE EDIT =================

async def safe_edit_message(query, texto, teclado=None, parse_mode="Markdown"):
    try:
        await query.edit_message_text(texto, reply_markup=teclado, parse_mode=parse_mode)
    except:
        await query.message.reply_text(texto, reply_markup=teclado, parse_mode=parse_mode)

# ================= BOT MENUS =================

async def start_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    init_usuario(user)

    teclado = InlineKeyboardMarkup([ 
        [InlineKeyboardButton("🛒 Loja", callback_data="menu_loja")],
        [InlineKeyboardButton("💰 Saldo", callback_data="menu_saldo")],
        [
            InlineKeyboardButton("📦 Meus pedidos", callback_data="menu_pedidos"),
            InlineKeyboardButton("👤 Perfil", callback_data="menu_perfil")
        ],
        [InlineKeyboardButton("🆘 Suporte", callback_data="menu_suporte")]
    ])

    texto = (
        f"👋 Olá, *{user.full_name}*\n\n"
        "💻🔥 ®RC STORE – BOT OFICIAL ®🔥💻\n\n"
        "Bem-vindo à maior plataforma de produtos digitais!"
    )

    url_img = "https://i.postimg.cc/Gt47J7p0/Screenshot-1.png"

    if update.message:
        await update.message.reply_photo(
            photo=url_img,
            caption=texto,
            reply_markup=teclado,
            parse_mode="Markdown"
        )
    else:
        query = update.callback_query
        await query.answer()
        await query.edit_message_media(
            media=InputMediaPhoto(
                media=url_img,
                caption=texto,
                parse_mode="Markdown"
            ),
            reply_markup=teclado
        )

# ================= CALLBACK HANDLER =================

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    init_usuario(user)
    data = query.data

    if data == "menu_loja":
        teclado = InlineKeyboardMarkup([
            [InlineKeyboardButton("📁 Produtos", callback_data="cat_produtos")],
            [InlineKeyboardButton("🗂 Reserva", callback_data="cat_reserva")],
            [InlineKeyboardButton("🔙 Voltar", callback_data="voltar_inicio")]
        ])
        await safe_edit_message(query, "Escolha uma categoria para ver os produtos disponíveis:", teclado)
        return

    if data == "cat_produtos":
        teclado = []
        for p in produtos["produtos"]:
            estoque = contar_estoque(p)
            teclado.append([InlineKeyboardButton(f"{produtos_info[p]['nome']} ({estoque})", callback_data=f"comprar_{p}")])
        teclado.append([InlineKeyboardButton("🔙 Voltar", callback_data="menu_loja")])
        await safe_edit_message(query, "📦 Produtos disponíveis:", InlineKeyboardMarkup(teclado))
        return

    if data.startswith("comprar_"):
        produto = data.split("_", 1)[1]
        u = usuarios[user.id]
        preco = produtos_info[produto]['preco']
        
        if u['saldo'] < preco:
            await safe_edit_message(query, "❌ Saldo insuficiente para a compra.")
            return

        estoque = contar_estoque(produto)
        if estoque == 0:
            await safe_edit_message(query, "❌ Estoque insuficiente.")
            return

        # Retirar um item do estoque
        retirar_item_estoque(produto)

        # Deduzir o valor do saldo
        u['saldo'] -= preco

        # Registrar a compra
        u['compras'].append(produtos_info[produto]['nome'])

        # Responder com confirmação
        await safe_edit_message(query, f"✅ Compra realizada com sucesso!\nProduto: {produtos_info[produto]['nome']}\nPreço: R$ {preco:.2f}")

        return

    if data == "menu_saldo":
        u = usuarios[user.id]
        texto = f"💰 Seu saldo: R$ {u['saldo']:.2f}\n⚡ Recarregue via PIX e receba bônus!"
        teclado = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Adicionar saldo", callback_data="adicionar_saldo")],
            [InlineKeyboardButton("🔙 Voltar", callback_data="voltar_inicio")]
        ])
        await safe_edit_message(query, texto, teclado)
        return

    if data == "adicionar_saldo":
        context.user_data[STATE_DEPOSITAR] = True
        await query.message.reply_text("Digite o valor para adicionar ao saldo:")
        return

    if data == "voltar_inicio":
        await start_menu(update, context)
        return

    if data == "menu_pedidos":
        await safe_edit_message(query, "📦 Aqui estão os seus pedidos recentes!", InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="voltar_inicio")]]))
        return

    if data == "menu_perfil":
        u = usuarios[user.id]
        compras = "\n".join(u["compras"]) if u["compras"] else "Nenhuma compra ainda"
        texto = (
            f"👤 *Perfil do Usuário*\n\n"
            f"🆔 ID: {user.id}\n"
            f"📛 Nome: {user.full_name}\n"
            f"💻 Username: @{user.username or 'Não definido'}\n"
            f"💰 Saldo: R$ {u['saldo']:.2f}\n"
            f"🛒 Compras efetuadas:\n{compras}\n"
            f"📅 Registrado em: {u['registro'].strftime('%d/%m/%Y %H:%M:%S')}"
        )
        teclado = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="voltar_inicio")]])
        await safe_edit_message(query, texto, teclado)
        return

    if data == "menu_suporte":
        await safe_edit_message(
            query,
            "🆘 *SUPORTE ®️RC Store®️*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "💡 Selecione o tipo abaixo para abrir um ticket.\n\n"
            "Nosso atendimento é feito via Telegram:\n"
            "@RC_Store_logins\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("🔐 Problema com conta", url="https://t.me/RC_Store_logins")],
                [InlineKeyboardButton("💰 Problema com pagamento", url="https://t.me/RC_Store_logins")],
                [InlineKeyboardButton("❓ Dúvida geral", url="https://t.me/RC_Store_logins")],
                [InlineKeyboardButton("🔙 Voltar", callback_data="voltar_inicio")]
            ])
        )
        return

# ================= COMANDO /bonus =================

async def bonus_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    
    try:
        global bonus_percentual, bonus_valor_minimo
        bonus_percentual = float(context.args[0])
        bonus_valor_minimo = float(context.args[1])

        global bonus_ativo
        bonus_ativo = True

        await update.message.reply_text(f"🎁 Bônus ativo: {bonus_percentual}% para depósitos a partir de R$ {bonus_valor_minimo:.2f}")
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Uso correto: /bonus <percentual> <valor_minimo>\nExemplo: /bonus 30 300")

# ================= RECEBER VALOR =================

async def receber_valor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    init_usuario(user)

    if STATE_DEPOSITAR in context.user_data:
        try:
            valor = float(update.message.text)
            bonus = 0

            if bonus_ativo and valor >= bonus_valor_minimo:
                bonus = valor * (bonus_percentual / 100)

            pix = criar_cobranca_pix(valor, user.id)
            payload_pix = pix['payload']
            context.user_data.pop(STATE_DEPOSITAR)

            await update.message.reply_text(f"💳 Pagamento PIX\nValor: R$ {valor:.2f}\n\nCopie e cole este código no seu banco:\n{payload_pix}")
        except:
            await update.message.reply_text("❌ Valor inválido.")
        return

# ================= COMANDOS ADMIN =================

async def add_estoque(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        produto = context.args[0]
        login, imgs = context.args[1].split("/")
        imagens = imgs.split(",")

        with open(f"{ESTOQUE_DIR}/{produto}.txt", "a", encoding="utf-8") as f:
            f.write("||".join([login] + imagens) + "\n")

        await update.message.reply_text("✅ Item adicionado ao estoque.")
        for img in imagens:
            await context.bot.send_photo(GRUPO_TELEGRAM, img)

    except:
        await update.message.reply_text("❌ Uso correto:\n/add_estoque produto login:senha/url1,url2")

# ================= MAIN =================


app_web = Flask(__name__)

@app_web.route("/")
def home():
    return "Bot online", 200

@app_web.route("/webhook_asaas", methods=["POST"])
def webhook():
    data = request.json
    if data.get("event") == "PAYMENT_RECEIVED":
        user_id = int(data["externalReference"])
        valor = float(data["value"])
        usuarios[user_id]["saldo"] += valor
    return "ok", 200


def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start_menu))
    app.add_handler(CommandHandler("add_estoque", add_estoque))
    app.add_handler(CommandHandler("bonus", bonus_cmd))

    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), receber_valor))

    print("🤖 Bot rodando...")
    app.run_polling()

if __name__ == "__main__":
    import os
PORT = int(os.environ.get("PORT", 3000))
Thread(target=lambda: app_web.run(host="0.0.0.0", port=PORT)).start()

    main()
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from datetime import datetime
import threading
import os
import requests
from flask import Flask, request
from threading import Thread

# ================= CONFIG =================

TOKEN = os.getenv("TELEGRAM_TOKEN")
ESTOQUE_DIR = "estoque"
RESERVA_DIR = "fila_reserva"
ADMINS = [8276989322]
GRUPO_TELEGRAM = -1003534782614

STATE_DEPOSITAR = "depositar_valor"
STATE_TICKET = "ticket_tipo"

bonus_ativo = False
bonus_percentual = 0
bonus_valor_minimo = 0

os.makedirs(ESTOQUE_DIR, exist_ok=True)
os.makedirs(RESERVA_DIR, exist_ok=True)
lock_estoque = threading.Lock()

usuarios = {}

produtos = {
    "produtos": ["mix_fisicos", "mais_10_fisicos", "pedidos_digitais"]
}

produtos_info = {
    "mix_fisicos": {"nome": "MIX PEDIDOS FÍSICOS 🎲", "preco": 125.0},
    "pedidos_digitais": {"nome": "PEDIDOS DIGITAIS (ASSINATURA) 🍿🎥", "preco": 75.0},
    "mais_10_fisicos": {"nome": "+10 PEDIDOS FÍSICOS 🥇💎", "preco": 155.0},
}


ASAAS_API_KEY = os.getenv("ASAAS_API_KEY")

def criar_cobranca_pix(valor, user_id):
    url = "https://api.asaas.com/v3/payments"
    headers = {
        "Content-Type": "application/json",
        "access_token": ASAAS_API_KEY
    }
    payload = {
        "billingType": "PIX",
        "value": valor,
        "description": "Deposito no bot",
        "externalReference": str(user_id)
    }
    r = requests.post(url, json=payload, headers=headers)
    data = r.json()
    pid = data["id"]
    pix = requests.get(f"https://api.asaas.com/v3/payments/{pid}/pixQrCode", headers=headers).json()
    return pix

# ================= UTIL =================

def is_admin(user_id):
    return user_id in ADMINS

def init_usuario(user):
    if user.id not in usuarios:
        usuarios[user.id] = {
            "nome": user.full_name,
            "username": user.username or "",
            "saldo": 0.0,
            "compras": [],
            "registro": datetime.now(),
        }

def contar_estoque(produto):
    caminho = f"{ESTOQUE_DIR}/{produto}.txt"
    if not os.path.exists(caminho):
        return 0
    with open(caminho, "r", encoding="utf-8") as f:
        return len([l for l in f if l.strip()])

def retirar_item_estoque(produto):
    caminho = f"{ESTOQUE_DIR}/{produto}.txt"
    if not os.path.exists(caminho):
        return None
    with lock_estoque:
        with open(caminho, "r", encoding="utf-8") as f:
            linhas = f.readlines()
        if not linhas:
            return None
        item = linhas.pop(0)
        with open(caminho, "w", encoding="utf-8") as f:
            f.writelines(linhas)
    return item.strip()

# ================= SAFE EDIT =================

async def safe_edit_message(query, texto, teclado=None, parse_mode="Markdown"):
    try:
        await query.edit_message_text(texto, reply_markup=teclado, parse_mode=parse_mode)
    except:
        await query.message.reply_text(texto, reply_markup=teclado, parse_mode=parse_mode)

# ================= BOT MENUS =================

async def start_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    init_usuario(user)

    teclado = InlineKeyboardMarkup([ 
        [InlineKeyboardButton("🛒 Loja", callback_data="menu_loja")],
        [InlineKeyboardButton("💰 Saldo", callback_data="menu_saldo")],
        [
            InlineKeyboardButton("📦 Meus pedidos", callback_data="menu_pedidos"),
            InlineKeyboardButton("👤 Perfil", callback_data="menu_perfil")
        ],
        [InlineKeyboardButton("🆘 Suporte", callback_data="menu_suporte")]
    ])

    texto = (
        f"👋 Olá, *{user.full_name}*\n\n"
        "💻🔥 ®RC STORE – BOT OFICIAL ®🔥💻\n\n"
        "Bem-vindo à maior plataforma de produtos digitais!"
    )

    url_img = "https://i.postimg.cc/Gt47J7p0/Screenshot-1.png"

    if update.message:
        await update.message.reply_photo(
            photo=url_img,
            caption=texto,
            reply_markup=teclado,
            parse_mode="Markdown"
        )
    else:
        query = update.callback_query
        await query.answer()
        await query.edit_message_media(
            media=InputMediaPhoto(
                media=url_img,
                caption=texto,
                parse_mode="Markdown"
            ),
            reply_markup=teclado
        )

# ================= CALLBACK HANDLER =================

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    init_usuario(user)
    data = query.data

    if data == "menu_loja":
        teclado = InlineKeyboardMarkup([
            [InlineKeyboardButton("📁 Produtos", callback_data="cat_produtos")],
            [InlineKeyboardButton("🗂 Reserva", callback_data="cat_reserva")],
            [InlineKeyboardButton("🔙 Voltar", callback_data="voltar_inicio")]
        ])
        await safe_edit_message(query, "Escolha uma categoria para ver os produtos disponíveis:", teclado)
        return

    if data == "cat_produtos":
        teclado = []
        for p in produtos["produtos"]:
            estoque = contar_estoque(p)
            teclado.append([InlineKeyboardButton(f"{produtos_info[p]['nome']} ({estoque})", callback_data=f"comprar_{p}")])
        teclado.append([InlineKeyboardButton("🔙 Voltar", callback_data="menu_loja")])
        await safe_edit_message(query, "📦 Produtos disponíveis:", InlineKeyboardMarkup(teclado))
        return

    if data.startswith("comprar_"):
        produto = data.split("_", 1)[1]
        u = usuarios[user.id]
        preco = produtos_info[produto]['preco']
        
        if u['saldo'] < preco:
            await safe_edit_message(query, "❌ Saldo insuficiente para a compra.")
            return

        estoque = contar_estoque(produto)
        if estoque == 0:
            await safe_edit_message(query, "❌ Estoque insuficiente.")
            return

        # Retirar um item do estoque
        retirar_item_estoque(produto)

        # Deduzir o valor do saldo
        u['saldo'] -= preco

        # Registrar a compra
        u['compras'].append(produtos_info[produto]['nome'])

        # Responder com confirmação
        await safe_edit_message(query, f"✅ Compra realizada com sucesso!\nProduto: {produtos_info[produto]['nome']}\nPreço: R$ {preco:.2f}")

        return

    if data == "menu_saldo":
        u = usuarios[user.id]
        texto = f"💰 Seu saldo: R$ {u['saldo']:.2f}\n⚡ Recarregue via PIX e receba bônus!"
        teclado = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Adicionar saldo", callback_data="adicionar_saldo")],
            [InlineKeyboardButton("🔙 Voltar", callback_data="voltar_inicio")]
        ])
        await safe_edit_message(query, texto, teclado)
        return

    if data == "adicionar_saldo":
        context.user_data[STATE_DEPOSITAR] = True
        await query.message.reply_text("Digite o valor para adicionar ao saldo:")
        return

    if data == "voltar_inicio":
        await start_menu(update, context)
        return

    if data == "menu_pedidos":
        await safe_edit_message(query, "📦 Aqui estão os seus pedidos recentes!", InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="voltar_inicio")]]))
        return

    if data == "menu_perfil":
        u = usuarios[user.id]
        compras = "\n".join(u["compras"]) if u["compras"] else "Nenhuma compra ainda"
        texto = (
            f"👤 *Perfil do Usuário*\n\n"
            f"🆔 ID: {user.id}\n"
            f"📛 Nome: {user.full_name}\n"
            f"💻 Username: @{user.username or 'Não definido'}\n"
            f"💰 Saldo: R$ {u['saldo']:.2f}\n"
            f"🛒 Compras efetuadas:\n{compras}\n"
            f"📅 Registrado em: {u['registro'].strftime('%d/%m/%Y %H:%M:%S')}"
        )
        teclado = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Voltar", callback_data="voltar_inicio")]])
        await safe_edit_message(query, texto, teclado)
        return

    if data == "menu_suporte":
        await safe_edit_message(
            query,
            "🆘 *SUPORTE ®️RC Store®️*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "💡 Selecione o tipo abaixo para abrir um ticket.\n\n"
            "Nosso atendimento é feito via Telegram:\n"
            "@RC_Store_logins\n\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("🔐 Problema com conta", url="https://t.me/RC_Store_logins")],
                [InlineKeyboardButton("💰 Problema com pagamento", url="https://t.me/RC_Store_logins")],
                [InlineKeyboardButton("❓ Dúvida geral", url="https://t.me/RC_Store_logins")],
                [InlineKeyboardButton("🔙 Voltar", callback_data="voltar_inicio")]
            ])
        )
        return

# ================= COMANDO /bonus =================

async def bonus_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    
    try:
        global bonus_percentual, bonus_valor_minimo
        bonus_percentual = float(context.args[0])
        bonus_valor_minimo = float(context.args[1])

        global bonus_ativo
        bonus_ativo = True

        await update.message.reply_text(f"🎁 Bônus ativo: {bonus_percentual}% para depósitos a partir de R$ {bonus_valor_minimo:.2f}")
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Uso correto: /bonus <percentual> <valor_minimo>\nExemplo: /bonus 30 300")

# ================= RECEBER VALOR =================

async def receber_valor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    init_usuario(user)

    if STATE_DEPOSITAR in context.user_data:
        try:
            valor = float(update.message.text)
            bonus = 0

            if bonus_ativo and valor >= bonus_valor_minimo:
                bonus = valor * (bonus_percentual / 100)

            pix = criar_cobranca_pix(valor, user.id)
            payload_pix = pix['payload']
            context.user_data.pop(STATE_DEPOSITAR)

            await update.message.reply_text(f"💳 Pagamento PIX\nValor: R$ {valor:.2f}\n\nCopie e cole este código no seu banco:\n{payload_pix}")
        except:
            await update.message.reply_text("❌ Valor inválido.")
        return

# ================= COMANDOS ADMIN =================

async def add_estoque(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    try:
        produto = context.args[0]
        login, imgs = context.args[1].split("/")
        imagens = imgs.split(",")

        with open(f"{ESTOQUE_DIR}/{produto}.txt", "a", encoding="utf-8") as f:
            f.write("||".join([login] + imagens) + "\n")

        await update.message.reply_text("✅ Item adicionado ao estoque.")
        for img in imagens:
            await context.bot.send_photo(GRUPO_TELEGRAM, img)

    except:
        await update.message.reply_text("❌ Uso correto:\n/add_estoque produto login:senha/url1,url2")

# ================= MAIN =================


app_web = Flask(__name__)

@app_web.route("/")
def home():
    return "Bot online", 200

@app_web.route("/webhook_asaas", methods=["POST"])
def webhook():
    data = request.json
    if data.get("event") == "PAYMENT_RECEIVED":
        user_id = int(data["externalReference"])
        valor = float(data["value"])
        usuarios[user_id]["saldo"] += valor
    return "ok", 200


def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start_menu))
    app.add_handler(CommandHandler("add_estoque", add_estoque))
    app.add_handler(CommandHandler("bonus", bonus_cmd))

    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), receber_valor))

    print("🤖 Bot rodando...")
    app.run_polling()

if __name__ == "__main__":
    Thread(target=lambda: app_web.run(host="0.0.0.0", port=3000)).start()
    main()
