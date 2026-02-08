"""
Notification Channel Implementations
Handles email, WhatsApp, and Discord notifications
"""

import asyncio
import logging
import smtplib
import ssl
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict

import aiohttp
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

logger = logging.getLogger(__name__)


def format_message(payload: dict) -> str:
    """
    Format trade signal as plain text message
    Used by WhatsApp and as email fallback
    """
    action = payload['action']
    symbol = payload['symbol']
    price = payload['price']
    sl = payload['sl']
    tp1 = payload['tp1']
    tp2 = payload['tp2']
    qty = payload['qty']
    rr = payload['rr']
    timeframe = payload['timeframe']

    message = f"""🔔 *FibAlgo Signal*

📊 Action: {action}
🏷️ Symbol: {symbol}
💰 Entry: ${price:.2f}
🛑 Stop Loss: ${sl:.2f}
🎯 TP1: ${tp1:.2f}
🎯 TP2: ${tp2:.2f}
📦 Qty: {qty}
⚖️ R:R: {rr}
⏰ Timeframe: {timeframe}"""

    return message


async def send_email(subject: str, body: str, config: dict) -> bool:
    """
    Send email via Gmail SMTP

    Args:
        subject: Email subject line
        body: HTML email body
        config: Dict containing gmail_address, gmail_app_password, email_recipient

    Returns:
        bool: True if email sent successfully, False otherwise
    """
    try:
        gmail_address = config['gmail_address']
        gmail_app_password = config['gmail_app_password']
        email_recipient = config['email_recipient']

        # Create message
        message = MIMEMultipart('alternative')
        message['Subject'] = subject
        message['From'] = gmail_address
        message['To'] = email_recipient

        # Attach HTML body
        html_part = MIMEText(body, 'html')
        message.attach(html_part)

        # Create secure SSL context
        context = ssl.create_default_context()

        # Send email via Gmail SMTP
        def send_smtp():
            with smtplib.SMTP_SSL('smtp.gmail.com', 465, context=context) as server:
                server.login(gmail_address, gmail_app_password)
                server.sendmail(gmail_address, email_recipient, message.as_string())

        # Run blocking SMTP operation in thread pool
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, send_smtp)

        logger.info(f"Email sent successfully to {email_recipient}")
        return True

    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"Email authentication failed: {str(e)}")
        logger.error("Check GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env file")
        return False
    except smtplib.SMTPException as e:
        logger.error(f"SMTP error: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"Email error: {str(e)}", exc_info=True)
        return False


async def send_whatsapp(message: str, config: dict) -> bool:
    """
    Send WhatsApp message via Twilio

    Args:
        message: Plain text message to send
        config: Dict containing account_sid, auth_token, whatsapp_from, whatsapp_to

    Returns:
        bool: True if message sent successfully, False otherwise
    """
    try:
        account_sid = config['account_sid']
        auth_token = config['auth_token']
        whatsapp_from = config['whatsapp_from']
        whatsapp_to = config['whatsapp_to']

        # Create Twilio client
        client = Client(account_sid, auth_token)

        # Send WhatsApp message
        def send_twilio():
            return client.messages.create(
                body=message,
                from_=whatsapp_from,
                to=whatsapp_to
            )

        # Run blocking Twilio operation in thread pool
        loop = asyncio.get_event_loop()
        twilio_message = await loop.run_in_executor(None, send_twilio)

        logger.info(f"WhatsApp message sent successfully. SID: {twilio_message.sid}")
        return True

    except TwilioRestException as e:
        logger.error(f"Twilio error: {e.msg} (Code: {e.code})")
        if e.code == 20003:
            logger.error("Authentication failed. Check TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN")
        elif e.code == 21211:
            logger.error("Invalid 'To' phone number. Check WHATSAPP_TO format")
        elif e.code == 63007:
            logger.error("WhatsApp message could not be sent. Ensure recipient has opted in")
        return False
    except Exception as e:
        logger.error(f"WhatsApp error: {str(e)}", exc_info=True)
        return False


async def send_discord(payload: dict, config: dict) -> bool:
    """
    Send Discord message via webhook

    Args:
        payload: Trade signal dict
        config: Dict containing webhook_url

    Returns:
        bool: True if message sent successfully, False otherwise
    """
    try:
        webhook_url = config['webhook_url']

        # Extract payload data
        action = payload['action']
        symbol = payload['symbol']
        price = payload['price']
        sl = payload['sl']
        tp1 = payload['tp1']
        tp2 = payload['tp2']
        qty = payload['qty']
        rr = payload['rr']
        timeframe = payload['timeframe']

        # Determine embed color
        color = 0x00FF00 if action == "BUY" else 0xFF0000

        # Create Discord embed
        embed = {
            "title": "🔔 FibAlgo Signal",
            "color": color,
            "fields": [
                {"name": "Action", "value": f"**{action}**", "inline": True},
                {"name": "Symbol", "value": symbol, "inline": True},
                {"name": "Timeframe", "value": timeframe, "inline": True},
                {"name": "Entry Price", "value": f"${price:.2f}", "inline": True},
                {"name": "Stop Loss", "value": f"${sl:.2f}", "inline": True},
                {"name": "R:R", "value": rr, "inline": True},
                {"name": "TP1", "value": f"${tp1:.2f}", "inline": True},
                {"name": "TP2", "value": f"${tp2:.2f}", "inline": True},
                {"name": "Quantity", "value": str(qty), "inline": True},
            ],
            "footer": {"text": "FibAlgo Trading System"},
            "timestamp": datetime.utcnow().isoformat()
        }

        # Prepare webhook payload
        webhook_payload = {
            "embeds": [embed]
        }

        # Send to Discord webhook
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=webhook_payload) as response:
                if response.status in [200, 204]:
                    logger.info(f"Discord webhook sent successfully")
                    return True
                else:
                    error_text = await response.text()
                    logger.error(f"Discord webhook failed with status {response.status}: {error_text}")
                    return False

    except aiohttp.ClientError as e:
        logger.error(f"Discord HTTP error: {str(e)}")
        return False
    except Exception as e:
        logger.error(f"Discord error: {str(e)}", exc_info=True)
        return False
