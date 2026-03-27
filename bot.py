import os
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
    return "✅ Bot de Reseñas de Morcones y Cubatas funcionando 24/7"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app_web.run(host="0.0.0.0", port=port)

# ==========================================
# 2. CONFIGURACIÓN DE TOKENS Y API (SEGURO)
# ==========================================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
# Convertimos el ID a texto y le quitamos cualquier espacio en blanco invisible
ADMIN_ID = str(os.environ.get("ADMIN_ID", "")).strip() 
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") 

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# --- BÚSQUEDA AUTOMÁTICA DEL MODELO ---
modelo_elegido = "gemini-1.5-flash" # Respaldo por si falla la búsqueda
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
    """Genera una respuesta profesional usando IA basada en la reseña."""
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
    usuario_id = str(update.effective_user.id)
    if usuario_id != ADMIN_ID:
        # El chivato: imprimirá esto en la consola negra de Render si te bloquea
        print(f"⚠️ BLOQUEO en /start -> Entrante: '{usuario_id}' | Esperado de Render: '{ADMIN_ID}'")
        return 
    
    await update.message.reply_text(
        "🤖 *Bot de Morcones y Cubatas Iniciado.* \n\n"
        "Cuando la API de Google esté lista, las reseñas llegarán automáticamente aquí.\n"
        "Por ahora, usa /simular para probar todo el sistema de respuestas.",
        parse_mode='Markdown'
    )

async def simular_resena(update: Update, context: ContextTypes.DEFAULT_TYPE):
    usuario_id = str(update.effective_user.id)
    if usuario_id != ADMIN_ID: 
        # El chivato para /simular
        print(f"⚠️ BLOQUEO en /simular -> Entrante: '{usuario_id}' | Esperado de Render: '{ADMIN_ID}'")
        return
    
    review_actual['negocio'] = "Morcones y Cubatas"
    review_actual['estrellas'] = 5
    review_actual['texto'] = "Los mejores morcones que he probado en mucho tiempo y los cubatas bien cargados. Ambiente de 10."
    
    mensaje = (
        f"🔔 *NUEVA RESEÑA EN \"{review_actual['negocio'].upper()}\" - {review_actual['estrellas']} ESTRELLAS*\n\n"
        f"🗣 *Cliente dice:* \"{review_actual['texto']}\""
    )
    
    teclado = [[InlineKeyboardButton("✨ Generar Respuesta con IA", callback_data="generar_ia")]]
    reply_markup = InlineKeyboardMarkup(teclado)
    
    await update.message.reply_text(mensaje, parse_mode='Markdown', reply_markup=reply_markup)
    return ESPERANDO_ACCION

async def manejar_botones_accion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data in ["generar_ia", "regenerar_ia"]:
        await query.edit_message_text("⏳ *Analizando reseña y generando respuesta con IA...*", parse_mode='Markdown')
        
        respuesta_ia = await generar_respuesta_ia(
            review_actual['texto'], review_actual['estrellas'], review_actual['negocio']
        )
        context.user_data['respuesta_borrador'] = respuesta_ia
        
        mensaje = f"🤖 *Propuesta de respuesta de la IA:*\n\n{respuesta_ia}"
        teclado = [
            [InlineKeyboardButton("✅ Publicar", callback_data="publicar")],
            [InlineKeyboardButton("🔄 Regenerar con IA", callback_data="regenerar_ia")],
            [InlineKeyboardButton("✍️ Escribir Manualmente", callback_data="escribir_manual")]
        ]
        await query.edit_message_text(mensaje, reply_markup=InlineKeyboardMarkup(teclado), parse_mode='Markdown')
        return ESPERANDO_ACCION

    elif query.data == "publicar":
        respuesta = context.user_data.get('respuesta_borrador', '')
        mensaje_doble_check = f"⚠️ ¿ESTÁS SEGURO DE QUE QUIERES PUBLICAR ESTA RESPUESTA?\n\n{respuesta}"
        teclado = [
            [InlineKeyboardButton("🟢 SÍ, PUBLICAR", callback_data="confirmar_si")],
            [InlineKeyboardButton("🔴 CANCELAR", callback_data="confirmar_no")]
        ]
        await query.edit_message_text(mensaje_doble_check, reply_markup=InlineKeyboardMarkup(teclado))
        return CONFIRMANDO_PUBLICACION

    elif query.data == "escribir_manual":
        await query.edit_message_text("✍️ *Escribe a continuación en el chat la respuesta que quieres publicar:*", parse_mode='Markdown')
        return ESPERANDO_TEXTO_MANUAL

async def recibir_texto_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    respuesta_manual = update.message.text
    context.user_data['respuesta_borrador'] = respuesta_manual
    
    mensaje_doble_check = f"⚠️ ¿ESTÁS SEGURO DE QUE QUIERES PUBLICAR ESTA RESPUESTA?\n\n{respuesta_manual}"
    teclado = [
        [InlineKeyboardButton("🟢 SÍ, PUBLICAR", callback_data="confirmar_si")],
        [InlineKeyboardButton("🔴 CANCELAR", callback_data="confirmar_no")]
    ]
    await update.message.reply_text(mensaje_doble_check, reply_markup=InlineKeyboardMarkup(teclado))
    return CONFIRMANDO_PUBLICACION

async def confirmacion_final(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "confirmar_si":
        respuesta_final = context.user_data.get('respuesta_borrador', '')
        await query.edit_message_text(f"✅ *¡RESPUESTA PUBLICADA CON ÉXITO!*\n\nTexto simulado como publicado:\n{respuesta_final}", parse_mode='Markdown')
    else:
        await query.edit_message_text("❌ *Publicación cancelada.* Usa /simular para empezar de nuevo con otra reseña.", parse_mode='Markdown')
    
    return ConversationHandler.END

# ==========================================
# 5. ARRANQUE DEL SISTEMA
# ==========================================
def main():
    if not TELEGRAM_TOKEN:
        print("❌ ERROR: Faltan las variables de entorno en Render (TELEGRAM_TOKEN).")
        return

    threading.Thread(target=run_web, daemon=True).start()
    
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("simular", simular_resena),
        ],
        states={
            ESPERANDO_ACCION: [CallbackQueryHandler(manejar_botones_accion)],
            ESPERANDO_TEXTO_MANUAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, recibir_texto_manual)],
            CONFIRMANDO_PUBLICACION: [CallbackQueryHandler(confirmacion_final)]
        },
        fallbacks=[CommandHandler("start", start)]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)

    print("🚀 Servidor y Bot de Morcones y Cubatas en marcha...")
    app.run_polling()

if __name__ == '__main__':
    main()