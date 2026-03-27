import os
import json
import logging
import threading
from flask import Flask
import google.generativeai as genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)

# ==========================================
# 1. SERVIDOR WEB OCULTO (Para Render 24/7)
# ==========================================
app_web = Flask(__name__)

@app_web.route('/')
def home():
    return "✅ Bot de Reseñas funcionando 24/7"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app_web.run(host="0.0.0.0", port=port)

# ==========================================
# 2. CONFIGURACIÓN DE TOKENS Y API (SEGURO)
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ADMIN_ID = str(os.environ.get("ADMIN_ID", "")).strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# --- BÚSQUEDA AUTOMÁTICA DEL MODELO ---
modelo_elegido = "gemini-1.5-flash"
try:
    modelos_disponibles = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
    if modelos_disponibles:
        modelo_elegido = next((m for m in modelos_disponibles if "flash" in m), modelos_disponibles[0])
        modelo_elegido = modelo_elegido.replace("models/", "")
except Exception as e:
    print(f"Aviso al buscar modelos: {e}")

model = genai.GenerativeModel(modelo_elegido)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# ==========================================
# 3. ESTADOS Y VARIABLES GLOBALES
# ==========================================
ESPERANDO_ACCION, ESPERANDO_TEXTO_MANUAL, CONFIRMANDO_PUBLICACION = range(3)
review_actual = {}

# ==========================================
# 4. FUNCIONES DEL BOT
# ==========================================
async def generar_respuesta_ia(texto_resena, estrellas, negocio):
    prompt = f"""
    Eres el gerente de atención al cliente de un negocio llamado '{negocio}'. 
    Has recibido una reseña de {estrellas} estrellas que dice: '{texto_resena}'.
    Escribe una respuesta profesional, agradecida (si es positiva) o resolutiva y empática (si es negativa). 
    Sé breve, natural y directo. Estrictamente prohibido usar asteriscos, guiones bajos o comillas.
    """
    try:
        response = await model.generate_content_async(prompt)
        texto_limpio = response.text.strip().replace('*', '').replace('_', '').replace('`', '')
        return texto_limpio
    except Exception as e:
        error_limpio = str(e).replace('*', '').replace('_', '')
        return f"Error en la IA: {error_limpio}"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear() # ✅ LIMPIEZA: Borra cualquier estado bloqueado
    
    usuario_id = str(update.effective_user.id)
    if usuario_id != ADMIN_ID:
        print(f"⚠️ BLOQUEO en /start -> Entrante: '{usuario_id}' | Esperado de Render: '{ADMIN_ID}'")
        return ConversationHandler.END # ✅ Cierra posibles bucles

    await update.message.reply_text(
        "🤖 *Bot de Gestión de Reseñas Iniciado.* \n\n"
        "Cuando la API de Google esté lista, las reseñas llegarán automáticamente aquí.\n"
        "Por ahora, usa /simular para probar todo el sistema de respuestas.",
        parse_mode='Markdown'
    )
    return ConversationHandler.END

