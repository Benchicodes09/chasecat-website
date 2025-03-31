import time
import requests
import logging
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, ConversationHandler

# --- CONFIGURATION ---
BOT_TOKEN = "7389457156:AAEc_N3pzVZ4yDnuCKbxQCLyvPf2PvFkKqo"
SOLANA_ADDRESS = "HKmBnM1ErJjCk1jtvtRDE9sWnDizXeqLCxrMove5CfUS"
EBOOK_FILE = "ebook.pdf"  # Local ebook file to be sent
SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"
REQUIRED_SOL = 0.00613  # Accept only 0.00613 SOL
TOLERANCE = 0.00001     # Allow small variation for network fees

# We'll store two mappings:
# USER_WALLETS maps telegram user_id to the wallet they used.
USER_WALLETS = {}
# USED_WALLETS maps wallet_address to the timestamp when the ebook was delivered.
USED_WALLETS = {}

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- STATES ---
WAITING_FOR_WALLET = 1

# --- COMMAND: Start ---
def start(update: Update, context: CallbackContext) -> None:
    message = (
        "🚀 **Welcome to the ChaseCat Ebook Payment Bot!** 🚀\n\n"
        "📖 **Price:** 0.00613 SOL (Solana Only)\n"
        "💰 **Send Payment To:**\n"
        f"```{SOLANA_ADDRESS}```\n\n"
        "⚠️ **Important:**\n"
        "- Only send **exactly** 0.00613 SOL.\n"
        "- After sending, use **/checkpayment** and enter your wallet address.\n\n"
        "After a successful payment (and within 45 seconds of the transaction), you’ll receive the ebook instantly!\n\n"
        "Note: Once a wallet has been used to claim the ebook, it cannot be used again."
    )
    update.message.reply_text(message, parse_mode="Markdown")

# --- COMMAND: Check Payment (Ask for Wallet) ---
def check_payment(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id

    # Prevent duplicate claims by this user
    if user_id in USER_WALLETS:
        update.message.reply_text("✅ You have already received the ebook. No duplicate claims allowed.")
        return ConversationHandler.END

    update.message.reply_text("🔍 Please enter your Solana wallet address to verify payment:")
    return WAITING_FOR_WALLET

# --- RECEIVE WALLET ADDRESS ---
def receive_wallet(update: Update, context: CallbackContext) -> int:
    user_id = update.message.from_user.id
    wallet_address = update.message.text.strip()

    # Basic Solana wallet validation
    if len(wallet_address) < 32 or len(wallet_address) > 44:
        update.message.reply_text("❌ Invalid Solana wallet address. Please try again.")
        return WAITING_FOR_WALLET

    # Check if this wallet was already used
    if wallet_address in USED_WALLETS:
        update.message.reply_text("❌ This wallet address has already received the ebook and cannot be used again.")
        return ConversationHandler.END

    update.message.reply_text("🔍 Checking your payment... Please wait.")

    try:
        # Fetch recent transactions for our receiving address
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getSignaturesForAddress",
            "params": [SOLANA_ADDRESS, {"limit": 10}]
        }
        headers = {"Content-Type": "application/json"}
        response = requests.post(SOLANA_RPC_URL, json=payload, headers=headers)

        if response.status_code != 200:
            update.message.reply_text("⚠️ Error: Unable to fetch transactions. Try again later.")
            logger.error(f"Solana RPC Error: {response.status_code} - {response.text}")
            return ConversationHandler.END

        transactions = response.json().get("result", [])
        if not transactions:
            update.message.reply_text("❌ No recent transactions found. Please check and try again.")
            return ConversationHandler.END

        logger.info(f"🔍 Checking transactions for wallet: {wallet_address}")

        for tx in transactions:
            signature = tx.get("signature")

            # Fetch transaction details using getTransaction
            tx_details_payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getTransaction",
                "params": [signature, {"encoding": "jsonParsed"}]
            }
            tx_details_response = requests.post(SOLANA_RPC_URL, json=tx_details_payload, headers=headers)

            if tx_details_response.status_code != 200:
                continue

            tx_data = tx_details_response.json().get("result", {})
            received = False

            # Loop over transaction instructions to see if a payment from the provided wallet was made
            for instruction in tx_data.get("transaction", {}).get("message", {}).get("instructions", []):
                if "parsed" in instruction and instruction["programId"] == "11111111111111111111111111111111":
                    parsed_info = instruction["parsed"]["info"]
                    if parsed_info["destination"] == SOLANA_ADDRESS and parsed_info["source"] == wallet_address:
                        amount_sol = float(parsed_info["lamports"]) / 1_000_000_000  # Convert lamports to SOL
                        if abs(amount_sol - REQUIRED_SOL) <= TOLERANCE:
                            received = True
                            break

            if received:
                # Verify that the transaction is recent (within 45 seconds)
                block_time = tx_data.get("blockTime")
                if block_time is None:
                    update.message.reply_text("❌ Cannot verify transaction time. Please try again later.")
                    return ConversationHandler.END

                current_time = time.time()
                if (current_time - block_time) > 45:
                    update.message.reply_text("❌ Payment expired: more than 45 seconds have passed since the transaction. Please send a new payment.")
                    return ConversationHandler.END

                logger.info(f"✅ Valid payment from {wallet_address}: {amount_sol} SOL")
                update.message.reply_text(
                    f"✅ **Payment received!** 🎉\n\n"
                    "Your ChaseCat Ebook is on the way! 📖\n\n"
                    f"🔗 [View Transaction](https://solscan.io/tx/{signature})\n\n"
                    "Thank you for your support! 🚀",
                    parse_mode="Markdown"
                )
                try:
                    with open(EBOOK_FILE, "rb") as ebook_file:
                        update.message.reply_document(
                            document=ebook_file,
                            filename="ChaseCat_Ebook.pdf",
                            caption="Your ChaseCat Ebook!"
                        )
                except FileNotFoundError:
                    update.message.reply_text("⚠️ Error: Ebook file not found on the server.")
                    logger.error("Ebook file not found: ensure 'ebook.pdf' is in the same directory as the script.")
                # Record that this wallet has been used and prevent future claims
                USED_WALLETS[wallet_address] = current_time
                USER_WALLETS[user_id] = wallet_address
                return ConversationHandler.END

        update.message.reply_text("❌ No valid payment found from your wallet. Make sure you sent exactly 0.00613 SOL and try again.")

    except requests.exceptions.RequestException as e:
        logger.error(f"⚠️ Network error: {e}")
        update.message.reply_text("⚠️ Network issue while checking payments. Please try again later.")

    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        update.message.reply_text("⚠️ Unexpected error. Please try again later.")

    return ConversationHandler.END

# --- MAIN FUNCTION ---
def main():
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    # Define conversation handler for payment verification
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("checkpayment", check_payment)],
        states={WAITING_FOR_WALLET: [MessageHandler(Filters.text & ~Filters.command, receive_wallet)]},
        fallbacks=[]
    )

    # Add command handlers
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(conv_handler)

    # Start the bot
    updater.start_polling()
    updater.idle()

# Run the bot
if __name__ == '__main__':
    main()
