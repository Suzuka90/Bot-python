import logging
import re
from typing import Optional, Tuple

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

TOKEN = '###########'
TAG = '##########'
CANALE_ID =   '#########'

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def estrai_asin(url: str) -> Optional[str]:
    patterns = [
        r'(?:/dp/|/gp/product/|/gp/aw/d/)([A-Z0-9]{10})(?:/|\?|$|&)',
        r'/([A-Z0-9]{10})(?:/|\?|$|&)',
        r'\b([A-Z0-9]{10})\b'
    ]
    for pattern in patterns:
        match = re.search(pattern, url, re.IGNORECASE)
        if match:
            return match.group(1).upper()
    return None

def estrai_prezzi(testo: str) -> Tuple[Optional[float], Optional[float]]:
    testo = re.sub(r'[\U0001F300-\U0001F9FF]', '', testo)
    testo = re.sub(r'\s+', ' ', testo).strip().lower()
    pattern = r'(?:-?\d+%\s*)?(\d{1,3}(?:[.,]\d{1,2})?)\s*€?\s*(?:invece\s*(?:di)?|prima|era|anziché|→|da|\(|\s+)?\s*(\d{1,3}(?:[.,]\d{1,2})?)?\s*€?'
    match = re.search(pattern, testo)
    if not match:
        single = re.search(r'(\d{1,3}(?:[.,]\d{1,2})?)\s*€?', testo)
        if single:
            return float(single.group(1).replace(',', '.')), None
        return None, None
    try:
        p1 = float(match.group(1).replace(',', '.'))
        p2_str = match.group(2)
        p2 = float(p2_str.replace(',', '.')) if p2_str else None
        if p2 is None:
            return p1, None
        if p2 > p1:
            return p1, p2
        if p1 > p2:
            return p2, p1
        return p1, None
    except (ValueError, TypeError):
        return None, None

def pulisci_testo(testo: str) -> str:
    testo = re.sub(r'https?://[^\s<>"\']+', '', testo)
    testo = re.sub(r'\s*\n\s*', '\n', testo)
    testo = re.sub(r'\s{2,}', ' ', testo)
    testo = re.sub(r'[\U0001F300-\U0001F9FF🤑💥💰]', '', testo)
    return testo.strip()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    testo = (
        "Invia in un unico messaggio:\n"
        "descrizione prodotto (opzionale)\n"
        "prezzo attuale (eventualmente con percentuale e/o prezzo originale)\n"
        "link Amazon\n\n"
        "Esempio valido:\n"
        "Avilia – Tavolo Pieghevole Rotondo Bianco Ø80 cm\n"
        "-15% 42,66€ invece di 49,90€\n"
        "https://www.amazon.it/dp/B0FYRBNXPM\n\n"
        "Poi scrivi /posta per pubblicare."
    )
    await update.message.reply_text(testo)