async def simular_resena(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear() # Limpieza total
    
    usuario_id = str(update.effective_user.id)
    if usuario_id != ADMIN_ID:
        print(f"⚠️ BLOQUEO en /simular -> Entrante: '{usuario_id}' | Esperado de Render: '{ADMIN_ID}'")
        return ConversationHandler.END

    # VOLVEMOS A LA RESEÑA FIJA: Cero cuelgues, cero retrasos.
    review_actual['negocio'] = "Casa Sobotta"
    review_actual['estrellas'] = 5
    review_actual['texto'] = "Sitio de 10. Fuimos el día de la inauguración y la verdad no pudimos estar mas acertados , un 10 tanto al servicio como a la comida, todo espectacular 👌"
    
    mensaje = (
        f"🔔 *NUEVA RESEÑA EN \"{review_actual['negocio'].upper()}\" - {review_actual['estrellas']} ESTRELLAS*\n\n"
        f"🗣 *Cliente dice:* \"{review_actual['texto']}\""
    )
    
    teclado = [[InlineKeyboardButton("✨ Generar Respuesta con IA", callback_data="generar_ia")]]
    reply_markup = InlineKeyboardMarkup(teclado)
    
    await update.message.reply_text(mensaje, parse_mode='Markdown', reply_markup=reply_markup)
    return ESPERANDO_ACCION    context.user_data.clear() # ✅ LIMPIEZA: Cada simulación nueva empieza de cero al 100%
    
    usuario_id = str(update.effective_user.id)
    if usuario_id != ADMIN_ID:
        print(f"⚠️ BLOQUEO en /simular -> Entrante: '{usuario_id}' | Esperado de Render: '{ADMIN_ID}'")
        return ConversationHandler.END

    # Mensaje de carga mientras la IA genera la reseña
    msg_carga = await update.message.reply_text("⏳ *Generando reseña de prueba...*", parse_mode='Markdown')

    prompt = """
    Invéntate una reseña realista de Google Maps para un bar-restaurante llamado "Casa Sobotta".
    Debes devolver ÚNICAMENTE un JSON con este formato exacto, sin texto extra ni backticks:
    {"estrellas": 4, "texto": "El texto de la reseña aquí"}
    Las estrellas deben ser un número entero del 1 al 5.
    El texto debe sonar natural, como lo escribiría un cliente real. Sin asteriscos ni comillas dentro del texto.
    Varía el tipo de reseña: a veces positiva, a veces negativa, a veces mixta.
    """

    try:
        response = await model.generate_content_async(prompt)
        datos = json.loads(response.text.strip())
        review_actual['negocio'] = "Casa Sobotta"
        review_actual['estrellas'] = datos['estrellas']
        review_actual['texto'] = datos['texto']
    except Exception as e:
        review_actual['negocio'] = "Casa Sobotta"
        review_actual['estrellas'] = 3
        review_actual['texto'] = f"(Error generando reseña: {e})"

    mensaje = (
        f"🔔 *NUEVA RESEÑA EN \"{review_actual['negocio'].upper()}\" - {review_actual['estrellas']} ESTRELLAS*\n\n"
        f"🗣 *Cliente dice:* \"{review_actual['texto']}\""
    )

    teclado = [[InlineKeyboardButton("✨ Generar Respuesta con IA", callback_data="generar_ia")]]
    await msg_carga.edit_text(mensaje, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(teclado))
    return ESPERANDO_ACCION

async def manejar_botones_accion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    texto_resena = review_actual.get('texto', '')
    estrellas = review_actual.get('estrellas', '')

    if query.data == "generar_ia":
        await query.edit_message_reply_markup(reply_markup=None)

        mensaje_carga = await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="⏳ *Analizando reseña y generando respuesta con IA...*",
            parse_mode='Markdown'
        )

        respuesta_ia = await generar_respuesta_ia(texto_resena, estrellas, review_actual['negocio'])
        context.user_data['respuesta_borrador'] = respuesta_ia

        mensaje = f"🤖 *Propuesta de respuesta (IA):*\n\n{respuesta_ia}"

        teclado = [
            [InlineKeyboardButton("✅ Publicar", callback_data="publicar")],
            [InlineKeyboardButton("🔄 Regenerar con IA", callback_data="regenerar_ia")],
            [InlineKeyboardButton("✍️ Escribir Manualmente", callback_data="escribir_manual")]
        ]
        await mensaje_carga.edit_text(mensaje, reply_markup=InlineKeyboardMarkup(teclado), parse_mode='Markdown')
        return ESPERANDO_ACCION

    elif query.data == "regenerar_ia":
        await query.edit_message_text("⏳ *Generando una respuesta diferente...*", parse_mode='Markdown')

        respuesta_ia = await generar_respuesta_ia(texto_resena, estrellas, review_actual['negocio'])
        context.user_data['respuesta_borrador'] = respuesta_ia

        mensaje = f"🤖 *Propuesta de respuesta (IA):*\n\n{respuesta_ia}"

        teclado = [
            [InlineKeyboardButton("✅ Publicar", callback_data="publicar")],
            [InlineKeyboardButton("🔄 Regenerar con IA", callback_data="regenerar_ia")],
            [InlineKeyboardButton("✍️ Escribir Manualmente", callback_data="escribir_manual")]
        ]
        await query.edit_message_text(mensaje, reply_markup=InlineKeyboardMarkup(teclado), parse_mode='Markdown')
        return ESPERANDO_ACCION

    elif query.data == "publicar":
        respuesta = context.user_data.get('respuesta_borrador', '')
        mensaje_doble_check = (
            f"⚠️ *¿ESTÁS SEGURO DE QUE QUIERES PUBLICAR ESTA RESPUESTA?*\n\n"
            f"⭐️ *Reseña ({estrellas} estrellas):*\n_{texto_resena}_\n\n"
            f"💬 *Respuesta a publicar:*\n{respuesta}"
        )
        teclado = [
            [InlineKeyboardButton("🟢 SÍ, PUBLICAR", callback_data="confirmar_si")],
            [InlineKeyboardButton("🔴 CANCELAR", callback_data="confirmar_no")]
        ]
        await query.edit_message_text(mensaje_doble_check, reply_markup=InlineKeyboardMarkup(teclado), parse_mode='Markdown')
        return CONFIRMANDO_PUBLICACION

    elif query.data == "escribir_manual":
        await query.edit_message_text("✍️ *Escribe a continuación en el chat la respuesta que quieres publicar:*", parse_mode='Markdown')
        return ESPERANDO_TEXTO_MANUAL

