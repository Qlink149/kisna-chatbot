from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from kisna_chatbot.utils.logger_config import logger
from kisna_chatbot.whatsapp_functions.template.send_otp_template import send_otp_template


router = APIRouter(prefix="/whatsapp", tags=["System - WhatsApp"])


class SendOTPRequest(BaseModel):
    phone_number: str
    otp_code: str


@router.post("/send-otp")
def send_otp(request: SendOTPRequest):
    """Send the OTP authentication template (otp_fom3) to a phone number."""
    try:
        result = send_otp_template(
            phone_number=request.phone_number,
            otp_code=request.otp_code,
        )
        return {"status": "success", "response": result}
    except Exception:
        logger.exception(
            "Failed to send OTP template",
            extra={"phone_number": request.phone_number},
        )
        raise HTTPException(status_code=500, detail="Failed to send OTP template")
