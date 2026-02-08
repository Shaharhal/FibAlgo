"""
FibAlgo Notification Relay Server
FastAPI webhook receiver for TradingView alerts
"""

import os
import logging
from datetime import datetime
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from dotenv import load_dotenv

from notifiers import send_email, send_whatsapp, send_discord, format_message

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# FastAPI app
app = FastAPI(
    title="FibAlgo Notification Relay",
    description="Webhook receiver for TradingView alerts with multi-channel notifications",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Pydantic models
class TradeSignal(BaseModel):
    action: str = Field(..., description="Trade action: BUY or SELL")
    symbol: str = Field(..., description="Trading symbol")
    price: float = Field(..., description="Entry price")
    sl: float = Field(..., description="Stop loss price")
    tp1: float = Field(..., description="Take profit 1 price")
    tp2: float = Field(..., description="Take profit 2 price")
    qty: int = Field(..., description="Quantity")
    rr: str = Field(..., description="Risk-reward ratio")
    timeframe: str = Field(..., description="Chart timeframe")

    @field_validator('action')
    @classmethod
    def validate_action(cls, v):
        v = v.upper()
        if v not in ['BUY', 'SELL']:
            raise ValueError('action must be either BUY or SELL')
        return v

    @field_validator('price', 'sl', 'tp1', 'tp2')
    @classmethod
    def validate_positive(cls, v):
        if v <= 0:
            raise ValueError('price values must be positive')
        return v

    @field_validator('qty')
    @classmethod
    def validate_quantity(cls, v):
        if v <= 0:
            raise ValueError('quantity must be positive')
        return v


class HealthResponse(BaseModel):
    status: str
    service: str
    timestamp: str
    enabled_channels: list[str]


class WebhookResponse(BaseModel):
    status: str
    message: str
    channels_notified: list[str]
    channels_failed: list[str]


# Configuration helper
def get_enabled_channels() -> dict:
    """Determine which notification channels are enabled based on env vars"""
    channels = {}

    # Email channel
    if all([
        os.getenv('GMAIL_ADDRESS'),
        os.getenv('GMAIL_APP_PASSWORD'),
        os.getenv('EMAIL_RECIPIENT')
    ]):
        channels['email'] = {
            'gmail_address': os.getenv('GMAIL_ADDRESS'),
            'gmail_app_password': os.getenv('GMAIL_APP_PASSWORD'),
            'email_recipient': os.getenv('EMAIL_RECIPIENT')
        }

    # WhatsApp channel
    if all([
        os.getenv('TWILIO_ACCOUNT_SID'),
        os.getenv('TWILIO_AUTH_TOKEN'),
        os.getenv('TWILIO_WHATSAPP_FROM'),
        os.getenv('WHATSAPP_TO')
    ]):
        channels['whatsapp'] = {
            'account_sid': os.getenv('TWILIO_ACCOUNT_SID'),
            'auth_token': os.getenv('TWILIO_AUTH_TOKEN'),
            'whatsapp_from': os.getenv('TWILIO_WHATSAPP_FROM'),
            'whatsapp_to': os.getenv('WHATSAPP_TO')
        }

    # Discord channel
    if os.getenv('DISCORD_WEBHOOK_URL'):
        channels['discord'] = {
            'webhook_url': os.getenv('DISCORD_WEBHOOK_URL')
        }

    return channels


# Routes
@app.get("/", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    enabled_channels = list(get_enabled_channels().keys())

    return HealthResponse(
        status="ok",
        service="FibAlgo Notification Relay",
        timestamp=datetime.utcnow().isoformat(),
        enabled_channels=enabled_channels
    )


@app.post("/webhook", response_model=WebhookResponse)
async def receive_webhook(signal: TradeSignal, request: Request):
    """
    Receive TradingView webhook and route to notification channels
    """
    logger.info(f"Received webhook: {signal.action} {signal.symbol} @ {signal.price}")

    # Get enabled channels
    channels = get_enabled_channels()

    if not channels:
        logger.warning("No notification channels configured")
        raise HTTPException(
            status_code=500,
            detail="No notification channels are configured. Check environment variables."
        )

    # Convert signal to dict for notifiers
    payload = signal.model_dump()

    # Track results
    notified = []
    failed = []

    # Send to each enabled channel (continue even if one fails)
    if 'email' in channels:
        try:
            subject = f"🔔 FibAlgo {signal.action} Signal: {signal.symbol}"
            body = format_email_html(payload)
            success = await send_email(subject, body, channels['email'])
            if success:
                notified.append('email')
                logger.info(f"Email notification sent successfully")
            else:
                failed.append('email')
                logger.error(f"Email notification failed")
        except Exception as e:
            failed.append('email')
            logger.error(f"Email notification error: {str(e)}", exc_info=True)

    if 'whatsapp' in channels:
        try:
            message = format_message(payload)
            success = await send_whatsapp(message, channels['whatsapp'])
            if success:
                notified.append('whatsapp')
                logger.info(f"WhatsApp notification sent successfully")
            else:
                failed.append('whatsapp')
                logger.error(f"WhatsApp notification failed")
        except Exception as e:
            failed.append('whatsapp')
            logger.error(f"WhatsApp notification error: {str(e)}", exc_info=True)

    if 'discord' in channels:
        try:
            success = await send_discord(payload, channels['discord'])
            if success:
                notified.append('discord')
                logger.info(f"Discord notification sent successfully")
            else:
                failed.append('discord')
                logger.error(f"Discord notification failed")
        except Exception as e:
            failed.append('discord')
            logger.error(f"Discord notification error: {str(e)}", exc_info=True)

    # Determine response status
    if notified:
        status = "success" if not failed else "partial_success"
        message = f"Notification sent to {len(notified)} channel(s)"
        if failed:
            message += f", {len(failed)} channel(s) failed"
    else:
        status = "error"
        message = "All notification channels failed"
        raise HTTPException(
            status_code=500,
            detail=message
        )

    return WebhookResponse(
        status=status,
        message=message,
        channels_notified=notified,
        channels_failed=failed
    )


@app.get("/test")
async def test_notifications():
    """
    Send a test notification to all enabled channels
    """
    logger.info("Test notification requested")

    # Create test signal
    test_signal = TradeSignal(
        action="BUY",
        symbol="AAPL",
        price=185.50,
        sl=182.30,
        tp1=190.20,
        tp2=193.80,
        qty=15,
        rr="2.1",
        timeframe="1H"
    )

    # Get enabled channels
    channels = get_enabled_channels()

    if not channels:
        raise HTTPException(
            status_code=500,
            detail="No notification channels are configured. Check environment variables."
        )

    # Convert signal to dict
    payload = test_signal.model_dump()

    # Track results
    notified = []
    failed = []

    # Send to each enabled channel
    if 'email' in channels:
        try:
            subject = f"🧪 TEST: FibAlgo {test_signal.action} Signal: {test_signal.symbol}"
            body = format_email_html(payload)
            success = await send_email(subject, body, channels['email'])
            if success:
                notified.append('email')
                logger.info(f"Test email sent successfully")
            else:
                failed.append('email')
        except Exception as e:
            failed.append('email')
            logger.error(f"Test email error: {str(e)}", exc_info=True)

    if 'whatsapp' in channels:
        try:
            message = "🧪 *TEST NOTIFICATION*\n\n" + format_message(payload)
            success = await send_whatsapp(message, channels['whatsapp'])
            if success:
                notified.append('whatsapp')
                logger.info(f"Test WhatsApp sent successfully")
            else:
                failed.append('whatsapp')
        except Exception as e:
            failed.append('whatsapp')
            logger.error(f"Test WhatsApp error: {str(e)}", exc_info=True)

    if 'discord' in channels:
        try:
            success = await send_discord(payload, channels['discord'])
            if success:
                notified.append('discord')
                logger.info(f"Test Discord sent successfully")
            else:
                failed.append('discord')
        except Exception as e:
            failed.append('discord')
            logger.error(f"Test Discord error: {str(e)}", exc_info=True)

    return {
        "status": "test_completed",
        "message": f"Test sent to {len(notified)} channel(s)",
        "channels_notified": notified,
        "channels_failed": failed
    }


def format_email_html(payload: dict) -> str:
    """Format payload as HTML email"""
    action = payload['action']
    color = "#28a745" if action == "BUY" else "#dc3545"

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{
                font-family: Arial, sans-serif;
                line-height: 1.6;
                color: #333;
                max-width: 600px;
                margin: 0 auto;
                padding: 20px;
            }}
            .header {{
                background-color: {color};
                color: white;
                padding: 20px;
                text-align: center;
                border-radius: 8px 8px 0 0;
            }}
            .badge {{
                font-size: 24px;
                font-weight: bold;
            }}
            .content {{
                background-color: #f8f9fa;
                padding: 20px;
                border-radius: 0 0 8px 8px;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                background-color: white;
                border-radius: 8px;
                overflow: hidden;
            }}
            td {{
                padding: 12px;
                border-bottom: 1px solid #dee2e6;
            }}
            td:first-child {{
                font-weight: bold;
                width: 40%;
                color: #6c757d;
            }}
            tr:last-child td {{
                border-bottom: none;
            }}
            .footer {{
                text-align: center;
                margin-top: 20px;
                color: #6c757d;
                font-size: 12px;
            }}
        </style>
    </head>
    <body>
        <div class="header">
            <div class="badge">🔔 FibAlgo {action} Signal</div>
        </div>
        <div class="content">
            <table>
                <tr>
                    <td>Symbol</td>
                    <td>{payload['symbol']}</td>
                </tr>
                <tr>
                    <td>Action</td>
                    <td><strong>{action}</strong></td>
                </tr>
                <tr>
                    <td>Entry Price</td>
                    <td>${payload['price']:.2f}</td>
                </tr>
                <tr>
                    <td>Stop Loss</td>
                    <td>${payload['sl']:.2f}</td>
                </tr>
                <tr>
                    <td>Take Profit 1</td>
                    <td>${payload['tp1']:.2f}</td>
                </tr>
                <tr>
                    <td>Take Profit 2</td>
                    <td>${payload['tp2']:.2f}</td>
                </tr>
                <tr>
                    <td>Quantity</td>
                    <td>{payload['qty']}</td>
                </tr>
                <tr>
                    <td>Risk:Reward</td>
                    <td>{payload['rr']}</td>
                </tr>
                <tr>
                    <td>Timeframe</td>
                    <td>{payload['timeframe']}</td>
                </tr>
            </table>
            <div class="footer">
                FibAlgo Trading System • {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}
            </div>
        </div>
    </body>
    </html>
    """
    return html


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    logger.info(f"Starting FibAlgo Notification Relay on port {port}")

    # Log enabled channels on startup
    enabled = list(get_enabled_channels().keys())
    if enabled:
        logger.info(f"Enabled notification channels: {', '.join(enabled)}")
    else:
        logger.warning("No notification channels configured! Check .env file")

    uvicorn.run(app, host="0.0.0.0", port=port)