async def recibir_texto_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    respuesta_manual = update.message.text
    context.user_data['respuesta_borrador'] = respuesta_manual

    texto_resena = review_actual.get('texto', '')
    estrellas = review_actual.get('estrellas', '')

    mensaje_doble_check = (
        f"⚠️ *¿ESTÁS SEGURO DE QUE QUIERES PUBLICAR ESTA RESPUESTA?*\n\n"
        f"⭐️ *Reseña ({estrellas} estrellas):*\n_{texto_resena}_\n\n"
        f"💬 *Respuesta a publicar:*\n{respuesta_manual}"
    )
    teclado = [
        [InlineKeyboardButton("🟢 SÍ, PUBLICAR", callback_data="confirmar_si")],
        [InlineKeyboardButton("🔴 CANCELAR", callback_data="confirmar_no")]
    ]
    await update.message.reply_text(mensaje_doble_check, reply_markup=InlineKeyboardMarkup(teclado), parse_mode='Markdown')
    return CONFIRMANDO_PUBLICACION

async def confirmacion_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "confirmar_si":
        respuesta_final = context.user_data.get('respuesta_borrador', '')
        texto_resena = review_actual.get('texto', '')
        estrellas = review_actual.get('estrellas', '')

        mensaje_exito = (
            f"✅ *¡RESPUESTA PUBLICADA CON ÉXITO!*\n\n"
            f"⭐️ *Reseña ({estrellas} estrellas):*\n_{texto_resena}_\n\n"
            f"💬 *Tu respuesta publicada:*\n{respuesta_final}"
        )
        await query.edit_message_text(mensaje_exito, parse_mode='Markdown')
    else:
        await query.edit_message_text("❌ *Publicación cancelada.* Usa /simular para empezar de nuevo.", parse_mode='Markdown')

    return ConversationHandler.END

# ==========================================
# 5. ARRANQUE DEL SISTEMA
# ==========================================
def main():
    if not TELEGRAM_TOKEN:
        print("❌ ERROR: Faltan las variables de entorno.")
        return

    threading.Thread(target=run_web, daemon=True).start()

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("simular", simular_resena)],
        states={
            ESPERANDO_ACCION: [CallbackQueryHandler(manejar_botones_accion)],
            ESPERANDO_TEXTO_MANUAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_texto_manual)],
            CONFIRMANDO_PUBLICACION: [CallbackQueryHandler(confirmacion_final)]
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True # ✅ CLAVE MAGICA: Permite forzar el inicio de una nueva simulación en cualquier momento
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)

    print("🚀 Servidor y Bot en marcha...")
    app.run_polling()

if __name__ == '__main__':
    main()