async def gestisci_messaggio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    msg = update.message
    raw = (msg.text or msg.caption or "").strip()
    if not raw:
        return
    links = re.findall(r'https?://[^\s<>"\']+', raw)
    if not links:
        await msg.reply_text("Non ho trovato nessun link Amazon.")
        return
    link_amazon = next((l for l in links if 'amazon' in l.lower() or 'amzn.to' in l.lower()), links[0])
    base = link_amazon.split('?')[0].rstrip('/')
    link_dettaglio = f"{base}?tag={TAG}"
    asin = estrai_asin(link_amazon)
    link_carrello = (
        f"https://www.amazon.it/gp/aws/cart/add.html?AssociateTag={TAG}&ASIN.1={asin}&Quantity.1=1"
        if asin else link_dettaglio
    )
    keyboard = [[
        InlineKeyboardButton("👀 Dettaglio", url=link_dettaglio),
        InlineKeyboardButton("🛒 Carrello", url=link_carrello),
    ]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    cleaned = pulisci_testo(raw)
    lines = [l.strip() for l in cleaned.split('\n') if l.strip()]

    # Modifica: Parsing robusto assumendo ordine descrizione -> prezzo -> link
    price_index = -1
    for i, line in enumerate(lines):
        # Criterio restrittivo: riga con numero (decimale o intero) seguito da €/euro/eur
        if re.search(r'(?:\d+[.,]\d{1,2}|\d+)\s*(?:€|euro|eur)', line, re.IGNORECASE):
            price_index = i
            break

    if price_index == -1:
        # Fallback: ultima riga con numero e simbolo moneta
        for i in range(len(lines)-1, -1, -1):
            if re.search(r'\d+[.,]?\d*', lines[i]) and re.search(r'[€$£]|euro|eur', lines[i], re.IGNORECASE):
                price_index = i
                break

    if price_index <= 0:
        # Nessuna riga prezzo o è la prima -> nessuna descrizione
        descrizione = ""
        price_line = lines[0] if lines else cleaned
    else:
        # Tutto prima della riga prezzo -> descrizione
        descrizione_lines = lines[:price_index]
        descrizione = ' '.join(l for l in descrizione_lines if l).strip()
        price_line = lines[price_index]

    desc_part = f"{descrizione}\n\n" if descrizione else ""

    prezzo_attuale, prezzo_precedente = estrai_prezzi(price_line or cleaned)
    if prezzo_attuale is None:
        await msg.reply_text(
            "Non riesco a interpretare il prezzo.\n"
            "Formati suggeriti:\n"
            "• 42,66 €\n"
            "• 42,66€ invece di 49,90€\n"
            "• -15% 42,66€\n"
            "• 49,90 → 42,66 €"
        )
        return
    prezzo_str = f"{prezzo_attuale:,.2f} €".replace(".", ",")
    if prezzo_precedente and prezzo_precedente > prezzo_attuale:
        sconto_perc = round(100 - (prezzo_attuale / prezzo_precedente * 100))
        risparmio = round(prezzo_precedente - prezzo_attuale, 2)
        riga_prezzo = (
            f"🤑 {prezzo_str} (invece di {prezzo_precedente:,.2f} €)".replace(".", ",")
            + "\n\n"
            + f"💥 SCONTO {sconto_perc}% 💥\n"
            + f"💰 RISPARMI {risparmio:,.2f} € 💰".replace(".", ",")
        )
    else:
        riga_prezzo = f"🤑 {prezzo_str}"
    caption = (
        "🔥 Offerta Amazon 🔥\n"
        f"{desc_part}"
        f"{riga_prezzo}"
    )
    file_id = None
    if msg.photo:
        file_id = msg.photo[-1].file_id
    elif msg.document and msg.document.mime_type.startswith('image/'):
        file_id = msg.document.file_id
    context.user_data.update({
        'caption': caption,
        'reply_markup': reply_markup,
        'file_id': file_id,
    })
    anteprima = (
        "Ecco come apparirà sul canale:\n\n"
        f"{caption}\n\n"
        "👀 Dettaglio    🛒 Carrello\n"
        f"{'📸 Con foto' if file_id else '⚠️ Senza foto'}\n\n"
        "Scrivi /posta per confermare la pubblicazione."
    )
    await msg.reply_text(anteprima, parse_mode='HTML')

async def posta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if 'caption' not in context.user_data:
        await update.message.reply_text("Prima invia descrizione, prezzo e link.")
        return
    caption = context.user_data['caption']
    markup = context.user_data.get('reply_markup')
    photo = context.user_data.get('file_id')
    try:
        if photo:
            await context.bot.send_photo(
                chat_id=CANALE_ID,
                photo=photo,
                caption=caption,
                parse_mode='HTML',
                reply_markup=markup
            )
            await update.message.reply_text("Pubblicato con foto.")
        else:
            await context.bot.send_message(
                chat_id=CANALE_ID,
                text=caption,
                parse_mode='HTML',
                reply_markup=markup
            )
            await update.message.reply_text("Pubblicato (solo testo).")
        context.user_data.clear()
    except Exception as e:
        await update.message.reply_text(f"Errore durante la pubblicazione: {str(e)}\nVerifica i permessi del bot nel canale.")

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("posta", posta))
    app.add_handler(MessageHandler(
        filters.TEXT | filters.CAPTION | filters.PHOTO | filters.Document.IMAGE,
        gestisci_messaggio
    ))
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()